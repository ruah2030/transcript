"""Mise en forme et mise en page — portage de `mettre_en_page.py`.

La structure est inférée du texte : chapitres, exergues (la phrase isolée
qui suit un titre), intertitres, listes de principes, références bibliques.
La détection est faillible par nature, d'où l'endpoint `/structure` qui
montre l'arbre avant de produire quoi que ce soit.

Le gabarit HTML est repris tel quel : format de page, justification avec
césure, lettrine, sommaire cliquable, sauts de page par chapitre, lignes
veuves et orphelines. Il est composé pour l'impression, pas pour l'écran.
"""

from __future__ import annotations

import html as H
import re
from dataclasses import dataclass, field
from typing import Literal

# ------------------------------------------------------------- détection

CHAPITRE = re.compile(
    r"^\s*(?:#\s+)?((?:Chapitre|Chapter|Partie|Section)\s+[\dIVXLC]+\s*[.:\u2014-]?\s*.*"
    r"|Pr\u00e9face|Preface|Introduction|Avant[- ]propos|Prologue|\u00c9pilogue"
    r"|Conclusion|D\u00e9vouement|Remerciements?|Annexes?|Postface)\s*[.:!]?\s*$",
    re.IGNORECASE,
)
LISTE_PRINCIPES = re.compile(r"^\s*(?:Des\s+)?[Pp]rincipes?\s*[?!.:]?\s*$")
ITEM = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+(.+)$")
REFERENCE = re.compile(
    r"\b((?:[1-3]\s)?[A-Z\u00c9\u00c8\u00c0][\w\u00e9\u00e8\u00ea\u00eb\u00e0\u00e2\u00ee\u00ef\u00f4\u00fb\u00fc\u00e7]{2,15}\.?)\s+(\d+)\.(\d+)(?:-(\d+))?\b"
)

PAGES = {
    "a5": ("148mm", "210mm", "14mm 16mm"),
    "a4": ("210mm", "297mm", "22mm 26mm"),
    "lettre": ("8.5in", "11in", "22mm 26mm"),
}

Genre = Literal["p", "intertitre", "principes"]


