"""Contrôle de fidélité entre deux versions d'un texte.

Portage de `verifier_sens.py`. La passe de réécriture a un angle mort :
quand le modèle ne comprend pas un passage, il ne le signale pas, il
produit une phrase plausible. Ce module rend ces endroits visibles.

Quatre étiquettes, par gravité croissante :

    OMISSION     une idée présente avant a disparu
    CONTRESENS   l'idée est là des deux côtés, mais le sens a changé
    FLOU         passage incompréhensible dont la réécriture propose une
                 lecture incertaine
    AJOUT        une idée est apparue — le cas le plus grave, parce qu'il
                 signale une invention pure

Limite structurelle, à garder en tête : aucun modèle ne retrouve un sens
absent des deux versions comparées. Là où la traduction automatique a
détruit l'information, seul le texte d'origine permet de la rétablir. D'où
l'intérêt de comparer contre la source réelle plutôt que contre une version
déjà dégradée.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.core.config import reglages
from app.domain.langues import nom_langue
from app.infra.cache import CacheSegments
from app.services.traduction.base import Capacite, Progression
from app.services.traduction.llm import MoteurLLM

VERSION_PROMPT = 3

ETIQUETTES = ("OMISSION", "AJOUT", "CONTRESENS", "FLOU")
GRAVITE = {"AJOUT": 3, "CONTRESENS": 2, "OMISSION": 2, "FLOU": 1}


@dataclass(slots=True)
class Constat:
    etiquette: str
    explication: str
    avant: str
    apres: str
    paire: int
    propositions: list[str] = field(default_factory=list)

    @property
    def gravite(self) -> int:
        return GRAVITE.get(self.etiquette, 0)


@dataclass(slots=True)
class RapportSens:
    constats: list[Constat] = field(default_factory=list)
    paires_comparees: int = 0

    def par_etiquette(self) -> dict[str, int]:
        compte: dict[str, int] = {}
        for c in self.constats:
            compte[c.etiquette] = compte.get(c.etiquette, 0) + 1
        return compte


def segmenter(texte: str, taille: int = 2200) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", texte) if p.strip()]
    segments, courant = [], ""
    for para in paras:
        if courant and len(courant) + len(para) + 2 > taille:
            segments.append(courant)
            courant = para
        else:
            courant = f"{courant}\n\n{para}" if courant else para
    if courant:
        segments.append(courant)
    return segments


def apparier(avant: str, apres: str, taille: int = 2200) -> list[tuple[str, str]]:
    """Apparie les segments des deux versions.

    La réécriture change le nombre de paragraphes — elle coupe les phrases
    longues, fusionne les redondances. On apparie donc proportionnellement
    plutôt qu'un pour un, ce qui est approximatif mais suffisant : le modèle
    voit assez de contexte des deux côtés pour repérer une idée manquante.
    """
    a, b = segmenter(avant, taille), segmenter(apres, taille)
    if not a or not b:
        return []

    n = max(len(a), len(b))
    paires = []
    for i in range(n):
        ia = min(int(i * len(a) / n), len(a) - 1)
        ib = min(int(i * len(b) / n), len(b) - 1)
        paires.append((a[ia], b[ib]))
    return paires


def construire_systeme(source: str, cible: str, propositions: bool) -> str:
    lignes = [
        "Tu contrôles la fidélité d'une réécriture.",
        "",
        f"On te donne un passage AVANT en {nom_langue(source)} et le passage "
        f"APRÈS en {nom_langue(cible)}.",
        "",
        "Ta tâche : relever uniquement ce qui a changé de sens. Les "
        "reformulations, les changements de syntaxe et les coupes de phrases "
        "longues ne sont PAS des constats — c'est le travail attendu.",
        "",
        "ÉTIQUETTES",
        "OMISSION   — une idée du AVANT est absente du APRÈS",
        "AJOUT      — une idée du APRÈS est absente du AVANT",
        "CONTRESENS — l'idée est présente des deux côtés mais le sens diffère",
        "FLOU       — le AVANT est incompréhensible, le APRÈS propose une "
        "lecture qui pourrait être fausse",
        "",
        "SORTIE : un tableau JSON, rien d'autre. Aucune introduction, aucune "
        "balise de code.",
        "",
        "Chaque élément :",
        '  {"etiquette": "...", "explication": "...", '
        '"avant": "...", "apres": "..."',
    ]
    if propositions:
        lignes.append(
            '   , "propositions": ["lecture 1", "lecture 2"]  '
            "(pour FLOU uniquement)"
        )
    lignes += [
        "  }",
        "",
        "`avant` et `apres` citent le fragment concerné, pas tout le passage.",
        "Si rien n'a changé de sens, renvoie exactement : []",
    ]
    return "\n".join(lignes)


def extraire(reponse: str) -> list[dict]:
    """Extrait le JSON même si le modèle a ajouté du bavardage autour."""
    texte = re.sub(r"^```[a-z]*\n?|```$", "", reponse.strip(), flags=re.MULTILINE)
    try:
        donnees = json.loads(texte)
    except json.JSONDecodeError:
        debut, fin = texte.find("["), texte.rfind("]")
        if debut == -1 or fin <= debut:
            return []
        try:
            donnees = json.loads(texte[debut:fin + 1])
        except json.JSONDecodeError:
            return []
    return donnees if isinstance(donnees, list) else []


class VerificateurSens:
    def __init__(self, llm: MoteurLLM | None = None):
        self.llm = llm or MoteurLLM()
        self.cache = CacheSegments("verification")

    async def verifier(
        self,
        avant: str,
        apres: str,
        source: str = "fr",
        cible: str = "fr",
        propositions: bool = False,
        progression: Progression = None,
    ) -> RapportSens:
        paires = apparier(avant, apres)
        systeme = construire_systeme(source, cible, propositions)
        # La vérification produit du JSON structuré : c'est une tâche de
        # généraliste, jamais de modèle spécialisé traduction.
        modele = MoteurLLM.modele_pour(Capacite.REVISION)
        empreinte = self.cache.empreinte_contexte(
            VERSION_PROMPT, modele, source, cible, propositions
        )

        rapport = RapportSens(paires_comparees=len(paires))

        for i, (av, ap) in enumerate(paires):
            cle = self.cache.cle(empreinte, f"{av}\x00{ap}")
            brut = self.cache.lire(cle)
            if brut is None:
                message = (
                    f"AVANT\n---\n{av}\n---\n\nAPRÈS\n---\n{ap}\n---"
                )
                brut = await self.llm._appeler(systeme, message, modele=modele)
                self.cache.ecrire(cle, brut)

            for element in extraire(brut):
                etiquette = str(element.get("etiquette", "")).upper()
                if etiquette not in ETIQUETTES:
                    continue
                rapport.constats.append(Constat(
                    etiquette=etiquette,
                    explication=str(element.get("explication", "")),
                    avant=str(element.get("avant", "")),
                    apres=str(element.get("apres", "")),
                    paire=i,
                    propositions=[
                        str(p) for p in element.get("propositions", [])
                    ],
                ))

            if progression:
                await progression(i + 1, len(paires), f"paire {i + 1}")

        # Les ajouts d'abord : ce sont les inventions pures.
        rapport.constats.sort(key=lambda c: (-c.gravite, c.paire))
        return rapport


def en_markdown(rapport: RapportSens) -> str:
    """Rapport lisible, les deux versions repliées sous chaque constat,
    pour arbitrer sans ouvrir les fichiers d'origine."""
    lignes = [
        "# Contrôle de fidélité",
        "",
        f"{rapport.paires_comparees} paire(s) comparée(s), "
        f"{len(rapport.constats)} constat(s).",
        "",
    ]
    compte = rapport.par_etiquette()
    if compte:
        lignes += ["| Étiquette | Nombre |", "|---|---|"]
        lignes += [f"| {e} | {n} |" for e, n in sorted(compte.items())]
        lignes.append("")

    if not rapport.constats:
        lignes.append("Aucun changement de sens détecté.")
        return "\n".join(lignes)

    for i, c in enumerate(rapport.constats, 1):
        lignes += [
            f"## {i}. {c.etiquette}",
            "",
            c.explication,
            "",
            "<details><summary>Avant</summary>",
            "", f"> {c.avant}", "",
            "</details>",
            "",
            "<details><summary>Après</summary>",
            "", f"> {c.apres}", "",
            "</details>",
            "",
        ]
        if c.propositions:
            lignes.append("**Lectures possibles :**")
            lignes += [f"{j}. {p}" for j, p in enumerate(c.propositions, 1)]
            lignes.append("")

    return "\n".join(lignes)
