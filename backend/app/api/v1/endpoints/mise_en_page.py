"""Mise en forme : structure détectée, puis composition HTML ou Markdown."""

from fastapi import APIRouter

from app.schemas.atelier import (
    DemandeMiseEnPage, ReponseMiseEnPage, ReponseStructure,
)
from app.services import mise_en_page as service

routeur = APIRouter(tags=["mise en page"])

AVERTISSEMENT_REPLI = (
    "Les paragraphes semblent repliés sur plusieurs lignes. La détection "
    "d'intertitres suppose un paragraphe par ligne — lance d'abord la passe "
    "de nettoyage avec fusion des paragraphes, sinon les intertitres seront "
    "pris pour du corps de texte."
)


def _texte_replie(texte: str) -> bool:
    lignes = [l for l in texte.split("\n") if l.strip()]
    if len(lignes) < 8:
        return False
    courtes = sum(1 for l in lignes if len(l) < 90)
    return courtes / len(lignes) > 0.75


@routeur.post("/structure", response_model=ReponseStructure)
async def detecter_structure(demande: DemandeMiseEnPage) -> ReponseStructure:
    """L'arbre détecté, avant de composer quoi que ce soit.

    À vérifier systématiquement : c'est ici que se voient les fausses
    détections de chapitre, et les intertitres manqués.
    """
    chapitres = service.analyser(demande.texte)
    return ReponseStructure(
        chapitres=service.structure(chapitres),
        avertissement=AVERTISSEMENT_REPLI if _texte_replie(demande.texte) else None,
    )


@routeur.post("/mise-en-page", response_model=ReponseMiseEnPage)
async def composer(demande: DemandeMiseEnPage) -> ReponseMiseEnPage:
    """HTML imprimable (Ctrl+P → PDF) ou Markdown (pandoc → .docx)."""
    chapitres = service.analyser(demande.texte)
    options = service.Options(**demande.options.model_dump())
    contenu = (
        service.en_markdown(chapitres, options)
        if demande.format == "md"
        else service.en_html(chapitres, options)
    )
    return ReponseMiseEnPage(
        contenu=contenu, format=demande.format, chapitres=len(chapitres)
    )
