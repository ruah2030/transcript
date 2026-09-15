"""Registre des moteurs disponibles.

Point unique d'accès. Les moteurs sont instanciés une fois pour toute la
durée du processus : le chargement CTranslate2 coûte quelques secondes et
occupe de la mémoire, on ne le refait pas à chaque requête.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.erreurs import CapaciteAbsente, MoteurInconnu
from app.services.traduction.base import Capacite, MoteurTraduction
from app.services.traduction.hybride import MoteurHybride
from app.services.traduction.llm import MoteurLLM
from app.services.traduction.nmt import MoteurArgos, MoteurOpusMT
from app.services.traduction.reparation import MoteurReparationCiblee


class RegistreMoteurs:
    def __init__(self):
        opus = MoteurOpusMT()
        argos = MoteurArgos()
        llm = MoteurLLM()
        self._moteurs: dict[str, MoteurTraduction] = {
            opus.nom: opus,
            argos.nom: argos,
            llm.nom: llm,
            "hybride": MoteurHybride(nmt=opus, llm=llm),
            "reparation_ciblee": MoteurReparationCiblee(llm=llm),
        }

    def __iter__(self):
        return iter(self._moteurs.values())

    def obtenir(self, nom: str) -> MoteurTraduction:
        moteur = self._moteurs.get(nom)
        if moteur is None:
            raise MoteurInconnu(
                f"Moteur inconnu : {nom}",
                f"Disponibles : {', '.join(sorted(self._moteurs))}",
            )
        return moteur

    def resoudre(self, nom: str, capacite: Capacite) -> MoteurTraduction:
        """Récupère le moteur et vérifie tout de suite qu'il sait faire.

        Cette vérification est faite avant l'ouverture du travail, pour que
        l'utilisateur soit refusé en une seconde plutôt qu'après dix minutes.
        """
        moteur = self.obtenir(nom)
        if not moteur.sait_faire(capacite):
            capables = [
                m.nom for m in self._moteurs.values() if m.sait_faire(capacite)
            ]
            raise CapaciteAbsente(
                f"{moteur.libelle} ne sait pas faire « {capacite} ».",
                f"Moteurs capables : {', '.join(capables) or 'aucun'}.",
            )
        return moteur

    async def diagnostiquer(self) -> list[dict]:
        rapport = []
        for moteur in self._moteurs.values():
            etat = await moteur.etat()
            rapport.append({
                **moteur.decrire(),
                "disponible": etat.disponible,
                "detail": etat.detail,
                "paires": etat.paires,
                "remede": etat.remede,
            })
        return rapport


@lru_cache
def registre() -> RegistreMoteurs:
    return RegistreMoteurs()
