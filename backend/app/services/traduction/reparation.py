"""Réparation ciblée : ne réécrire que les segments réellement dégradés.

Le mode `reparation` classique envoie tout le texte au modèle. Sur 80 000
mots et un CPU sans GPU, c'est douze heures. Or une transcription dégradée
n'est pas uniformément mauvaise : les calques se concentrent sur une
minorité de passages.

Ce moteur note chaque segment sans appeler aucun modèle, puis n'envoie au
LLM que ceux qui dépassent le seuil. Les autres passent tels quels.

La différence avec `hybride.py` est la nature des signaux. Là-bas on
comparait une source et une sortie — ratio de longueur, mots non traduits.
Ici il n'y a qu'un texte, en français, qu'il faut juger sur sa seule
forme. Les signaux sont donc morphosyntaxiques et lexicaux.

Deux d'entre eux lisent directement tes fichiers existants : la section
`signalements` de dictionnaire-calques.json et la liste `calques_a_bannir`
du glossaire. Enrichir ces fichiers améliore la détection sans toucher au
code — c'est le même geste que celui que tu fais déjà en relecture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import reglages
from app.core.erreurs import CapaciteAbsente
from app.domain import decoupage
from app.services.traduction.base import (
    Capacite, Etat, MoteurTraduction, Progression, Requete, Resultat,
)
from app.services.traduction.llm import MoteurLLM


@dataclass(slots=True)
class Note:
    indice: int
    score: float
    motifs: list[str] = field(default_factory=list)


# --------------------------------------------------------------- signaux

# Une phrase française de plus de 250 caractères sans ponctuation médiane
# est presque toujours une phrase anglaise non redécoupée.
def _phrases_interminables(texte: str, **_) -> float:
    phrases = [p for p in re.split(r"(?<=[.!?…])\s+", texte) if p.strip()]
    if not phrases:
        return 0.0
    longues = [p for p in phrases if len(p) > 250 and p.count(",") < 3]
    return min(1.0, len(longues) / len(phrases) * 4)


# Le passif est correct en français mais rare. Une densité élevée trahit
# presque toujours un décalque de l'anglais.
PASSIF = re.compile(
    r"\b(?:est|sont|était|étaient|sera|seront|a été|ont été|avait été)\s+"
    r"\w+(?:é|és|ée|ées|i|is|ie|ies|u|us|ue|ues)\b",
    re.IGNORECASE,
)


def _densite_passive(texte: str, **_) -> float:
    phrases = [p for p in re.split(r"(?<=[.!?…])\s+", texte) if p.strip()]
    if len(phrases) < 3:
        return 0.0
    taux = len(PASSIF.findall(texte)) / len(phrases)
    return min(1.0, (taux - 0.25) * 2.5) if taux > 0.25 else 0.0


# Connecteurs lourds répétés : signature de la traduction automatique,
# qui rend « therefore » et « essentially » toujours de la même façon.
CONNECTEURS = (
    "par conséquent", "essentiellement", "en outre", "de plus", "ainsi",
    "cependant", "néanmoins", "toutefois", "en effet", "de ce fait",
)


def _connecteurs_repetes(texte: str, **_) -> float:
    bas = texte.lower()
    phrases = max(1, len([p for p in re.split(r"(?<=[.!?…])\s+", texte) if p.strip()]))
    total = sum(bas.count(c) for c in CONNECTEURS)
    taux = total / phrases
    return min(1.0, (taux - 0.3) * 2) if taux > 0.3 else 0.0


# Résidus anglais restés dans le texte.
TEMOINS_ANGLAIS = {
    "the", "and", "with", "that", "which", "would", "should", "because",
    "however", "therefore", "through", "about", "their", "these", "those",
    "purpose", "leadership", "however", "indeed",
}


def _residus_anglais(texte: str, **_) -> float:
    mots = set(re.findall(r"\b[a-z]{3,}\b", texte.lower()))
    trouves = mots & TEMOINS_ANGLAIS
    return min(1.0, len(trouves) / 2) if trouves else 0.0


# Pronoms accumulés sans antécédent clair : le NMT perd le fil référentiel.
def _pronoms_flottants(texte: str, **_) -> float:
    mots = texte.lower().split()
    if len(mots) < 40:
        return 0.0
    pronoms = sum(
        1 for m in mots
        if m.strip(".,;:!?") in {"il", "elle", "ils", "elles", "cela", "ceci", "ce"}
    )
    taux = pronoms / len(mots)
    return min(1.0, (taux - 0.06) * 12) if taux > 0.06 else 0.0


def _charger_motifs_calques() -> list[tuple[str, re.Pattern]]:
    """Lit la section `signalements` de dictionnaire-calques.json.

    Ces motifs ne sont jamais corrigés automatiquement parce que le bon
    choix dépend de la phrase — c'est exactement ce qui en fait un bon
    signal : leur présence indique un passage à faire relire par un modèle
    qui, lui, voit le contexte.
    """
    import json

    chemin: Path = reglages().dossier_ressources / "dictionnaire-calques.json"
    if not chemin.is_file():
        return []
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    motifs = []
    for regle in donnees.get("signalements", []):
        brut = regle["motif"] if regle.get("regex", True) else re.escape(regle["motif"])
        try:
            motifs.append((
                regle.get("categorie", "calque"),
                re.compile(brut, 0 if regle.get("casse") else re.IGNORECASE),
            ))
        except re.error:
            continue
    return motifs


class MoteurReparationCiblee(MoteurTraduction):
    nom = "reparation_ciblee"
    libelle = "Réparation ciblée (LLM sur les seuls passages dégradés)"
    capacites = frozenset({
        Capacite.REPARATION, Capacite.REVISION,
        Capacite.GLOSSAIRE, Capacite.CONTEXTE,
    })
    debit_mots_seconde = 25.0

    def __init__(
        self,
        llm: MoteurLLM | None = None,
        seuil: float = 0.9,
        part_maximale: float | None = None,
        taille_segment: int = 1200,
    ):
        self.llm = llm or MoteurLLM()
        self.seuil = seuil
        #: Plafond de segments réécrits. Calibré sur la taille du modèle de
        #: réécriture, parce que le coût par segment varie d'un facteur six
        #: entre un 4B et un 12B sur CPU. Un plafond fixe ferait passer le
        #: même document de 20 minutes à deux heures selon le modèle, sans
        #: que rien ne le signale.
        self.part_maximale = (
            part_maximale if part_maximale is not None else self._plafond_par_defaut()
        )
        #: Segments plus courts qu'en traduction, et c'est délibéré. La
        #: granularité de découpe borne la précision du ciblage : dans un
        #: bloc de 3500 caractères, bon et mauvais français cohabitent, et
        #: on réécrit du texte correct pour rien. À 1200, un paragraphe
        #: dégradé est isolé de ses voisins sains.
        self.taille_segment = taille_segment
        self._motifs_calques: list[tuple[str, re.Pattern]] | None = None

    @staticmethod
    def _plafond_par_defaut() -> float:
        import re as _re

        modele = MoteurLLM.modele_pour(Capacite.REPARATION).lower()
        milliards = _re.search(r"(\d{1,3})b\b", modele)
        if not milliards:
            return 0.25
        taille = int(milliards.group(1))
        if taille >= 12:
            return 0.15
        if taille >= 7:
            return 0.20
        return 0.30

    @property
    def motifs_calques(self):
        if self._motifs_calques is None:
            self._motifs_calques = _charger_motifs_calques()
        return self._motifs_calques

    def _signaux_glossaire(self, texte: str, glossaire: dict | None) -> float:
        """Tournures que le glossaire demande d'éviter dans la langue
        d'arrivée. La partie avant la flèche est le calque à repérer."""
        if not glossaire:
            return 0.0
        bannis = glossaire.get("calques_a_bannir", [])
        if not bannis:
            return 0.0
        bas = texte.lower()
        trouves = sum(
            1 for entree in bannis
            if (calque := entree.split("→")[0].strip().lower()) and calque in bas
        )
        return min(1.0, trouves / 2)

    def noter(self, indice: int, texte: str, glossaire: dict | None) -> Note:
        note = Note(indice=indice, score=0.0)

        mesures = (
            ("phrases interminables", _phrases_interminables(texte), 1.2),
            ("densité passive", _densite_passive(texte), 1.0),
            ("connecteurs répétés", _connecteurs_repetes(texte), 0.8),
            ("résidus anglais", _residus_anglais(texte), 1.6),
            ("pronoms flottants", _pronoms_flottants(texte), 0.9),
            ("calques du glossaire", self._signaux_glossaire(texte, glossaire), 1.4),
        )
        for libelle, valeur, poids in mesures:
            if valeur > 0:
                note.score += valeur * poids
                note.motifs.append(f"{libelle} ({valeur:.2f})")

        # Signalements du dictionnaire de calques.
        touches = [
            categorie for categorie, motif in self.motifs_calques
            if motif.search(texte)
        ]
        if touches:
            valeur = min(1.0, len(touches) / 2)
            note.score += valeur * 1.5
            note.motifs.append(f"signalements dictionnaire ({len(touches)})")

        return note

    async def etat(self) -> Etat:
        etat_llm = await self.llm.etat()
        if not etat_llm.disponible:
            return Etat(
                False, f"LLM indisponible — {etat_llm.detail}", [],
                etat_llm.remede,
            )
        return Etat(True, f"détection locale + reprise par {etat_llm.detail}")

    async def traduire(
        self, requete: Requete, progression: Progression = None
    ) -> Resultat:
        if requete.capacite not in self.capacites:
            raise CapaciteAbsente(
                f"{self.libelle} ne fait que réparation et révision.",
                "Pour traduire d'une langue vers une autre, utilise « hybride ».",
            )

        plan = decoupage.construire_plan(requete.texte, self.taille_segment)
        total = len(plan.segments)
        if not total:
            return Resultat(texte="", moteur=self.nom)

        # --- notation, sans aucun appel de modèle
        notes = [
            self.noter(i, s.texte, requete.glossaire)
            for i, s in enumerate(plan.segments)
        ]
        suspects = sorted(
            (n for n in notes if n.score >= self.seuil), key=lambda n: -n.score
        )
        plafond = max(1, int(total * self.part_maximale))
        retenus = suspects[:plafond]
        a_reprendre = {n.indice for n in retenus}

        sorties = [s.texte for s in plan.segments]
        doutes: list[str] = []
        contexte = ""

        # --- reprise LLM sur les seuls segments retenus
        for n, note in enumerate(retenus):
            segment = plan.segments[note.indice]
            resultat = await self.llm.traduire(
                Requete(
                    texte=segment.texte,
                    source=requete.source, cible=requete.cible,
                    capacite=requete.capacite, registre=requete.registre,
                    glossaire=requete.glossaire, contexte=contexte,
                    titre_section=segment.titre_section, modele=requete.modele,
                )
            )
            sorties[note.indice] = resultat.texte
            contexte = resultat.texte
            doutes += resultat.doutes
            doutes.append(
                f"[réécrit] segment {note.indice} — {', '.join(note.motifs)}"
            )
            if progression:
                await progression(n + 1, len(retenus), "réécriture")

        # Les segments laissés tels quels au-dessus du seuil : le plafond
        # les a écartés. On le signale pour qu'ils soient relus à la main.
        for note in suspects[plafond:]:
            doutes.append(
                f"[non traité — plafond atteint] segment {note.indice} "
                f"(score {note.score:.2f})"
            )

        morceaux: list[str] = []
        section_courante = -1
        for segment, sortie in zip(plan.segments, sorties):
            if segment.section != section_courante:
                section_courante = segment.section
                morceaux.append(f"\n\n{segment.titre_section}\n")
            morceaux.append(sortie)

        return Resultat(
            texte="\n\n".join(m.strip() for m in morceaux if m.strip()),
            moteur=self.nom,
            doutes=doutes,
            confiance=1 - len(a_reprendre) / total,
        )

    def diagnostiquer(self, texte: str, glossaire: dict | None = None) -> dict:
        """Notation seule, sans réécriture. Sert à régler le seuil avant de
        lancer un traitement long : tu vois combien de segments seraient
        repris, et pourquoi."""
        plan = decoupage.construire_plan(texte, self.taille_segment)
        notes = [
            self.noter(i, s.texte, glossaire) for i, s in enumerate(plan.segments)
        ]
        suspects = [n for n in notes if n.score >= self.seuil]
        plafond = max(1, int(len(plan.segments) * self.part_maximale))
        mots_repris = sum(
            len(plan.segments[n.indice].texte.split())
            for n in sorted(suspects, key=lambda n: -n.score)[:plafond]
        )
        return {
            "segments": len(plan.segments),
            "au_dessus_du_seuil": len(suspects),
            "seront_repris": min(len(suspects), plafond),
            "plafond": plafond,
            "mots_a_reecrire": mots_repris,
            "part": round(min(len(suspects), plafond) / max(1, len(plan.segments)), 3),
            "details": [
                {"segment": n.indice, "score": round(n.score, 2), "motifs": n.motifs}
                for n in sorted(suspects, key=lambda n: -n.score)[:25]
            ],
        }
