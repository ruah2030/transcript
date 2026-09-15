"""Import de fichiers. Rend du texte brut, que le front réinjecte."""

from fastapi import APIRouter, File, UploadFile

from app.services import documents

routeur = APIRouter(tags=["documents"])

TAILLE_MAX = 20 * 1024 * 1024


@routeur.post("/documents/import")
async def importer(fichier: UploadFile = File(...)) -> dict:
    """Lit .txt, .md et .docx directement. Les autres formats renvoient la
    commande de conversion à lancer, plutôt qu'un échec opaque."""
    from app.core.erreurs import DocumentInvalide

    donnees = await fichier.read()
    if len(donnees) > TAILLE_MAX:
        raise DocumentInvalide(
            f"Fichier trop volumineux ({len(donnees) // 1024} Ko, "
            f"limite {TAILLE_MAX // 1024 // 1024} Mo)."
        )

    texte = documents.lire(fichier.filename or "sans-nom.txt", donnees)
    return {
        "nom": fichier.filename,
        "texte": texte,
        "caracteres": len(texte),
        "mots": len(texte.split()),
    }
