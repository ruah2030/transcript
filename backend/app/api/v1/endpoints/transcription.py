"""Passe 0 — obtenir le texte d'une vidéo ou d'un fichier audio.

Deux entrées : `/source/inspecter` renseigne sans rien télécharger, pour
décider en connaissance de cause ; `/travaux/transcription` fait le travail.

Le service tente toujours les sous-titres avant Whisper. Sur une vidéo qui
en a, on passe de vingt minutes de calcul à deux secondes de téléchargement.
"""

from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.core.config import reglages
from app.infra.travaux import gestionnaire
from app.schemas.atelier import (
    DemandeSource, DemandeTranscription, PisteLue, ReponseSource,
    ReponseTranscription, TravailOuvert,
)
from app.services.transcription import sources, timedtext, whisper
from app.services.transcription.base import VITESSE_MODELES, Media, Origine

routeur = APIRouter(tags=["transcription"])


@routeur.get("/transcription/modeles")
async def modeles_transcription() -> dict:
    """État de la passe 0 : modèles Whisper et fraîcheur de yt-dlp.

    La version de yt-dlp est affichée parce qu'elle est la première cause
    de panne : YouTube change son API régulièrement, et seules les versions
    récentes suivent.
    """
    import shutil

    etat = await whisper.etat()
    version_ytdlp = await sources.version()
    chemin = shutil.which("yt-dlp") or ""
    systeme = chemin.startswith(("/usr/bin", "/usr/local/bin", "/snap"))

    return {
        "modeles": whisper.modeles_disponibles(),
        "disponible": etat.disponible,
        "detail": etat.detail,
        "remede": etat.remede,
        "en_cache": etat.paires,
        "ytdlp": {
            "version": version_ytdlp,
            "chemin": chemin,
            "installe_par_le_systeme": systeme,
            "avertissement": (
                "yt-dlp vient d'un paquet système, souvent très en retard et "
                "incapable de se mettre à jour seul. Préfère celui du venv : "
                "sudo apt remove yt-dlp puis "
                "python -m pip install -U --pre yt-dlp"
            ) if systeme else None,
        },
    }


@routeur.get("/transcription/config")
async def config_effective() -> dict:
    """Ce que le service passe réellement à yt-dlp.

    À consulter en premier quand un réglage semble sans effet : uvicorn
    --reload ne surveille que les fichiers Python, donc une modification de
    .env n'est prise en compte qu'après un arrêt complet du serveur.
    """
    return {
        "yt_dlp": await sources.version(),
        "timedtext": dict(zip(
            ("disponible", "detail"), await timedtext.disponible()
        )),
        **sources.options_effectives(),
    }


@routeur.post("/source/inspecter", response_model=ReponseSource)
async def inspecter(demande: DemandeSource) -> ReponseSource:
    """Titre, durée et sous-titres disponibles. Aucun téléchargement.

    C'est ce qui permet d'annoncer « sous-titres français disponibles »
    plutôt que d'engager une transcription dont on n'avait pas besoin.
    """
    # timedtext d'abord : plus léger, et surtout indépendant de l'API du
    # lecteur que YouTube protège le plus. Quand yt-dlp est bloqué, cette
    # voie répond souvent quand même.
    directes = await timedtext.pistes(demande.url)

    try:
        media = await sources.inspecter(demande.url)
    except Exception:                                       # noqa: BLE001
        if not directes:
            raise
        # yt-dlp refusé mais les sous-titres restent lisibles : on répond
        # avec ce qu'on a plutôt que d'échouer.
        media = Media(
            titre="(titre indisponible)", duree_secondes=0.0,
            url=demande.url, pistes=directes,
        )

    for piste in directes:
        if not any(p.langue == piste.langue for p in media.pistes):
            media.pistes.append(piste)

    humaines = [p.langue for p in media.pistes if not p.automatique]
    autos = [p.langue for p in media.pistes if p.automatique]

    if humaines:
        voie, detail = "sous_titres_humains", (
            f"Sous-titres rédigés disponibles ({', '.join(humaines[:6])}). "
            "Récupération quasi instantanée, ponctuation conservée."
        )
    elif autos:
        voie, detail = "sous_titres_auto", (
            f"Sous-titres automatiques disponibles ({', '.join(autos[:6])}). "
            "Rapides, mais sans ponctuation fiable — la passe de nettoyage "
            "puis celle de correction sont indispensables ensuite."
        )
    else:
        voie, detail = "transcription", (
            "Aucun sous-titre. Il faudra extraire l'audio et le transcrire."
        )

    return ReponseSource(
        titre=media.titre, chaine=media.chaine,
        duree_secondes=media.duree_secondes, url=media.url,
        pistes=[PisteLue(langue=p.langue, automatique=p.automatique)
                for p in media.pistes],
        voie_prevue=voie, detail=detail,
        estimations={
            nom: round(whisper.duree_estimee(media.duree_secondes, nom), 1)
            for nom in VITESSE_MODELES
        },
    )


