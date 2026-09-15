"""Contrat commun à tous les moteurs de traduction.

Le point central de cette architecture est la notion de CAPACITÉ.

Un moteur NMT (Opus-MT, Argos) est un modèle seq2seq bilingue : il prend
une langue en entrée, il en produit une autre. Il ne sait pas réécrire un
mauvais français en bon français — cette tâche est monolingue et n'a pas
de représentation dans son espace d'entraînement.

Un LLM sait faire les deux, mais paie ce choix par un débit cent fois
moindre.

Plutôt que de laisser l'appelant deviner, chaque moteur déclare ce qu'il
sait faire. Le registre refuse une combinaison impossible avant de lancer
un travail de plusieurs heures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Awaitable, Callable


class Capacite(StrEnum):
    TRADUCTION = "traduction"    # langue A -> langue B
    REPARATION = "reparation"    # réécrire une mauvaise traduction, monolingue
    REVISION = "revision"        # relire une traduction humaine, monolingue
    GLOSSAIRE = "glossaire"      # sait respecter une terminologie imposée
    CONTEXTE = "contexte"        # tient compte du segment précédent


class Registre(StrEnum):
    SOUTENU = "soutenu"
    COURANT = "courant"
    TECHNIQUE = "technique"
    COMMERCIAL = "commercial"


@dataclass(slots=True)
class Requete:
    """Ce qu'on demande à un moteur."""

    texte: str
    source: str = "en"
    cible: str = "fr"
    capacite: Capacite = Capacite.TRADUCTION
    registre: Registre = Registre.COURANT
    glossaire: dict | None = None
    contexte: str = ""            # fin de la production précédente
    titre_section: str = ""
    #: Surcharge ponctuelle du modèle, pour comparer deux modèles sans
    #: toucher à la configuration ni redémarrer le service. Ignoré par les
    #: moteurs NMT, qui n'ont pas de modèle interchangeable.
    modele: str | None = None


@dataclass(slots=True)
class Resultat:
    """Ce qu'un moteur renvoie."""

    texte: str
    moteur: str
    doutes: list[str] = field(default_factory=list)
    confiance: float | None = None   # None si le moteur n'en produit pas
    depuis_cache: bool = False


# Rappel de progression : (faits, total, étiquette) -> None
Progression = Callable[[int, int, str], Awaitable[None]] | None


@dataclass(slots=True)
class Etat:
    """Diagnostic d'un moteur, pour l'écran de configuration.

    `remede` porte la commande exacte à lancer quand le moteur est
    indisponible. Un bouton grisé sans marche à suivre est une impasse :
    l'utilisateur voit que ça ne marche pas, sans savoir quoi faire.
    """

    disponible: bool
    detail: str
    paires: list[str] = field(default_factory=list)
    remede: str | None = None


class MoteurTraduction(ABC):
    """Interface que tout moteur doit remplir."""

    nom: str
    libelle: str
    capacites: frozenset[Capacite]
    #: Vitesse indicative en mots/seconde sur CPU, pour estimer une durée.
    debit_mots_seconde: float

    @abstractmethod
    async def etat(self) -> Etat:
        """Le moteur est-il utilisable maintenant ? Sans effet de bord."""

    @abstractmethod
    async def traduire(
        self, requete: Requete, progression: Progression = None
    ) -> Resultat:
        """Traite la requête. Peut être long : signale l'avancement."""

    def sait_faire(self, capacite: Capacite) -> bool:
        return capacite in self.capacites

    def duree_estimee(self, mots: int) -> float:
        """Secondes estimées pour ce volume. Indicatif, pas contractuel."""
        return mots / self.debit_mots_seconde if self.debit_mots_seconde else 0.0

    def decrire(self) -> dict:
        return {
            "nom": self.nom,
            "libelle": self.libelle,
            "capacites": sorted(str(c) for c in self.capacites),
            "debit_mots_seconde": self.debit_mots_seconde,
        }
