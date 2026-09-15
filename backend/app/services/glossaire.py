"""Chargement et sauvegarde du glossaire injecté dans les requêtes LLM.

Le glossaire est le fichier qui s'enrichit au fil de la relecture : chaque
incohérence repérée devient une ligne, et les sections suivantes en
profitent. C'est pour ça qu'il est modifiable depuis l'interface.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import reglages
from app.core.erreurs import DocumentInvalide

SECTIONS = ("terminologie", "ne_pas_traduire", "calques_a_bannir",
            "consignes_de_style")


def chemin_glossaire(nom: str = "glossaire.json") -> Path:
    if "/" in nom or "\\" in nom or nom.startswith("."):
        raise DocumentInvalide(f"Nom de glossaire invalide : {nom}")
    return reglages().dossier_ressources / nom


def charger(nom: str = "glossaire.json") -> dict:
    chemin = chemin_glossaire(nom)
    if not chemin.is_file():
        return {s: [] for s in SECTIONS}
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    for section in SECTIONS:
        donnees.setdefault(section, [])
    return donnees


def enregistrer(donnees: dict, nom: str = "glossaire.json") -> dict:
    chemin = chemin_glossaire(nom)
    existant = charger(nom) if chemin.is_file() else {}
    fusion = {**existant, **{s: donnees.get(s, existant.get(s, [])) for s in SECTIONS}}
    fusion["version"] = existant.get("version", 1) + 1
    chemin.write_text(
        json.dumps(fusion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return fusion


def lister() -> list[str]:
    return sorted(p.name for p in reglages().dossier_ressources.glob("glossaire*.json"))
