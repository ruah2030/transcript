"""Moteur hybride : NMT partout, LLM là où c'est nécessaire.

Le raisonnement. Sur un CPU sans GPU, un LLM traite environ 4 mots/seconde
et un NMT environ 200. Pour 80 000 mots, l'écart est de 6 heures contre
7 minutes. Mais la sortie NMT est phrase par phrase : pronoms flottants,
terminologie qui dérive, idiomes rendus mot à mot.

L'observation utile est que ces défauts ne sont pas répartis uniformément.
Ils se concentrent sur une minorité de segments, et ces segments sont
repérables mécaniquement, sans relire le texte.

D'où la stratégie : NMT sur l'intégralité, détection des segments douteux,
puis LLM sur ceux-là seulement. Avec 10 % de segments repris, on paie 10 %
du coût du LLM.

Les cinq signaux de suspicion sont dans `SIGNAUX`. Chacun rend un score
entre 0 et 1 ; leur somme pondérée est comparée au seuil.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.erreurs import CapaciteAbsente
from app.domain import decoupage
from app.services.traduction.base import (
    Capacite, Etat, MoteurTraduction, Progression, Requete, Resultat,
)
from app.services.traduction.llm import MoteurLLM
from app.services.traduction.nmt import MoteurNMT


@dataclass(slots=True)
class Verdict:
    indice: int
    score: float
    motifs: list[str]

    @property
    def suspect(self) -> bool:
        return self.score > 0


# --------------------------------------------------------------- signaux

def _ratio_longueur(source: str, sortie: str, **_) -> float:
    """Une traduction qui perd ou double le volume a mangé ou inventé.

    En→fr le texte gonfle de 15 à 20 %. On tolère 0,8 à 1,6.
    """
    if not source.strip():
        return 0.0
    ratio = len(sortie) / len(source)
    if ratio < 0.8:
        return min(1.0, (0.8 - ratio) * 3)
    if ratio > 1.6:
        return min(1.0, (ratio - 1.6) * 2)
    return 0.0


def _repetitions(sortie: str, **_) -> float:
    """Les modèles NMT bouclent quand ils décrochent : même n-gramme répété."""
    mots = sortie.lower().split()
    if len(mots) < 12:
        return 0.0
    quadrigrammes = [" ".join(mots[i:i + 4]) for i in range(len(mots) - 3)]
    uniques = len(set(quadrigrammes))
    taux = 1 - uniques / len(quadrigrammes)
    return min(1.0, taux * 4) if taux > 0.12 else 0.0


def _residus_source(source: str, sortie: str, langue_source: str = "en", **_) -> float:
    """Des mots de la langue de départ restés tels quels dans la sortie."""
    if langue_source != "en":
        return 0.0
    temoins = {
        "the", "and", "with", "that", "which", "would", "should", "because",
        "however", "therefore", "through", "about", "their", "these", "those",
    }
    mots = set(re.findall(r"\b[a-z]{3,}\b", sortie.lower()))
    trouves = mots & temoins
    return min(1.0, len(trouves) / 3) if trouves else 0.0


def _phrases_longues(sortie: str, **_) -> float:
    """Une phrase de plus de 350 caractères est presque toujours un calque
    non découpé — le NMT ne restructure jamais."""
    phrases = re.split(r"(?<=[.!?…])\s+", sortie)
    longues = [p for p in phrases if len(p) > 350]
    if not phrases:
        return 0.0
    return min(1.0, len(longues) / max(1, len(phrases)) * 5)


def _glossaire_ignore(source: str, sortie: str, glossaire: dict | None = None, **_) -> float:
    """Un terme imposé présent à la source, absent de la sortie.

    C'est le signal le plus précieux : le NMT ne connaît pas le glossaire,
    donc c'est exactement là qu'il faut le LLM.
    """
    if not glossaire:
        return 0.0
    termes = glossaire.get("terminologie", [])
    if not termes:
        return 0.0

    manques = 0
    concernes = 0
    bas_source, bas_sortie = source.lower(), sortie.lower()

    for terme in termes:
        motif = terme.get("source", "").lower()
        if not motif or motif not in bas_source:
            continue
        concernes += 1
        rendus = [
            r.strip().lower()
            for r in re.split(r"[,/]", terme.get("rendu", ""))
            if r.strip()
        ]
        rendus = [re.sub(r"\s*\([^)]*\)", "", r).strip() for r in rendus]
        if rendus and not any(r and r in bas_sortie for r in rendus):
            manques += 1

    return manques / concernes if concernes else 0.0


SIGNAUX = (
    ("ratio de longueur anormal", _ratio_longueur, 1.0),
    ("répétitions en boucle", _repetitions, 1.2),
    ("mots non traduits", _residus_source, 1.5),
    ("phrases trop longues", _phrases_longues, 0.6),
    ("terminologie ignorée", _glossaire_ignore, 1.4),
)


def evaluer(
    indice: int, source: str, sortie: str, langue_source: str, glossaire: dict | None,
    seuil: float,
) -> Verdict:
    score, motifs = 0.0, []
    for nom, fonction, poids in SIGNAUX:
        valeur = fonction(
            source=source, sortie=sortie,
            langue_source=langue_source, glossaire=glossaire,
        )
        if valeur > 0:
            score += valeur * poids
            motifs.append(f"{nom} ({valeur:.2f})")
    return Verdict(indice, score if score >= seuil else 0.0, motifs)


# ---------------------------------------------------------------- moteur

class MoteurHybride(MoteurTraduction):
    nom = "hybride"
    libelle = "Hybride NMT + LLM"
    capacites = frozenset({
        Capacite.TRADUCTION, Capacite.GLOSSAIRE, Capacite.CONTEXTE,
    })
    debit_mots_seconde = 30.0

    def __init__(
        self,
        nmt: MoteurNMT,
        llm: MoteurLLM,
        seuil: float = 1.0,
        part_maximale: float = 0.30,
    ):
        self.nmt = nmt
        self.llm = llm
        self.seuil = seuil
        #: Garde-fou : jamais plus de cette part de segments repris par le LLM.
        #: Au-delà, autant lancer le LLM sur tout et l'assumer.
        self.part_maximale = part_maximale

    async def etat(self) -> Etat:
        etat_nmt, etat_llm = await self.nmt.etat(), await self.llm.etat()
        if not etat_nmt.disponible:
            return Etat(
                False, f"NMT indisponible — {etat_nmt.detail}", [],
                etat_nmt.remede,
            )
        if not etat_llm.disponible:
            return Etat(
                False,
                f"NMT prêt mais LLM indisponible — {etat_llm.detail}",
                etat_nmt.paires, etat_llm.remede,
            )
        return Etat(
            True, f"{etat_nmt.detail}, reprise par {etat_llm.detail}",
            etat_nmt.paires,
        )

    async def traduire(
        self, requete: Requete, progression: Progression = None
    ) -> Resultat:
        if requete.capacite is not Capacite.TRADUCTION:
            raise CapaciteAbsente(
                "Le mode hybride ne couvre que la traduction.",
                "Réparation et révision sont monolingues : le NMT n'y apporte "
                "rien. Utilise le moteur « llm » directement.",
            )

        plan = decoupage.construire_plan(requete.texte)
        total = len(plan.segments)
        if not total:
            return Resultat(texte="", moteur=self.nom)

        # --- passe 1 : NMT sur tout
        sorties: list[str] = []
        for i, segment in enumerate(plan.segments):
            resultat = await self.nmt.traduire(
                Requete(
                    texte=segment.texte, source=requete.source,
                    cible=requete.cible, capacite=Capacite.TRADUCTION,
                )
            )
            sorties.append(resultat.texte)
            if progression:
                await progression(i + 1, total * 2, "NMT")

        # --- détection
        verdicts = [
            evaluer(
                i, plan.segments[i].texte, sorties[i],
                requete.source, requete.glossaire, self.seuil,
            )
            for i in range(total)
        ]
        suspects = sorted(
            (v for v in verdicts if v.suspect), key=lambda v: -v.score
        )
        plafond = max(1, int(total * self.part_maximale))
        retenus = suspects[:plafond]

        # --- passe 2 : LLM sur les seuls segments retenus
        doutes: list[str] = []
        contexte = ""
        for n, verdict in enumerate(retenus):
            segment = plan.segments[verdict.indice]
            resultat = await self.llm.traduire(
                Requete(
                    texte=segment.texte, source=requete.source,
                    cible=requete.cible, capacite=Capacite.TRADUCTION,
                    registre=requete.registre, glossaire=requete.glossaire,
                    contexte=contexte, titre_section=segment.titre_section,
                    modele=requete.modele,
                )
            )
            sorties[verdict.indice] = resultat.texte
            contexte = resultat.texte
            doutes += resultat.doutes
            doutes.append(
                f"[repris] segment {verdict.indice} — {', '.join(verdict.motifs)}"
            )
            if progression:
                await progression(total + n + 1, total * 2, "LLM (reprise)")

        if progression:
            await progression(total * 2, total * 2, "terminé")

        # --- réassemblage avec les titres de section
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
            confiance=1 - len(retenus) / total,
        )
