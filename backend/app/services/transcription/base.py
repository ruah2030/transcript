"""Contrat commun aux sources de texte parlé.

Deux façons d'obtenir le texte d'une vidéo, très inégales :

    sous-titres   déjà écrits, récupérés en quelques secondes. Qu'ils soient
                  humains ou générés automatiquement, c'est toujours plus
                  rapide que de retranscrire — et souvent meilleur, car les
                  sous-titres humains portent la ponctuation.

    transcription Whisper sur la piste audio. Des minutes à des heures selon
                  la durée et le modèle.

On tente donc toujours les sous-titres en premier. C'est aussi ce qui
explique la passe de nettoyage : les sous-titres automatiques arrivent
segmentés par bloc temporel, pas en paragraphes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Origine(StrEnum):
    SOUS_TITRES_HUMAINS = "sous_titres_humains"
    SOUS_TITRES_AUTO = "sous_titres_auto"
    TRANSCRIPTION = "transcription"
    FICHIER = "fichier"


@dataclass(slots=True)
class PisteSousTitres:
    langue: str
    automatique: bool
    nom: str = ""


@dataclass(slots=True)
class Media:
    """Ce qu'on sait d'une source avant de la traiter."""

    titre: str
    duree_secondes: float
    url: str = ""
    chaine: str = ""
    pistes: list[PisteSousTitres] = field(default_factory=list)

    def piste_pour(self, langue: str) -> PisteSousTitres | None:
        """Préfère une piste humaine à une piste automatique."""
        candidates = [p for p in self.pistes if p.langue.split("-")[0] == langue]
        if not candidates:
            return None
        return sorted(candidates, key=lambda p: p.automatique)[0]


@dataclass(slots=True)
class Transcription:
    texte: str
    origine: Origine
    langue: str
    duree_secondes: float = 0.0
    titre: str = ""
    #: Renseigné seulement si l'appelant a demandé les horodatages.
    segments: list[dict] = field(default_factory=list)


#: Vitesse de faster-whisper sur CPU en int8, exprimée en multiples du temps
#: réel : 6.0 signifie qu'une heure d'audio se traite en dix minutes. Ce sont
#: des ordres de grandeur mesurés sur un CPU de bureau récent, pas une
#: promesse — le nombre de cœurs change tout.
VITESSE_MODELES = {
    "tiny": 20.0,
    "base": 12.0,
    "small": 6.0,
    "distil-large-v3": 4.0,
    "medium": 2.5,
    "large-v3": 1.0,
}

#: Empreinte mémoire approximative en int8, pour choisir sans se tromper.
POIDS_MODELES = {
    "tiny": "75 Mo",
    "base": "145 Mo",
    "small": "484 Mo",
    "distil-large-v3": "1,5 Go",
    "medium": "1,5 Go",
    "large-v3": "3,1 Go",
}
