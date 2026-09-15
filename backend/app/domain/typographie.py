"""Conventions typographiques par langue d'arrivée.

Appliqué en sortie de traduction, quel que soit le moteur : un modèle NMT
ne produit pas d'espaces fines insécables, un LLM les produit de façon
inconstante. Cette passe rend le résultat homogène.
"""

import re

FINE = "\u202f"   # espace fine insécable


def _francais(t: str) -> str:
    t = re.sub(r"(\w)'(\w)", r"\1’\2", t)
    t = re.sub(r'"([^"]*)"', f"«{FINE}\\1{FINE}»", t)
    return re.sub(r"\s*([;:!?%])", FINE + r"\1", t)


def _anglosaxon(t: str) -> str:
    t = re.sub(r"(\w)'(\w)", r"\1’\2", t)
    t = re.sub(r'"([^"]*)"', "“\\1”", t)
    return re.sub(r"\s+([;:!?%,.])", r"\1", t)


def _allemand(t: str) -> str:
    t = re.sub(r'"([^"]*)"', "„\\1“", t)
    return re.sub(r"\s+([;:!?%,.])", r"\1", t)


def _espagnol(t: str) -> str:
    return re.sub(r"\s+([;:!?%,.])", r"\1", t)


REGLES = {
    "fr": _francais,
    "en": _anglosaxon, "nl": _anglosaxon, "pt": _anglosaxon, "it": _anglosaxon,
    "de": _allemand,
    "es": _espagnol,
}


def appliquer(texte: str, langue: str) -> str:
    texte = re.sub(r"[ \t\u00a0]+", " ", texte)
    regle = REGLES.get(langue.lower())
    if regle:
        texte = regle(texte)
    texte = re.sub(r"\.{3,}", "…", texte)
    texte = re.sub(r"[ \t]+\n", "\n", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()
