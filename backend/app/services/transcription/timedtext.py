"""Sous-titres YouTube par les endpoints `timedtext`.

Deuxième voie d'accès aux sous-titres, indépendante de yt-dlp.

yt-dlp interroge l'API du lecteur, celle que YouTube protège le plus
sévèrement — d'où les blocages « Sign in to confirm you're not a bot ».
`youtube-transcript-api` lit les endpoints `timedtext`, la même source que
le panneau de transcription affiché sur youtube.com. Ce n'est ni une clé
d'API, ni OAuth, ni un navigateur piloté : juste l'endpoint que la page
web appelle elle-même.

Les deux chemins étant distincts, l'un passe souvent quand l'autre est
refusé. On essaie donc celui-ci en premier : il est plus léger, plus rapide,
et couvre l'essentiel du besoin, puisque la grande majorité des vidéos ont
des sous-titres, ne serait-ce qu'automatiques.

Il ne donne accès qu'aux sous-titres. Une vidéo qui n'en a pas passe par
yt-dlp puis Whisper.
"""

from __future__ import annotations

import asyncio
import re

from app.core.erreurs import MoteurIndisponible
from app.services.transcription.base import Media, Origine, PisteSousTitres, Transcription

#: Formes d'URL YouTube dont on sait extraire l'identifiant.
MOTIFS_ID = (
    re.compile(r"(?:youtube\.com|youtube-nocookie\.com)/watch\?(?:.*&)?v=([\w-]{11})"),
    re.compile(r"youtu\.be/([\w-]{11})"),
    re.compile(r"youtube\.com/(?:embed|shorts|live|v)/([\w-]{11})"),
)


def identifiant(url: str) -> str | None:
    """Identifiant de la vidéo, ou None si l'URL n'est pas une vidéo YouTube."""
    for motif in MOTIFS_ID:
        trouve = motif.search(url)
        if trouve:
            return trouve.group(1)
    # Un identifiant nu passé directement.
    if re.fullmatch(r"[\w-]{11}", url.strip()):
        return url.strip()
    return None


def _api():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as e:
        raise MoteurIndisponible(
            "youtube-transcript-api n'est pas installé.",
            "pip install youtube-transcript-api\n\n"
            "Cette voie lit les sous-titres par les endpoints timedtext de "
            "YouTube, indépendamment de yt-dlp. Elle passe souvent quand "
            "yt-dlp est bloqué.",
        ) from e
    return YouTubeTranscriptApi


def _lister(video: str):
    """Pistes disponibles. Gère les deux générations d'API de la
    bibliothèque : instance depuis la 1.x, méthode de classe avant."""
    Api = _api()
    if hasattr(Api, "list"):
        return Api().list(video)
    return Api.list_transcripts(video)      # type: ignore[attr-defined]


def _recuperer(video: str, langues: list[str]):
    Api = _api()
    if hasattr(Api, "fetch"):
        return Api().fetch(video, languages=langues)
    return Api.get_transcript(video, languages=langues)  # type: ignore[attr-defined]


def _entrees(recupere) -> list[dict]:
    """Normalise la sortie : la 1.x rend un objet, les versions
    antérieures une liste de dictionnaires."""
    if hasattr(recupere, "to_raw_data"):
        return recupere.to_raw_data()
    return list(recupere)


def _en_paragraphes(entrees: list[dict]) -> str:
    """Recolle en paragraphes. Les sous-titres arrivent par fragments de
    quelques secondes ; les passes suivantes attendent de la prose."""
    morceaux = [
        " ".join(str(e.get("text", "")).split())
        for e in entrees
        if str(e.get("text", "")).strip()
    ]
    texte = " ".join(morceaux)
    texte = re.sub(r"\s+", " ", texte).strip()

    paragraphes, courant = [], ""
    for phrase in re.split(r"(?<=[.!?…])\s+", texte):
        courant = f"{courant} {phrase}".strip() if courant else phrase
        if len(courant) > 400:
            paragraphes.append(courant)
            courant = ""
    if courant:
        paragraphes.append(courant)
    return "\n\n".join(paragraphes)


async def pistes(url: str) -> list[PisteSousTitres]:
    """Pistes disponibles, sans rien télécharger. Liste vide si inaccessible."""
    video = identifiant(url)
    if video is None:
        return []

    def travailler() -> list[PisteSousTitres]:
        try:
            liste = _lister(video)
        except Exception:                                   # noqa: BLE001
            return []
        trouvees = []
        for piste in liste:
            trouvees.append(PisteSousTitres(
                langue=getattr(piste, "language_code", "?"),
                automatique=bool(getattr(piste, "is_generated", True)),
                nom=getattr(piste, "language", ""),
            ))
        return trouvees

    return await asyncio.to_thread(travailler)


async def recuperer(
    url: str, langue: str, media: Media | None = None,
) -> Transcription | None:
    """Sous-titres pour cette langue, ou None si indisponibles.

    Ne lève pas sur un échec réseau : l'appelant enchaîne sur yt-dlp.
    """
    video = identifiant(url)
    if video is None:
        return None

    # La langue demandée d'abord, puis l'anglais comme repli usuel.
    langues = [langue] if langue else []
    for repli in ("en", "fr"):
        if repli not in langues:
            langues.append(repli)

    def travailler():
        try:
            recupere = _recuperer(video, langues)
        except MoteurIndisponible:
            raise
        except Exception:                                   # noqa: BLE001
            return None

        entrees = _entrees(recupere)
        if not entrees:
            return None

        code = getattr(recupere, "language_code", langues[0])
        genere = bool(getattr(recupere, "is_generated", True))
        return Transcription(
            texte=_en_paragraphes(entrees),
            origine=(Origine.SOUS_TITRES_AUTO if genere
                     else Origine.SOUS_TITRES_HUMAINS),
            langue=code,
            duree_secondes=media.duree_secondes if media else 0.0,
            titre=media.titre if media else "",
        )

    return await asyncio.to_thread(travailler)


async def disponible() -> tuple[bool, str]:
    try:
        _api()
        return True, "prêt"
    except MoteurIndisponible as e:
        return False, e.message
