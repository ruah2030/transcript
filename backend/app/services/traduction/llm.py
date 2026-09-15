"""Moteur LLM local : Ollama ou toute API compatible OpenAI.

Reprend la mécanique éprouvée de `traduire.py` :

  - cache par segment sur disque, pour reprendre après interruption ;
  - contexte glissant (fin de la production précédente) pour que le ton ne
    dérive pas d'un segment à l'autre ;
  - marqueurs [DOUTE] rassemblés à part, comme points de relecture.

Seul moteur capable des modes monolingues (réparation, révision) : réécrire
un mauvais français en bon français n'a pas de sens pour un modèle bilingue.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.core.config import reglages
from app.core.erreurs import MoteurIndisponible
from app.domain import decoupage, typographie
from app.domain.langues import nom_langue
from app.infra.cache import CacheSegments
from app.services.traduction.base import (
    Capacite, Etat, MoteurTraduction, Progression, Registre, Requete, Resultat,
)

VERSION_PROMPT = 5   # incrémenter en cas de changement : invalide le cache

CONSIGNES = {
    Capacite.TRADUCTION: [
        "Tu traduis un document de {source} vers {cible}.",
        "",
        "RÈGLES",
        "1. Traduis l'intégralité du passage. Ne résume pas, n'ajoute rien, "
        "ne commente pas.",
        "2. Écris dans un {cible} naturel, tel qu'un traducteur professionnel "
        "l'écrirait. La syntaxe de la langue de départ ne doit pas transparaître.",
        "3. Les idiomes se rendent par leur équivalent, jamais mot à mot.",
        "4. Conserve la mise en forme : titres, listes, numérotation, "
        "paragraphes, gras et italiques s'ils sont marqués.",
        "5. Ne traduis pas : noms propres, marques, adresses, extraits de code, "
        "identifiants, unités de mesure normalisées.",
        "6. Les nombres, dates et devises sont convertis aux conventions de "
        "{cible} sans changer les valeurs.",
    ],
    Capacite.REPARATION: [
        "On te soumet un passage en {cible} produit par une traduction "
        "automatique, parfois transcrit depuis un enregistrement audio. Le "
        "résultat est grammaticalement possible mais peu intelligible : syntaxe "
        "étrangère, idiomes traduits mot à mot, homophones confondus.",
        "",
        "Ta tâche : réécrire ce passage en {cible} naturel, tel qu'un traducteur "
        "humain l'aurait rendu.",
        "",
        "RÈGLES",
        "1. Ne résume pas, n'ajoute rien. Chaque idée doit se retrouver.",
        "2. Restructure librement les phrases. Le calque doit disparaître : "
        "coupe les phrases trop longues, remplace les passifs par des tournures "
        "actives, rends les idiomes par leur équivalent.",
        "3. Quand un mot est manifestement une erreur de reconnaissance vocale, "
        "rétablis celui que le sens impose.",
        "4. Conserve les titres, les listes numérotées et les paragraphes.",
    ],
    Capacite.REVISION: [
        "Tu révises une traduction en {cible} déjà réalisée.",
        "",
        "RÈGLES",
        "1. Ne réécris que ce qui le mérite : maladresses, calques, "
        "incohérences terminologiques, erreurs de registre.",
        "2. Une phrase déjà bonne reste telle quelle.",
        "3. Ne résume pas, n'ajoute rien.",
        "4. Conserve la mise en forme.",
    ],
}

REGISTRES = {
    Registre.SOUTENU: "Registre soutenu, phrases construites, vocabulaire précis.",
    Registre.COURANT: "Registre courant, phrases directes, vocabulaire accessible.",
    Registre.TECHNIQUE: "Registre technique : terminologie exacte et constante, "
                        "phrases courtes, aucune fioriture.",
    Registre.COMMERCIAL: "Registre commercial : ton engageant, phrases rythmées, "
                         "sans emphase excessive.",
}


def construire_systeme(requete: Requete) -> str:
    lignes = ["Tu es traducteur professionnel.", ""]
    lignes += [
        l.format(source=nom_langue(requete.source), cible=nom_langue(requete.cible))
        for l in CONSIGNES[requete.capacite]
    ]
    lignes += [
        "",
        REGISTRES.get(requete.registre, REGISTRES[Registre.COURANT]),
        "",
        "Si un passage reste incompréhensible même en contexte, rends-le du "
        "mieux possible et signale-le en fin de réponse par une ligne "
        "commençant par [DOUTE].",
        "",
        f"SORTIE : uniquement le texte en {nom_langue(requete.cible)}. Aucune "
        "introduction, aucun commentaire, aucune balise de code.",
    ]

    g = requete.glossaire or {}
    if termes := g.get("terminologie"):
        lignes += ["", "TERMINOLOGIE À RESPECTER"]
        for t in termes:
            ligne = f"- {t['source']} → {t['rendu']}"
            if t.get("jamais"):
                ligne += f"  (jamais : {t['jamais']})"
            lignes.append(ligne)
    if items := g.get("ne_pas_traduire"):
        lignes += ["", "À LAISSER TEL QUEL"] + [f"- {m}" for m in items]
    if items := g.get("calques_a_bannir"):
        lignes += ["", "CALQUES À BANNIR"] + [f"- {c}" for c in items]
    if items := g.get("consignes_de_style"):
        lignes += ["", "STYLE"] + [f"- {c}" for c in items]

    return "\n".join(lignes)


def construire_message(segment: str, titre: str, contexte: str, cible: str) -> str:
    parties = [f"Section en cours : {titre or 'Document'}"]
    if contexte:
        parties += [
            "",
            f"Fin de ta production précédente en {nom_langue(cible)}, pour la "
            "continuité (ne la retraduis pas) :",
            "---", contexte[-600:], "---",
        ]
    parties += ["", "Passage à traiter :", "---", segment, "---"]
    return "\n".join(parties)


def nettoyer_reponse(brut: str) -> tuple[str, list[str]]:
    import re

    t = re.sub(r"^```[a-z]*\n?|```$", "", brut.strip(), flags=re.MULTILINE)
    doutes = re.findall(r"^\[DOUTE\].*$", t, flags=re.MULTILINE)
    t = re.sub(r"^\[DOUTE\].*$", "", t, flags=re.MULTILINE)
    return t.strip(), doutes


class MoteurLLM(MoteurTraduction):
    nom = "llm"
    libelle = "Modèle de langue local"
    capacites = frozenset({
        Capacite.TRADUCTION, Capacite.REPARATION, Capacite.REVISION,
        Capacite.GLOSSAIRE, Capacite.CONTEXTE,
    })
    debit_mots_seconde = 4.0

    def __init__(self, cache: CacheSegments | None = None):
        self.cache = cache or CacheSegments("llm")

    # -- choix du modèle --------------------------------------------------

    @staticmethod
    def modele_pour(capacite: Capacite) -> str:
        """Le modèle dépend de la tâche, pas seulement de la configuration.

        Traduire d'une langue à une autre et réécrire dans une seule langue
        sont deux compétences distinctes. Un modèle spécialisé traduction
        (HY-MT, Opus) est excellent sur la première et médiocre sur la
        seconde : il n'a jamais vu de consigne de réécriture monolingue.

        On route donc, avec repli sur le modèle principal si le second
        n'est pas configuré.
        """
        cfg = reglages()
        monolingue = {Capacite.REPARATION, Capacite.REVISION}
        if capacite in monolingue and cfg.llm_modele_reecriture:
            return cfg.llm_modele_reecriture
        return cfg.llm_modele

    # -- transport --------------------------------------------------------

    async def _appeler(
        self, systeme: str, message: str, essais: int = 3,
        modele: str | None = None,
    ) -> str:
        cfg = reglages()
        url = cfg.llm_url.rstrip("/")
        modele = modele or cfg.llm_modele
        messages = [
            {"role": "system", "content": systeme},
            {"role": "user", "content": message},
        ]

        if cfg.llm_api == "ollama":
            point = f"{url}/api/chat"
            charge = {
                "model": modele, "messages": messages, "stream": False,
                "options": {
                    "temperature": cfg.llm_temperature,
                    "num_ctx": cfg.llm_contexte,
                },
            }
        else:
            point = f"{url}/v1/chat/completions"
            charge = {
                "model": modele, "messages": messages,
                "temperature": cfg.llm_temperature,
            }

        derniere: Exception | None = None
        async with httpx.AsyncClient(timeout=cfg.llm_delai) as client:
            for essai in range(essais):
                try:
                    r = await client.post(point, json=charge)
                    r.raise_for_status()
                    donnees = r.json()
                    if cfg.llm_api == "ollama":
                        return donnees["message"]["content"].strip()
                    return donnees["choices"][0]["message"]["content"].strip()
                except Exception as e:                      # noqa: BLE001
                    derniere = e
                    if essai < essais - 1:
                        await asyncio.sleep(3 * (essai + 1))

        raise MoteurIndisponible(
            f"Modèle « {modele} » injoignable sur {point}", str(derniere)
        )

    # -- interface --------------------------------------------------------

    async def etat(self) -> Etat:
        cfg = reglages()
        url = cfg.llm_url.rstrip("/")
        point = f"{url}/api/tags" if cfg.llm_api == "ollama" else f"{url}/v1/models"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(point)
                r.raise_for_status()
                donnees = r.json()
        except Exception as e:                              # noqa: BLE001
            return Etat(
                False, f"serveur injoignable sur {url}", [],
                "ollama serve\n\n"
                f"Ou corrige ATELIER_LLM_URL dans .env (actuel : {url}).\n"
                f"Détail : {e}",
            )

        if cfg.llm_api == "ollama":
            noms = [m["name"] for m in donnees.get("models", [])]
        else:
            noms = [m["id"] for m in donnees.get("data", [])]

        def present(modele: str) -> bool:
            return modele in noms or any(n.startswith(modele) for n in noms)

        attendus = [cfg.llm_modele]
        if cfg.llm_modele_reecriture:
            attendus.append(cfg.llm_modele_reecriture)
        manquants = [m for m in attendus if not present(m)]

        if manquants:
            return Etat(
                False,
                f"modèle(s) absent(s) : {', '.join(manquants)}", noms,
                "\n".join(f"ollama pull {m}" for m in manquants)
                + "\n\nOu ajuste ATELIER_LLM_MODELE / "
                  "ATELIER_LLM_MODELE_REECRITURE dans .env.",
            )

        if cfg.llm_modele_reecriture:
            return Etat(
                True,
                f"{cfg.llm_modele} (traduction) + "
                f"{cfg.llm_modele_reecriture} (réécriture)",
                noms,
            )
        return Etat(True, f"{cfg.llm_modele} prêt", noms)

    async def traduire(
        self, requete: Requete, progression: Progression = None
    ) -> Resultat:
        plan = decoupage.construire_plan(requete.texte)
        systeme = construire_systeme(requete)
        modele = requete.modele or self.modele_pour(requete.capacite)
        # Le modèle fait partie de l'empreinte : changer de modèle invalide
        # naturellement le cache, sans purge manuelle.
        empreinte = self.cache.empreinte_contexte(
            VERSION_PROMPT, modele, requete.capacite,
            requete.source, requete.cible, requete.registre,
        )

        morceaux: list[str] = []
        doutes: list[str] = []
        contexte = ""
        total = len(plan.segments)
        section_courante = -1

        for i, segment in enumerate(plan.segments):
            if segment.section != section_courante:
                section_courante = segment.section
                morceaux.append(f"\n\n{segment.titre_section}\n")
                contexte = ""   # on repart à zéro à chaque section

            cle = self.cache.cle(empreinte, segment.texte)
            brut = self.cache.lire(cle)
            depuis_cache = brut is not None

            if brut is None:
                message = construire_message(
                    segment.texte, segment.titre_section, contexte, requete.cible
                )
                brut = await self._appeler(systeme, message, modele=modele)
                self.cache.ecrire(cle, brut)

            traduit, doutes_segment = nettoyer_reponse(brut)
            traduit = typographie.appliquer(traduit, requete.cible)

            morceaux.append(traduit)
            contexte = traduit
            doutes += [f"[{segment.titre_section}] {d}" for d in doutes_segment]

            if progression:
                await progression(
                    i + 1, total, "cache" if depuis_cache else "traduit"
                )

        return Resultat(
            texte="\n\n".join(m.strip() for m in morceaux if m.strip()),
            moteur=self.nom,
            doutes=doutes,
        )