@dataclass(slots=True)
class Chapitre:
    titre: str | None
    exergue: str | None = None
    blocs: list[tuple[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class Options:
    titre: str = ""
    auteur: str = ""
    taille: str = "a5"
    police: str = "serif"
    corps: float = 11
    interligne: float = 1.5
    sans_toc: bool = False
    sans_lettrine: bool = False


def est_intertitre(ligne: str, suivante: str) -> bool:
    """Court, sans ponctuation finale, suivi d'un vrai paragraphe."""
    l = ligne.strip()
    if not (3 < len(l) <= 70):
        return False
    if l.startswith("##"):
        return True
    if l[-1] in ".,;:!?\u2026\u00bb":
        return False
    if not l[0].isupper():
        return False
    if ITEM.match(l):
        return False
    return bool(suivante.strip()) and len(suivante.strip()) > 80


def analyser(texte: str) -> list[Chapitre]:
    lignes = [l.rstrip() for l in texte.split("\n")]
    chapitres: list[Chapitre] = []
    courant: Chapitre | None = None
    i = 0

    while i < len(lignes):
        ligne = lignes[i]
        if not ligne.strip():
            i += 1
            continue

        if CHAPITRE.match(ligne):
            if courant:
                chapitres.append(courant)
            courant = Chapitre(titre=re.sub(r"^#+\s*", "", ligne.strip().rstrip(".:!")))

            # Exergue : ligne courte isolée juste après le titre.
            j = i + 1
            while j < len(lignes) and not lignes[j].strip():
                j += 1
            if j < len(lignes) and 10 < len(lignes[j].strip()) <= 110:
                suivante = lignes[j + 1] if j + 1 < len(lignes) else ""
                if not suivante.strip() or len(lignes[j].strip()) < 90:
                    courant.exergue = lignes[j].strip()
                    i = j + 1
                    continue
            i += 1
            continue

        if courant is None:
            courant = Chapitre(titre=None)

        if LISTE_PRINCIPES.match(ligne):
            items, j = [], i + 1
            while j < len(lignes):
                if not lignes[j].strip():
                    j += 1
                    continue
                mi = ITEM.match(lignes[j])
                if not mi:
                    break
                items.append(mi.group(2).strip())
                j += 1
            if items:
                courant.blocs.append(("principes", items))
                i = j
                continue

        suivante = ""
        for k in range(i + 1, min(i + 4, len(lignes))):
            if lignes[k].strip():
                suivante = lignes[k]
                break
        if est_intertitre(ligne, suivante):
            courant.blocs.append(("intertitre", re.sub(r"^#+\s*", "", ligne.strip())))
            i += 1
            continue

        courant.blocs.append(("p", ligne.strip()))
        i += 1

    if courant:
        chapitres.append(courant)
    return chapitres


def proteger_refs(t: str) -> str:
    """Empêche les références bibliques d'être coupées en fin de ligne."""
    return REFERENCE.sub(lambda m: '<span class="ref">' + m.group(0) + "</span>", t)


# ----------------------------------------------------------------- HTML

GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{titre}</title>
<style>
  @page {{
    size: {largeur} {hauteur};
    margin: {marges};
    @bottom-center {{ content: counter(page); font-size: 9pt; }}
  }}
  @page :first {{ @bottom-center {{ content: ""; }} }}

  :root {{
    --labeur: {famille};
    --corps: {corps}pt;
    --interligne: {interligne};
    --encre: #14181a;
    --gris: #6b7378;
  }}

  * {{ box-sizing: border-box; }}
  body {{
    margin: 0 auto;
    max-width: 34em;
    padding: 3rem 1.5rem 5rem;
    font-family: var(--labeur);
    font-size: var(--corps);
    line-height: var(--interligne);
    color: var(--encre);
    background: #fbfaf8;
    hyphens: auto;
    -webkit-hyphens: auto;
    text-align: justify;
    text-justify: inter-word;
  }}

  /* ---- couverture ---- */
  .couverture {{
    text-align: center;
    padding: 22vh 0 0;
    page-break-after: always;
  }}
  .couverture h1 {{
    font-size: 2.1em;
    font-weight: 600;
    line-height: 1.15;
    letter-spacing: -.01em;
    margin: 0 0 .8em;
  }}
  .couverture .auteur {{
    font-size: 1em;
    color: var(--gris);
    letter-spacing: .12em;
    text-transform: uppercase;
  }}
  .couverture .filet {{
    width: 3.5em; height: 1px;
    background: var(--encre);
    margin: 2.2em auto;
  }}

  /* ---- table des matières ---- */
  nav {{ page-break-after: always; text-align: left; }}
  nav h2 {{
    font-size: 1em; font-weight: 600;
    letter-spacing: .14em; text-transform: uppercase;
    color: var(--gris);
    margin: 0 0 1.6em;
  }}
  nav ol {{ list-style: none; margin: 0; padding: 0; }}
  nav li {{ margin: 0 0 .55em; }}
  nav a {{ color: var(--encre); text-decoration: none; }}
  nav .num {{
    display: inline-block; width: 2.4em;
    color: var(--gris); font-variant-numeric: tabular-nums;
  }}

  /* ---- chapitres ---- */
  section {{ page-break-before: always; }}
  section:first-of-type {{ page-break-before: avoid; }}

  h2.chapitre {{
    font-size: 1.35em;
    font-weight: 600;
    line-height: 1.25;
    text-align: left;
    margin: 0 0 .3em;
    page-break-after: avoid;
  }}
  .exergue {{
    font-style: italic;
    color: var(--gris);
    text-align: left;
    margin: 0 0 2.4em;
    padding-bottom: 1.4em;
    border-bottom: 1px solid #e2ded7;
    page-break-after: avoid;
  }}

  h3 {{
    font-size: 1em;
    font-weight: 600;
    text-align: left;
    margin: 2.2em 0 .7em;
    page-break-after: avoid;
  }}

  p {{ margin: 0; text-indent: 1.3em; orphans: 3; widows: 3; }}
  p.premier {{ text-indent: 0; }}
  h3 + p, .exergue + p {{ text-indent: 0; }}

  {lettrine}

  /* ---- listes de principes ---- */
  .principes {{
    margin: 2.2em 0;
    padding: 1.4em 1.6em;
    background: #f4f1ec;
    border-left: 2px solid var(--encre);
    counter-reset: principe;
    list-style: none;
    text-align: left;
    page-break-inside: avoid;
  }}
  .principes li {{
    position: relative;
    padding-left: 2.2em;
    margin-bottom: .7em;
    text-indent: 0;
  }}
  .principes li:last-child {{ margin-bottom: 0; }}
  .principes li::before {{
    counter-increment: principe;
    content: counter(principe);
    position: absolute; left: 0; top: 0;
    font-variant-numeric: tabular-nums;
    color: var(--gris);
    font-size: .85em;
  }}

  .ref {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}

  @media print {{
    body {{ background: #fff; max-width: none; padding: 0; }}
    nav a {{ color: #000; }}
  }}
</style>
</head>
<body>
{couverture}{toc}{corps_html}
</body>
</html>
"""

LETTRINE = """
  section > p.premier::first-letter {
    float: left;
    font-size: 3.1em;
    line-height: .82;
    padding: .06em .09em 0 0;
    font-weight: 600;
  }
"""


def en_html(chapitres: list[Chapitre], options: Options) -> str:
    largeur, hauteur, marges = PAGES[options.taille]
    famille = (
        'Iowan Old Style, "Palatino Linotype", Palatino, Georgia, serif'
        if options.police == "serif"
        else '"Helvetica Neue", Inter, system-ui, sans-serif'
    )

    couverture = ""
    if options.titre:
        couverture = (
            '<div class="couverture">\n'
            f'  <h1>{H.escape(options.titre)}</h1>\n'
            '  <div class="filet"></div>\n'
            + (f'  <div class="auteur">{H.escape(options.auteur)}</div>\n'
               if options.auteur else "")
            + "</div>\n"
        )

    toc = ""
    if not options.sans_toc:
        entrees = [
            f'    <li><a href="#ch{n}"><span class="num">{n}</span>'
            f'{H.escape(ch.titre)}</a></li>'
            for n, ch in enumerate(chapitres, 1) if ch.titre
        ]
        if entrees:
            toc = ("<nav>\n  <h2>Sommaire</h2>\n  <ol>\n"
                   + "\n".join(entrees) + "\n  </ol>\n</nav>\n")

    morceaux = []
    for n, ch in enumerate(chapitres, 1):
        morceaux.append(f'<section id="ch{n}">')
        if ch.titre:
            morceaux.append(f'  <h2 class="chapitre">{H.escape(ch.titre)}</h2>')
        if ch.exergue:
            morceaux.append(f'  <p class="exergue">{H.escape(ch.exergue)}</p>')

        premier = True
        for genre, contenu in ch.blocs:
            if genre == "p":
                classe = ' class="premier"' if premier else ""
                premier = False
                morceaux.append(f"  <p{classe}>{proteger_refs(H.escape(str(contenu)))}</p>")
            elif genre == "intertitre":
                premier = False
                morceaux.append(f"  <h3>{H.escape(str(contenu))}</h3>")
            elif genre == "principes":
                premier = False
                items = "\n".join(
                    f"    <li>{proteger_refs(H.escape(x))}</li>" for x in contenu  # type: ignore[union-attr]
                )
                morceaux.append(f'  <ol class="principes">\n{items}\n  </ol>')
        morceaux.append("</section>")

    return GABARIT.format(
        titre=H.escape(options.titre or "Document"),
        largeur=largeur, hauteur=hauteur, marges=marges,
        famille=famille, corps=options.corps, interligne=options.interligne,
        lettrine="" if options.sans_lettrine else LETTRINE,
        couverture=couverture, toc=toc, corps_html="\n".join(morceaux),
    )


def en_markdown(chapitres: list[Chapitre], options: Options) -> str:
    """Markdown avec en-tête YAML, pour repasser en .docx via pandoc."""
    sortie: list[str] = []
    if options.titre:
        sortie.append("---")
        sortie.append(f'title: "{options.titre}"')
        if options.auteur:
            sortie.append(f'author: "{options.auteur}"')
        sortie.append("lang: fr")
        sortie.append("---\n")

    for ch in chapitres:
        if ch.titre:
            sortie.append(f"\n# {ch.titre}\n")
        if ch.exergue:
            sortie.append(f"> *{ch.exergue}*\n")
        for genre, contenu in ch.blocs:
            if genre == "p":
                sortie.append(str(contenu) + "\n")
            elif genre == "intertitre":
                sortie.append(f"\n## {contenu}\n")
            elif genre == "principes":
                for i, x in enumerate(contenu, 1):  # type: ignore[arg-type]
                    sortie.append(f"{i}. {x}")
                sortie.append("")

    return "\n".join(sortie).strip() + "\n"


def structure(chapitres: list[Chapitre]) -> list[dict]:
    """Arbre détecté, à vérifier avant de composer. C'est ici que se voient
    les fausses détections de chapitre ou d'intertitre."""
    return [
        {
            "titre": ch.titre,
            "exergue": ch.exergue,
            "paragraphes": sum(1 for g, _ in ch.blocs if g == "p"),
            "intertitres": [c for g, c in ch.blocs if g == "intertitre"],
            "listes_principes": sum(1 for g, _ in ch.blocs if g == "principes"),
        }
        for ch in chapitres
    ]
