"""Cache disque par segment.

Reprend le principe de `traduire.py` : chaque segment traité est écrit sur
disque sous une clé qui dépend du texte ET du contexte de traitement
(version des prompts, modèle, mode, paire de langues, registre). Changer
l'un de ces paramètres invalide naturellement le cache, sans purge.

C'est ce qui rend un travail de plusieurs heures interruptible : après une
coupure, on relance et seuls les segments manquants sont recalculés.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import reglages


class CacheSegments:
    def __init__(self, espace: str):
        self.racine: Path = reglages().dossier_cache / espace
        self.racine.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def empreinte_contexte(*elements) -> str:
        """Condense les paramètres de traitement en une empreinte courte."""
        brut = "|".join(str(e) for e in elements)
        return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:8]

    @staticmethod
    def cle(empreinte: str, contenu: str) -> str:
        digest = hashlib.sha1(contenu.encode("utf-8")).hexdigest()[:16]
        return f"{empreinte}-{digest}"

    def _chemin(self, cle: str) -> Path:
        # Un niveau de sous-dossiers : évite des dizaines de milliers
        # d'entrées à plat, que certains systèmes de fichiers digèrent mal.
        return self.racine / cle[:2] / f"{cle}.txt"

    def lire(self, cle: str) -> str | None:
        chemin = self._chemin(cle)
        if chemin.is_file():
            return chemin.read_text(encoding="utf-8")
        return None

    def ecrire(self, cle: str, contenu: str) -> None:
        chemin = self._chemin(cle)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")

    def vider(self) -> int:
        compte = 0
        for fichier in self.racine.rglob("*.txt"):
            fichier.unlink()
            compte += 1
        return compte

    def taille(self) -> tuple[int, int]:
        """(nombre d'entrées, octets)."""
        fichiers = list(self.racine.rglob("*.txt"))
        return len(fichiers), sum(f.stat().st_size for f in fichiers)
