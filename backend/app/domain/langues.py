"""Codes de langue et noms lisibles."""

LANGUES = {
    "fr": "français", "en": "anglais", "es": "espagnol", "de": "allemand",
    "it": "italien", "pt": "portugais", "nl": "néerlandais", "pl": "polonais",
    "ru": "russe", "ar": "arabe", "zh": "chinois", "ja": "japonais",
    "ko": "coréen", "tr": "turc", "sv": "suédois", "da": "danois",
    "no": "norvégien", "fi": "finnois", "cs": "tchèque", "el": "grec",
    "he": "hébreu", "hi": "hindi",
}


def nom_langue(code: str) -> str:
    """Nom français de la langue. Un code inconnu est renvoyé tel quel :
    « wolof », « fon » et « yoruba » passent au LLM sans traduction."""
    return LANGUES.get(code.lower(), code)


def paire(source: str, cible: str) -> str:
    return f"{source.lower()}-{cible.lower()}"