def _reponse(t) -> dict:
    return {
        "texte": t.texte, "origine": str(t.origine), "langue": t.langue,
        "titre": t.titre, "duree_secondes": t.duree_secondes,
        "mots": len(t.texte.split()), "segments": t.segments,
    }


@routeur.post("/travaux/transcription", response_model=TravailOuvert, status_code=202)
async def ouvrir(demande: DemandeTranscription, requete: Request) -> TravailOuvert:
    """Récupère le texte d'une vidéo. Sous-titres d'abord, Whisper sinon."""
    if not demande.url.strip():
        from app.core.erreurs import DocumentInvalide
        raise DocumentInvalide("Aucune adresse fournie.")

    directes = await timedtext.pistes(demande.url)
    try:
        media = await sources.inspecter(demande.url)
    except Exception:                                       # noqa: BLE001
        if not directes:
            raise
        media = Media(
            titre="(titre indisponible)", duree_secondes=0.0,
            url=demande.url, pistes=directes,
        )

    # Total à zéro : la recherche de sous-titres ne rapporte pas de
    # progression mesurable, elle enchaîne des tentatives. Whisper fixera
    # son propre total en secondes d'audio s'il entre en jeu. Un total nul
    # dit à l'interface d'afficher une attente indéterminée plutôt qu'une
    # barre figée à 0 %, ce qui donnait l'impression d'un blocage.
    travail = gestionnaire.ouvrir("transcription", total=0)

    async def besogne(t):
        avancer = gestionnaire.rappel(t)

        if not demande.forcer_audio:
            # 1. timedtext — chemin le plus léger et le moins filtré.
            await avancer(0, 0, "recherche des sous-titres")
            trouve = await timedtext.recuperer(demande.url, demande.langue, media)
            if trouve is not None:
                await avancer(1, 1, "sous-titres récupérés")
                return _reponse(trouve)

            # 2. yt-dlp — couvre les plateformes autres que YouTube.
            await avancer(0, 0, "sous-titres via yt-dlp")
            trouve = await sources.recuperer_sous_titres(
                demande.url, demande.langue, media
            )
            if trouve is not None:
                await avancer(1, 1, "sous-titres récupérés")
                return _reponse(trouve)

        await avancer(0, 0, "extraction de l'audio")

        dossier = reglages().dossier_cache / "audio"
        audio = await sources.extraire_audio(
            demande.url, dossier / f"{travail.identifiant}.wav"
        )
        try:
            resultat = await whisper.transcrire(
                audio, demande.modele, demande.langue or None,
                demande.horodatages, avancer,
            )
            resultat.titre = media.titre
            return _reponse(resultat)
        finally:
            audio.unlink(missing_ok=True)   # l'audio brut ne sert plus

    gestionnaire.lancer(travail, besogne)
    base = str(requete.base_url).rstrip("/")
    return TravailOuvert(
        identifiant=travail.identifiant, genre=travail.genre,
        etat=str(travail.etat),
        flux=f"{base}/api/v1/travaux/{travail.identifiant}/flux",
    )


@routeur.post("/travaux/transcription-fichier", response_model=TravailOuvert,
              status_code=202)
async def ouvrir_fichier(
    requete: Request,
    fichier: UploadFile = File(...),
    langue: str = Form("fr"),
    modele: str = Form("small"),
    horodatages: bool = Form(False),
) -> TravailOuvert:
    """Transcrit un fichier audio ou vidéo déposé.

    Utile quand la source n'est pas une URL publique : un enregistrement
    personnel, ou une vidéo déjà téléchargée.
    """
    dossier = reglages().dossier_cache / "audio"
    dossier.mkdir(parents=True, exist_ok=True)
    travail = gestionnaire.ouvrir("transcription-fichier", total=1)

    suffixe = Path(fichier.filename or "media").suffix or ".bin"
    chemin = dossier / f"{travail.identifiant}{suffixe}"
    chemin.write_bytes(await fichier.read())

    async def besogne(t):
        try:
            resultat = await whisper.transcrire(
                chemin, modele, langue or None, horodatages,
                gestionnaire.rappel(t),
            )
            resultat.titre = fichier.filename or ""
            return _reponse(resultat)
        finally:
            chemin.unlink(missing_ok=True)

    gestionnaire.lancer(travail, besogne)
    base = str(requete.base_url).rstrip("/")
    return TravailOuvert(
        identifiant=travail.identifiant, genre=travail.genre,
        etat=str(travail.etat),
        flux=f"{base}/api/v1/travaux/{travail.identifiant}/flux",
    )
