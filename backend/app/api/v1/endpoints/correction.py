"""Passes 1 à 4. Rapides et pures : réponse directe, pas de travail."""

from fastapi import APIRouter

from app.core.config import reglages
from app.schemas.atelier import (
    DemandeCorrection, DemandeNettoyage, ReponseCorrection, ReponseNettoyage,
)
from app.services import correction

routeur = APIRouter(tags=["correction"])


@routeur.post("/nettoyage", response_model=ReponseNettoyage)
async def nettoyer(demande: DemandeNettoyage) -> ReponseNettoyage:
    """Passe 1 — retire les marqueurs temporels des transcriptions."""
    texte, retires = correction.nettoyer_timestamps(
        demande.texte, demande.fusionner_paragraphes
    )
    return ReponseNettoyage(texte=texte, marqueurs_retires=retires)


@routeur.post("/correction", response_model=ReponseCorrection)
async def corriger(demande: DemandeCorrection) -> ReponseCorrection:
    """Passes 2 à 4 — typographie, dictionnaires, références, grammaire."""
    from app.domain import typographie as typo

    texte = demande.texte
    rapport = correction.Rapport()

    if demande.typographie:
        texte = typo.appliquer(texte, "fr")

    if demande.dedoublonner:
        texte, rapport.doublons_retires = correction.dedoublonner(texte)

    for nom in demande.dictionnaires:
        chemin = reglages().dossier_ressources / nom
        dico = correction.charger_dictionnaire(chemin)
        texte = correction.appliquer_dictionnaire(texte, dico, rapport)

    refs = 0
    if demande.references:
        texte, refs = correction.normaliser_references(texte)

    if demande.grammaire:
        texte, rapport.corrections_grammaire = await correction.grammaire(texte)

    return ReponseCorrection(
        texte=texte,
        regles_appliquees=rapport.applique,
        total_applique=rapport.total_applique,
        signalements=rapport.signale,
        doublons_retires=rapport.doublons_retires,
        references_normalisees=refs,
        corrections_grammaire=rapport.corrections_grammaire,
    )


@routeur.get("/dictionnaires")
async def lister_dictionnaires() -> list[dict]:
    return correction.dictionnaires_disponibles()
