"""Diagnostic des moteurs. Alimente l'écran de configuration du front."""

from fastapi import APIRouter

from app.schemas.atelier import EtatMoteur
from app.services.traduction.registre import registre

routeur = APIRouter(tags=["moteurs"])


@routeur.get("/moteurs", response_model=list[EtatMoteur])
async def lister_moteurs() -> list[dict]:
    """Chaque moteur, ce qu'il sait faire et s'il est prêt maintenant.

    Le front s'en sert pour griser les combinaisons impossibles au lieu de
    laisser l'utilisateur lancer un travail voué à l'échec.
    """
    return await registre().diagnostiquer()
