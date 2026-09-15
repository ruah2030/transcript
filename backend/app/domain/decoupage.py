"""Découpage d'un document en sections, segments et phrases.

Trois granularités, trois usages :

    sections  — unité de structure (chapitre, partie). Sert au découpage
                utilisateur et à l'affichage du plan.
    segments  — unité d'envoi au LLM. Quelques milliers de caractères, pour
                que le modèle garde le fil sans saturer son contexte.
    phrases   — unité d'envoi au NMT. Les modèles Opus-MT et Argos traduisent
                phrase par phrase ; c'est aussi ce qui permet le batching.
"""

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------- sections

MOTIFS_TITRE = (
    r"#{1,3}\s+.+",                                          # markdown
    r"(?:Chapitre|Chapter|Capítulo|Capitolo|Kapitel)\s+[\dIVXLC]+.*",
    r"(?:Partie|Part|Parte|Teil|Section|Sección)\s+[\dIVXLC]+.*",
    r"(?:Introduction|Préface|Preface|Prólogo|Vorwort|Avant[- ]propos"
    r"|Conclusion|Annexe|Appendix|Résumé|Abstract|Sommaire"
    r"|Table des matières)\s*[:.!]?.*",
    r"\d{1,2}\.\s+[A-ZÉÈÀÎÔÛÄÖÜÑ][^\n]{3,80}",               # « 3. Méthodologie »
    r"[A-ZÉÈÀÎÔÛÄÖÜÑ][A-ZÉÈÀÎÔÛÄÖÜÑ \d’'-]{6,60}",           # TITRE EN CAPITALES
)
TITRE = re.compile(r"^\s*(" + "|".join(MOTIFS_TITRE) + r")\s*$", re.MULTILINE)

# Fin de phrase : ponctuation forte, espace, puis majuscule ou ouvrante.
FIN_PHRASE = re.compile(r"(?<=[.!?…])\s+(?=[«\"'(\[]?[A-ZÀ-ÖØ-Þ0-9])")

#: Abréviations qui se terminent par un point sans finir la phrase.
#: Sans elles, « M. Munroe » ou « cf. Jean » sont coupés en deux, et le
#: moteur traduit des fragments au lieu de phrases — ce qui dégrade le
#: résultat bien plus que le fragment lui-même ne le laisse croire.
ABREVIATIONS = {
    # civilités
    "m", "mm", "mme", "mmes", "mlle", "mlles", "dr", "drs", "pr", "me",
    "mr", "mrs", "ms", "jr", "sr", "st", "ste", "sts", "stes",
    # renvois et références
    "cf", "cfr", "ibid", "op", "loc", "id", "et al", "etc", "vs",
    "p", "pp", "vol", "chap", "ch", "art", "fig", "no", "n", "ed", "éd",
    "trad", "coll", "dir", "t", "v", "vv", "av", "apr",
    # locutions
    "i.e", "e.g", "c.-à-d", "j.-c", "environ", "approx", "env",
}

#: Initiale isolée : « J. K. Rowling », « C. S. Lewis ».
INITIALE = re.compile(r"\b[A-ZÀ-Þ]\.$")


def _termine_une_phrase(fragment: str) -> bool:
    """Le fragment se termine-t-il vraiment ?

    On regarde le dernier mot avant le point : si c'est une abréviation
    connue ou une initiale, la phrase continue.
    """
    fragment = fragment.rstrip()
    if not fragment.endswith("."):
        return True                      # ! ? … terminent toujours
    if INITIALE.search(fragment):
        return False
    dernier = re.split(r"[\s(\[«\"']", fragment)[-1].rstrip(".").lower()
    return dernier not in ABREVIATIONS


def _phrases_brutes(texte: str) -> list[str]:
    """Découpe puis recolle ce qui avait été coupé à tort."""
    morceaux = FIN_PHRASE.split(texte)
    phrases: list[str] = []
    for morceau in morceaux:
        if phrases and not _termine_une_phrase(phrases[-1]):
            phrases[-1] = f"{phrases[-1]} {morceau}"
        else:
            phrases.append(morceau)
    return phrases


@dataclass(slots=True)
class Section:
    indice: int
    titre: str
    corps: str

    @property
    def caracteres(self) -> int:
        return len(self.corps)


