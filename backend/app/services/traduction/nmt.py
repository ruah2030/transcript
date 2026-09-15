"""Moteurs NMT sur CTranslate2 : Opus-MT et Argos.

Les deux partagent le même moteur d'inférence et la même mécanique. Ils ne
diffèrent que par l'endroit où sont les poids et la façon de tokeniser :

    Opus-MT   modèles Helsinki-NLP convertis par ct2-transformers-converter,
              tokenizer chargé depuis transformers (MarianTokenizer).
    Argos     paquets installés par argostranslate, tokenizer SentencePiece
              lu directement dans le dossier du paquet.

Opus-MT existe en paires directes. Argos pivote par l'anglais : fr->es se
fait en fr->en puis en->es, donc deux fois le temps. Pour en<->fr les deux
sont en une seule passe.

L'inférence CTranslate2 est bloquante et libère le GIL. On l'exécute dans un
pool de threads pour ne pas figer la boucle asyncio.
"""

from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.config import reglages
from app.core.erreurs import CapaciteAbsente, MoteurIndisponible
from app.domain import decoupage, typographie
from app.services.traduction.base import (
    Capacite, Etat, MoteurTraduction, Progression, Requete, Resultat,
)

# Un seul pool pour tout le processus : sans GPU, la concurrence ne sert
# à rien, les coeurs sont déjà saturés par le batching interne.
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ct2")

CAPACITES_NMT = frozenset({Capacite.TRADUCTION})


def _threads() -> int:
    configure = reglages().ct2_threads
    return configure if configure > 0 else (os.cpu_count() or 4)


class _MaillonCT2:
    """Un modèle CTranslate2 chargé, pour une paire donnée.

    Le chargement est paresseux et mis en cache : le premier appel paie
    quelques secondes, les suivants réutilisent l'objet en mémoire.
    """

    def __init__(self, dossier: Path, tokeniseur):
        import ctranslate2

        self.dossier = dossier
        self.tokeniseur = tokeniseur
        self.traducteur = ctranslate2.Translator(
            str(dossier),
            device="cpu",
            compute_type=reglages().ct2_calcul,
            intra_threads=_threads(),
            inter_threads=1,
        )

    def traduire_lot(self, phrases: list[str]) -> list[str]:
        cfg = reglages()
        entree = [self.tokeniseur.encoder(p) for p in phrases]
        sorties = self.traducteur.translate_batch(
            entree,
            batch_type="tokens",
            max_batch_size=cfg.ct2_lots_tokens,
            beam_size=cfg.ct2_faisceau,
            length_penalty=cfg.ct2_penalite_longueur,
            repetition_penalty=cfg.ct2_penalite_repetition,
            no_repeat_ngram_size=cfg.ct2_sans_repetition,
            max_decoding_length=512,
            replace_unknowns=cfg.ct2_recopier_inconnus,
        )
        return [self.tokeniseur.decoder(s.hypotheses[0]) for s in sorties]


class _TokeniseurMarian:
    """Tokenizer des modèles Opus-MT, via transformers."""

    def __init__(self, repo: str):
        from transformers import AutoTokenizer

        self._tok = AutoTokenizer.from_pretrained(repo)

    def encoder(self, texte: str) -> list[str]:
        return self._tok.convert_ids_to_tokens(self._tok.encode(texte))

    def decoder(self, jetons: list[str]) -> str:
        return self._tok.decode(
            self._tok.convert_tokens_to_ids(jetons), skip_special_tokens=True
        )


class _TokeniseurSentencePiece:
    """Tokenizer des paquets Argos, lu dans le dossier du modèle."""

    def __init__(self, chemin: Path):
        import sentencepiece as spm

        self._sp = spm.SentencePieceProcessor(model_file=str(chemin))

    def encoder(self, texte: str) -> list[str]:
        return self._sp.encode(texte, out_type=str)

    def decoder(self, jetons: list[str]) -> str:
        return self._sp.decode(jetons)


