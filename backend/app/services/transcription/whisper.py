"""Transcription audio par faster-whisper.

faster-whisper est une réimplémentation de Whisper sur CTranslate2 — le même
moteur d'inférence que les traducteurs Opus-MT et Argos de cet atelier. Il
n'y a donc pas de deuxième pile à installer : `pip install faster-whisper`
réutilise ce qui est déjà là.

Comme pour la traduction, le calcul est bloquant et libère le GIL. On
l'exécute dans un pool à un seul fil : sans GPU, le batching interne sature
déjà tous les cœurs, et lancer deux transcriptions en parallèle les ferait
se disputer le CPU sans rien gagner.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.config import reglages
from app.core.erreurs import MoteurIndisponible
from app.services.traduction.base import Etat, Progression
from app.services.transcription.base import (
    POIDS_MODELES, VITESSE_MODELES, Origine, Transcription,
)

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
_MODELES: dict[str, object] = {}


def _charger(nom: str):
    """Chargement paresseux et mis en cache : quelques secondes au premier
    appel, réutilisé ensuite."""
    if nom in _MODELES:
        return _MODELES[nom]

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise MoteurIndisponible(
            "faster-whisper n'est pas installé.",
            "pip install faster-whisper\n\n"
            "Il s'appuie sur CTranslate2, déjà présent si tu utilises Opus-MT.",
        ) from e

    cfg = reglages()
    _MODELES[nom] = WhisperModel(
        nom,
        device="cpu",
        compute_type=cfg.whisper_calcul,
        cpu_threads=cfg.ct2_threads or 0,
        download_root=str(cfg.dossier_modeles / "whisper"),
    )
    return _MODELES[nom]


def duree_estimee(secondes_audio: float, modele: str) -> float:
    """Secondes de calcul pour cette durée d'audio. Indicatif."""
    return secondes_audio / VITESSE_MODELES.get(modele, 4.0)


def modeles_disponibles() -> list[dict]:
    return [
        {
            "nom": nom,
            "poids": POIDS_MODELES.get(nom, ""),
            "vitesse_x_temps_reel": vitesse,
            "note": _note(nom),
        }
        for nom, vitesse in VITESSE_MODELES.items()
    ]


def _note(nom: str) -> str:
    return {
        "tiny": "Repérage seulement. Trop d'erreurs pour un texte à garder.",
        "base": "Correct sur une prise de son nette, sans accent marqué.",
        "small": "Le bon compromis sur CPU. À prendre par défaut.",
        "distil-large-v3": "Qualité proche de large-v3, quatre fois plus rapide. "
                           "Optimisé pour l'anglais.",
        "medium": "Nettement meilleur sur les accents et le bruit de fond.",
        "large-v3": "Le meilleur, mais plus lent que le temps réel sans GPU.",
    }.get(nom, "")


async def etat() -> Etat:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return Etat(
            False, "faster-whisper n'est pas installé", [],
            "pip install faster-whisper",
        )
    import shutil
    if shutil.which("ffmpeg") is None:
        return Etat(
            False, "ffmpeg est absent", [],
            "sudo apt install ffmpeg\n\n"
            "Nécessaire pour décoder l'audio.",
        )
    caches = sorted(
        (reglages().dossier_modeles / "whisper").glob("models--*")
    )
    noms = [c.name.split("--")[-1] for c in caches]
    return Etat(
        True,
        f"prêt ({len(noms)} modèle(s) en cache)" if noms else "prêt (aucun modèle en cache)",
        noms,
    )


async def transcrire(
    audio: Path,
    modele: str = "small",
    langue: str | None = None,
    horodatages: bool = False,
    progression: Progression = None,
) -> Transcription:
    """Transcrit un fichier audio.

    `langue = None` laisse Whisper détecter. Préciser la langue quand tu la
    connais est plus sûr : sur une entrée en français avec des citations
    anglaises, la détection automatique bascule parfois d'une langue à
    l'autre en cours de route.
    """
    if not audio.is_file():
        raise MoteurIndisponible(f"Fichier audio introuvable : {audio}")

    instance = _charger(modele)
    boucle = asyncio.get_running_loop()
    file: asyncio.Queue = asyncio.Queue()

    def travailler():
        """Tourne dans le pool. Pousse chaque segment dans la file pour que
        la boucle asyncio puisse diffuser la progression au fil de l'eau."""
        segments, info = instance.transcribe(   # type: ignore[attr-defined]
            str(audio),
            language=langue,
            beam_size=1,               # greedy : le plus rapide sur CPU
            vad_filter=True,           # saute les silences
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,   # évite les boucles de répétition
            word_timestamps=False,
        )
        boucle.call_soon_threadsafe(file.put_nowait, ("info", info))
        for segment in segments:
            boucle.call_soon_threadsafe(file.put_nowait, ("segment", segment))
        boucle.call_soon_threadsafe(file.put_nowait, ("fin", None))

    tache = boucle.run_in_executor(_POOL, travailler)

    morceaux: list[str] = []
    details: list[dict] = []
    duree_totale = 0.0
    langue_detectee = langue or "?"

    while True:
        genre, charge = await file.get()
        if genre == "info":
            duree_totale = float(getattr(charge, "duration", 0.0) or 0.0)
            langue_detectee = getattr(charge, "language", langue_detectee)
            continue
        if genre == "fin":
            break

        texte = (charge.text or "").strip()
        if texte:
            morceaux.append(texte)
            if horodatages:
                details.append({
                    "debut": round(charge.start, 2),
                    "fin": round(charge.end, 2),
                    "texte": texte,
                })
        if progression and duree_totale:
            await progression(
                int(charge.end), int(duree_totale),
                f"{int(charge.end // 60)} min sur {int(duree_totale // 60)}",
            )

    await tache

    # Paragraphes plutôt qu'un segment par ligne : les passes suivantes
    # supposent un paragraphe par ligne, et Whisper produit des segments de
    # quelques secondes.
    paragraphes, courant = [], ""
    for morceau in morceaux:
        courant = f"{courant} {morceau}".strip() if courant else morceau
        if len(courant) > 400 and courant.endswith((".", "!", "?", "…")):
            paragraphes.append(courant)
            courant = ""
    if courant:
        paragraphes.append(courant)

    return Transcription(
        texte="\n\n".join(paragraphes),
        origine=Origine.TRANSCRIPTION,
        langue=langue_detectee,
        duree_secondes=duree_totale,
        segments=details,
    )
