"""Assemblage des routes de la v1."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    correction, documents, glossaire, mise_en_page, modeles, moteurs,
    traduction, transcription, travaux, verification,
)

routeur = APIRouter(prefix="/api/v1")

for module in (correction, documents, glossaire, mise_en_page, modeles,
               moteurs, transcription, traduction, verification,
               travaux):
    routeur.include_router(module.routeur)
