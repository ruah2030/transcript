"""Suivi des travaux longs : instantané, flux SSE, résultat, annulation."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.erreurs import RessourceIntrouvable
from app.infra.travaux import EtatTravail, gestionnaire
from app.schemas.atelier import InstantaneTravail

routeur = APIRouter(prefix="/travaux", tags=["travaux"])


@routeur.get("", response_model=list[InstantaneTravail])
async def lister(limite: int = 50) -> list[dict]:
    return gestionnaire.lister(limite)


@routeur.get("/{identifiant}", response_model=InstantaneTravail)
async def instantane(identifiant: str) -> dict:
    return gestionnaire.obtenir(identifiant).instantane()


@routeur.get("/{identifiant}/flux")
async def flux(identifiant: str) -> StreamingResponse:
    """Progression en Server-Sent Events.

    Trois types d'événements : `etat` au raccordement et aux transitions,
    `progression` à chaque avancée, `fin` quand c'est terminé. Un commentaire
    de battement toutes les 15 secondes garde la connexion ouverte à travers
    les reverse-proxies.
    """
    gestionnaire.obtenir(identifiant)   # 404 immédiat si inconnu
    return StreamingResponse(
        gestionnaire.flux(identifiant),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # désactive le tampon nginx
        },
    )


@routeur.get("/{identifiant}/resultat")
async def resultat(identifiant: str) -> dict:
    travail = gestionnaire.obtenir(identifiant)
    if travail.etat is not EtatTravail.TERMINE:
        raise RessourceIntrouvable(
            f"Le travail n'est pas terminé (état : {travail.etat}).",
            "Abonne-toi au flux pour attendre la fin.",
        )
    return travail.resultat


@routeur.delete("/{identifiant}", response_model=InstantaneTravail)
async def annuler(identifiant: str) -> dict:
    travail = await gestionnaire.annuler(identifiant)
    return travail.instantane()
