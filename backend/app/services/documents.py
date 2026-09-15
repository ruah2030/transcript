"""Lecture des formats d'entrée.

Le .docx est lu sans dépendance externe : c'est un zip contenant du XML,
et pour du texte brut un dézippage suffit. Les formats qui demandent un
vrai convertisseur renvoient une erreur explicite avec la commande à
lancer, plutôt qu'un échec silencieux.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from app.core.erreurs import DocumentInvalide

ENTITES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
           ("&quot;", '"'), ("&apos;", "'"))


def lire_docx(donnees: bytes) -> str:
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(donnees)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError) as e:
        raise DocumentInvalide("Fichier .docx illisible", str(e)) from e

    xml = re.sub(r"</w:p>", "\n\n", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    texte = re.sub(r"<[^>]+>", "", xml)
    for avant, apres in ENTITES:
        texte = texte.replace(avant, apres)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


CONVERSIONS = {
    ".pdf": "pdftotext -layout {f} sortie.txt",
    ".odt": "pandoc {f} -t plain -o sortie.txt",
    ".rtf": "pandoc {f} -t plain -o sortie.txt",
    ".epub": "pandoc {f} -t plain -o sortie.txt",
    ".html": "pandoc {f} -t plain -o sortie.txt",
}


def lire(nom: str, donnees: bytes) -> str:
    extension = Path(nom).suffix.lower()

    if extension == ".docx":
        return lire_docx(donnees)

    if extension in CONVERSIONS:
        raise DocumentInvalide(
            f"Le format {extension} n'est pas lu directement.",
            "Convertis-le d'abord :  " + CONVERSIONS[extension].format(f=nom),
        )

    try:
        return donnees.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return donnees.decode("latin-1")
        except Exception as e:
            raise DocumentInvalide("Encodage non reconnu", str(e)) from e