class MoteurNMT(MoteurTraduction):
    """Base commune. Les sous-classes fournissent la résolution des maillons."""

    capacites = CAPACITES_NMT
    debit_mots_seconde = 200.0

    def __init__(self):
        self._maillons: dict[str, _MaillonCT2] = {}

    # -- à implémenter par les sous-classes ------------------------------

    def _chaine(self, source: str, cible: str) -> list[tuple[str, str]]:
        """Suite de sauts à enchaîner. Une paire directe = un seul saut."""
        raise NotImplementedError

    def _charger(self, source: str, cible: str) -> _MaillonCT2:
        raise NotImplementedError

    def _paires_installees(self) -> list[str]:
        raise NotImplementedError

    # -- commun ----------------------------------------------------------

    def _maillon(self, source: str, cible: str) -> _MaillonCT2:
        cle = f"{source}-{cible}"
        if cle not in self._maillons:
            self._maillons[cle] = self._charger(source, cible)
        return self._maillons[cle]

    async def etat(self) -> Etat:
        try:
            import ctranslate2  # noqa: F401
        except ImportError:
            return Etat(
                False, "ctranslate2 n'est pas installé", [],
                "pip install ctranslate2 sentencepiece transformers",
            )

        paires = self._paires_installees()
        if not paires:
            return Etat(False, "aucun modèle installé", [], self.remede_modele())
        return Etat(True, f"{len(paires)} paire(s) disponible(s)", paires)

    def remede_modele(self) -> str:
        return "Aucun modèle trouvé."

    async def traduire(
        self, requete: Requete, progression: Progression = None
    ) -> Resultat:
        if requete.capacite is not Capacite.TRADUCTION:
            raise CapaciteAbsente(
                f"{self.libelle} ne sait pas faire « {requete.capacite} ».",
                "Les modèles NMT sont bilingues : ils traduisent d'une langue "
                "vers une autre. Réparer ou réviser un texte dans sa propre "
                "langue demande un LLM. Choisis le moteur « llm » ou « hybride ».",
            )

        phrases = decoupage.decouper_phrases(requete.texte)
        if not phrases:
            return Resultat(texte="", moteur=self.nom)

        sauts = self._chaine(requete.source, requete.cible)
        total = len(phrases) * len(sauts)
        courant = [p.texte for p in phrases]
        faits = 0

        for source, cible in sauts:
            maillon = self._maillon(source, cible)
            etiquette = f"{source} → {cible}"
            if progression:
                await progression(faits, total, etiquette)

            boucle = asyncio.get_running_loop()
            courant = await boucle.run_in_executor(
                _POOL, maillon.traduire_lot, courant
            )
            faits += len(phrases)
            if progression:
                await progression(faits, total, etiquette)

        texte = decoupage.reassembler_phrases(phrases, courant)
        return Resultat(
            texte=typographie.appliquer(texte, requete.cible),
            moteur=self.nom,
        )


