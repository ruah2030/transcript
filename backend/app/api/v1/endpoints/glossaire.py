"""Lecture et écriture du glossaire depuis l'interface."""

from fastapi import APIRouter

from app.schemas.atelier import Glossaire
from app.services import glossaire as service

routeur = APIRouter(tags=["glossaire"])


@routeur.get("/glossaires")
async def lister() -> list[str]:
    return service.lister()


@routeur.get("/glossaires/{nom}", response_model=Glossaire)
async def lire(nom: str) -> dict:
    return service.charger(nom)


@routeur.put("/glossaires/{nom}", response_model=Glossaire)
async def ecrire(nom: str, contenu: Glossaire) -> dict:
    return service.enregistrer(contenu.model_dump(), nom)