@dataclass(slots=True)
class Segment:
    """Un morceau de texte à traiter, rattaché à sa section d'origine."""

    indice: int
    section: int
    titre_section: str
    texte: str

    @property
    def caracteres(self) -> int:
        return len(self.texte)


@dataclass(slots=True)
class Phrase:
    """Une phrase, avec l'indice du paragraphe d'où elle vient.

    Le paragraphe sert au réassemblage : on recolle les phrases traduites
    dans leur paragraphe d'origine plutôt qu'en un bloc continu.
    """

    indice: int
    paragraphe: int
    texte: str


@dataclass(slots=True)
class Plan:
    """Résultat complet du découpage d'un document."""

    sections: list[Section] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    @property
    def caracteres(self) -> int:
        return sum(s.caracteres for s in self.sections)


def decouper_sections(texte: str) -> list[Section]:
    marques = list(TITRE.finditer(texte))
    if not marques:
        return [Section(0, "Document", texte.strip())]

    sections: list[Section] = []
    if marques[0].start() > 0:
        tete = texte[: marques[0].start()].strip()
        if tete:
            sections.append(Section(0, "Préambule", tete))

    for i, m in enumerate(marques):
        fin = marques[i + 1].start() if i + 1 < len(marques) else len(texte)
        corps = texte[m.end():fin].strip()
        if corps:
            sections.append(Section(len(sections), m.group(1).strip(), corps))
    return sections


def decouper_segments(sections: list[Section], taille: int = 3500) -> list[Segment]:
    """Regroupe les paragraphes en segments sans jamais couper un paragraphe."""
    segments: list[Segment] = []

    for section in sections:
        paras = [p.strip() for p in re.split(r"\n\s*\n", section.corps) if p.strip()]
        if not paras:
            paras = re.findall(r"[^.!?…。]+[.!?…。]+\s*", section.corps) or [section.corps]

        courant = ""
        for para in paras:
            if courant and len(courant) + len(para) + 2 > taille:
                segments.append(
                    Segment(len(segments), section.indice, section.titre, courant)
                )
                courant = para
            else:
                courant = f"{courant}\n\n{para}" if courant else para
        if courant:
            segments.append(
                Segment(len(segments), section.indice, section.titre, courant)
            )

    return segments


def construire_plan(texte: str, taille_segment: int = 3500) -> Plan:
    sections = decouper_sections(texte)
    return Plan(sections=sections, segments=decouper_segments(sections, taille_segment))


# ---------------------------------------------------------------- phrases

def decouper_phrases(texte: str, longueur_max: int = 900) -> list[Phrase]:
    """Découpe en phrases pour les moteurs NMT.

    `longueur_max` est un filet de sécurité : une « phrase » plus longue que
    ça (liste sans ponctuation, tableau collé) ferait déborder le décodeur.
    On la coupe alors sur le dernier espace disponible.
    """
    phrases: list[Phrase] = []
    paragraphes = [p for p in texte.split("\n\n") if p.strip()]

    for indice_para, para in enumerate(paragraphes):
        normalise = " ".join(para.split())
        for brut in _phrases_brutes(normalise):
            reste = brut.strip()
            while len(reste) > longueur_max:
                coupe = reste.rfind(" ", 0, longueur_max)
                coupe = coupe if coupe > longueur_max // 2 else longueur_max
                phrases.append(Phrase(len(phrases), indice_para, reste[:coupe].strip()))
                reste = reste[coupe:].strip()
            if reste:
                phrases.append(Phrase(len(phrases), indice_para, reste))

    return phrases


def reassembler_phrases(phrases: list[Phrase], traductions: list[str]) -> str:
    """Recolle les phrases traduites dans leurs paragraphes d'origine."""
    if len(phrases) != len(traductions):
        raise ValueError(
            f"{len(phrases)} phrases mais {len(traductions)} traductions"
        )

    paragraphes: dict[int, list[str]] = {}
    for phrase, traduite in zip(phrases, traductions):
        paragraphes.setdefault(phrase.paragraphe, []).append(traduite)

    return "\n\n".join(" ".join(paragraphes[k]) for k in sorted(paragraphes))