class MoteurOpusMT(MoteurNMT):
    """Opus-MT (Helsinki-NLP) converti en CTranslate2.

    Convention de nommage : modeles/opus-<source>-<cible>-ct2/
    """

    nom = "opusmt"
    libelle = "Opus-MT (CTranslate2)"
    debit_mots_seconde = 220.0

    MOTIF = re.compile(r"^opus-([a-z]{2,3})-([a-z]{2,3})-ct2$")

    def remede_modele(self) -> str:
        return (
            "ct2-transformers-converter \\\n"
            "  --model Helsinki-NLP/opus-mt-en-fr \\\n"
            f"  --output_dir {reglages().dossier_modeles / 'opus-en-fr-ct2'} \\\n"
            "  --quantization int8\n\n"
            "Le dossier doit s'appeler exactement opus-<source>-<cible>-ct2."
        )

    def _dossier(self, source: str, cible: str) -> Path:
        return reglages().dossier_modeles / f"opus-{source}-{cible}-ct2"

    def _paires_installees(self) -> list[str]:
        racine = reglages().dossier_modeles
        if not racine.is_dir():
            return []
        paires = []
        for d in sorted(racine.iterdir()):
            m = self.MOTIF.match(d.name)
            if m and (d / "model.bin").is_file():
                paires.append(f"{m.group(1)}-{m.group(2)}")
        return paires

    def _chaine(self, source: str, cible: str) -> list[tuple[str, str]]:
        if self._dossier(source, cible).is_dir():
            return [(source, cible)]
        # Repli sur le pivot anglais si la paire directe manque.
        if "en" not in (source, cible):
            if (self._dossier(source, "en").is_dir()
                    and self._dossier("en", cible).is_dir()):
                return [(source, "en"), ("en", cible)]
        raise MoteurIndisponible(
            f"Aucun modèle Opus-MT pour {source} → {cible}.",
            f"Convertis-le puis relance :\n"
            f"  ct2-transformers-converter --model Helsinki-NLP/opus-mt-{source}-{cible} "
            f"--output_dir modeles/opus-{source}-{cible}-ct2 --quantization int8",
        )

    def _charger(self, source: str, cible: str) -> _MaillonCT2:
        dossier = self._dossier(source, cible)
        if not (dossier / "model.bin").is_file():
            raise MoteurIndisponible(f"Modèle absent : {dossier}")
        # Un marqueur écrit à la conversion dit quel dépôt HuggingFace
        # fournit le tokenizer : les modèles « tc-big » ne suivent pas la
        # même convention de nommage que les anciens.
        marqueur = dossier / "depot.txt"
        repo = (
            marqueur.read_text(encoding="utf-8").strip()
            if marqueur.is_file()
            else f"Helsinki-NLP/opus-mt-{source}-{cible}"
        )
        try:
            return _MaillonCT2(dossier, _TokeniseurMarian(repo))
        except Exception as e:
            raise MoteurIndisponible(
                f"Chargement impossible de {repo}", str(e)
            ) from e


class MoteurArgos(MoteurNMT):
    """Paquets Argos Translate installés localement.

    Argos pivote systématiquement par l'anglais : une paire sans anglais
    coûte deux passes.
    """

    nom = "argos"
    libelle = "Argos Translate"
    debit_mots_seconde = 190.0

    MOTIF = re.compile(r"^translate-([a-z]{2,3})_([a-z]{2,3})")

    def remede_modele(self) -> str:
        return (
            "pip install argostranslate\n"
            "python -c \"import argostranslate.package as p; "
            "p.update_package_index(); "
            "pkg = next(x for x in p.get_available_packages() "
            "if x.from_code=='en' and x.to_code=='fr'); "
            "p.install_from_path(pkg.download())\"\n\n"
            f"Dossier scanné : {self._racine()}"
        )

    @staticmethod
    def _racine() -> Path:
        depuis_env = os.environ.get("ARGOS_PACKAGES_DIR")
        if depuis_env:
            return Path(depuis_env)
        return Path.home() / ".local" / "share" / "argos-translate" / "packages"

    def _dossier(self, source: str, cible: str) -> Path | None:
        racine = self._racine()
        if not racine.is_dir():
            return None
        prefixe = f"translate-{source}_{cible}"
        for d in sorted(racine.iterdir()):
            if d.is_dir() and d.name.startswith(prefixe):
                return d
        return None

    def _paires_installees(self) -> list[str]:
        racine = self._racine()
        if not racine.is_dir():
            return []
        paires = []
        for d in sorted(racine.iterdir()):
            m = self.MOTIF.match(d.name)
            if m:
                paires.append(f"{m.group(1)}-{m.group(2)}")
        return paires

    def _chaine(self, source: str, cible: str) -> list[tuple[str, str]]:
        if self._dossier(source, cible):
            return [(source, cible)]
        if "en" not in (source, cible):
            if self._dossier(source, "en") and self._dossier("en", cible):
                return [(source, "en"), ("en", cible)]
        raise MoteurIndisponible(
            f"Aucun paquet Argos pour {source} → {cible}.",
            "Installe-le avec argostranslate, puis relance le service.",
        )

    def _charger(self, source: str, cible: str) -> _MaillonCT2:
        dossier = self._dossier(source, cible)
        if dossier is None:
            raise MoteurIndisponible(f"Paquet Argos absent : {source} → {cible}")
        modele, sp = dossier / "model", dossier / "sentencepiece.model"
        if not modele.is_dir() or not sp.is_file():
            raise MoteurIndisponible(f"Paquet Argos incomplet : {dossier}")
        return _MaillonCT2(modele, _TokeniseurSentencePiece(sp))
