"""Accès aux vidéos en ligne, via yt-dlp.

yt-dlp est appelé en sous-processus plutôt qu'importé. Trois raisons :

  - il se met à jour très souvent, parce que les plateformes changent leur
    format ; garder le couplage lâche évite qu'une montée de version casse
    le service ;
  - le téléchargement d'une longue vidéo bloquerait la boucle asyncio ;
  - un binaire qui plante ne tue pas le processus du service.

Le module ne fait aucune supposition sur la plateforme : yt-dlp en gère
plusieurs centaines, et l'inspection dira si l'URL passée est traitable.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from app.core.erreurs import ErreurAtelier, MoteurIndisponible
from app.services.transcription.base import Media, Origine, PisteSousTitres, Transcription

DELAI_INSPECTION = 60
DELAI_TELECHARGEMENT = 3600


class SourceIndisponible(ErreurAtelier):
    code_http = 502
    code = "source_indisponible"


def _binaire() -> str:
    chemin = shutil.which("yt-dlp")
    if chemin is None:
        raise MoteurIndisponible(
            "yt-dlp n'est pas installé.",
            "pip install yt-dlp\n\n"
            "L'extraction audio demande aussi ffmpeg :\n"
            "  sudo apt install ffmpeg",
        )
    return chemin


def _ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None


#: Signatures d'une casse due à un yt-dlp périmé. YouTube change son API
#: régulièrement ; yt-dlp corrige en continu, mais seulement sur les
#: versions récentes. Une borne basse dans les dépendances ne protège de
#: rien : ce qui compte est la fraîcheur, pas un minimum.
SYMPTOMES_PERIME = (
    "precondition check failed",
    "http error 400",
    "unable to extract",
    "player response",
    "nsig extraction failed",
    "failed to extract any player response",
)
SYMPTOMES_BLOCAGE = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
)


async def version() -> str:
    """Version de yt-dlp, ou une chaîne d'erreur. Ne lève jamais."""
    try:
        code, sortie, _ = await _lancer(["--version"], 20, brut=True)
        return sortie.decode("utf-8", "replace").strip() if code == 0 else "?"
    except Exception:                                       # noqa: BLE001
        return "absent"


def _chemin_binaire() -> str:
    return shutil.which("yt-dlp") or ""


def diagnostiquer_echec(erreur: str) -> str | None:
    """Traduit une sortie d'erreur brute en marche à suivre.

    Sans ça, l'utilisateur reçoit une pile de warnings YouTube qui ne dit
    nulle part que la cause est une version périmée.
    """
    bas = erreur.lower()

    if any(m in bas for m in SYMPTOMES_BLOCAGE):
        return (
            "YouTube demande une authentification pour cette vidéo.\n"
            "Trois remèdes, du moins engageant au plus. Redémarre le service "
            "après chaque modification de .env.\n"
            "\n"
            "1) Changer de client — aucun compte nécessaire.\n"
            "   ATELIER_YTDLP_CLIENT=tv\n"
            "   Puis, si besoin : mweb, android, web_safari.\n"
            "\n"
            "2) Un fichier de cookies exporté — le plus fiable.\n"
            "   Exporte cookies.txt depuis ton navigateur (extension au "
            "format Netscape), puis :\n"
            "   ATELIER_YTDLP_COOKIES_FICHIER=~/cookies.txt\n"
            "\n"
            "3) Les cookies lus directement dans le navigateur.\n"
            "   ATELIER_YTDLP_COOKIES=firefox\n"
            "   Si le navigateur est en snap ou flatpak, donne le profil :\n"
            "   ATELIER_YTDLP_COOKIES=firefox:~/snap/firefox/common/"
            ".mozilla/firefox/xxxx.default-release\n"
            "\n"
            "Utiliser ton compte principal pour du téléchargement "
            "automatisé peut le faire signaler par YouTube."
        )

    if any(m in bas for m in SYMPTOMES_PERIME):
        chemin = _chemin_binaire()
        lignes = [
            "yt-dlp est probablement périmé. YouTube change son API "
            "régulièrement et seules les versions récentes suivent.",
            "",
            "  python -m pip install -U --pre yt-dlp",
            "",
        ]
        if chemin.startswith(("/usr/bin", "/usr/local/bin", "/snap")):
            lignes += [
                f"Attention : le binaire utilisé est {chemin}, donc une "
                "version système et non celle du venv.",
                "Les paquets système sont souvent très en retard et "
                "refusent de se mettre à jour seuls.",
                "",
                "  sudo apt remove yt-dlp",
                "",
                "puis réinstalle-le dans le venv avec la commande ci-dessus.",
            ]
        return "\n".join(lignes)

    return None


def _options_communes() -> list[str]:
    """Options ajoutées à tout appel réseau.

    `player_client` et les cookies sont les deux leviers de contournement
    quand YouTube durcit ses contrôles. Les rendre configurables évite
    d'avoir à modifier le code à chaque changement de leur côté.
    """
    from app.core.config import reglages

    cfg = reglages()
    options: list[str] = []
    # Le fichier prime : il ne dépend ni du trousseau système ni de l'état
    # du navigateur, et fonctionne donc dans un service qui tourne en fond.
    if cfg.ytdlp_cookies_fichier:
        _champ_confondu(cfg.ytdlp_cookies_fichier, "fichier")
        chemin = Path(cfg.ytdlp_cookies_fichier).expanduser()
        if not chemin.is_file():
            raise MoteurIndisponible(
                f"Fichier de cookies introuvable : {chemin}",
                "Corrige ATELIER_YTDLP_COOKIES_FICHIER dans .env, ou vide-le "
                "pour utiliser ATELIER_YTDLP_COOKIES à la place.",
            )
        options += ["--cookies", str(chemin)]
    elif cfg.ytdlp_cookies:
        options += ["--cookies-from-browser", _resoudre_navigateur(cfg.ytdlp_cookies)]
    if cfg.ytdlp_client:
        _champ_confondu(cfg.ytdlp_client, "client")
        _valider_client(cfg.ytdlp_client)
        options += ["--extractor-args", f"youtube:player_client={cfg.ytdlp_client}"]
    if cfg.ytdlp_options:
        options += cfg.ytdlp_options.split()
    return options


#: Espaces réservés qu'on laisse parfois tels quels en recopiant une doc.
#: Les détecter évite un échec silencieux : yt-dlp accepte un profil
#: inexistant, retombe sur un accès anonyme, et l'erreur qui remonte parle
#: d'authentification sans jamais mentionner le chemin fautif.
GABARITS = ("xxxx", "xxx", "abcd1234", "votreprofil", "monprofil")

#: Clients YouTube connus de yt-dlp. Sert à détecter une valeur posée dans
#: le mauvais champ : trois réglages aux noms voisins se confondent vite.
CLIENTS = frozenset({
    "web", "web_safari", "web_embedded", "web_music", "web_creator",
    "android", "android_vr", "ios", "mweb", "tv", "tv_simply", "tv_embedded",
    "default", "all",
})

#: Navigateurs acceptés par --cookies-from-browser.
NAVIGATEURS = frozenset({
    "brave", "chrome", "chromium", "edge", "firefox", "opera",
    "safari", "vivaldi", "whale",
})


#: Marqueurs d'un dossier de profil de navigateur. Un chemin qui en contient
#: un n'est jamais un cookies.txt.
MARQUEURS_PROFIL = (
    ".mozilla/firefox", "firefox/profiles", ".default",
    "google-chrome", "chromium", "bravesoftware", "microsoft-edge",
)


def _ressemble_a_un_profil(valeur: str) -> bool:
    from pathlib import Path as _P

    bas = valeur.replace("\\", "/").lower()
    if any(m in bas for m in MARQUEURS_PROFIL):
        return True
    return _P(valeur).expanduser().is_dir()


def _valider_client(valeur: str) -> None:
    """Refuse un nom de client inconnu.

    Sans ce contrôle, une valeur fantaisiste part telle quelle vers yt-dlp,
    qui l'ignore ou échoue de façon obscure — et l'utilisateur croit avoir
    essayé un client qu'il n'a jamais essayé.
    """
    v = valeur.strip().lower()
    if v in CLIENTS:
        return
    raise MoteurIndisponible(
        f"« {valeur} » n'est pas un client YouTube.",
        "ATELIER_YTDLP_CLIENT attend une seule valeur parmi :\n"
        f"  {', '.join(sorted(CLIENTS))}\n\n"
        "Laisse ce champ VIDE pour que le service essaie automatiquement "
        "tv, mweb, android, web_safari puis ios.",
    )


def _champ_confondu(valeur: str, attendu: str) -> None:
    """Signale une valeur posée dans le mauvais réglage.

    Sans ce contrôle, « tv » dans le champ du fichier de cookies produit
    « Fichier de cookies introuvable : tv » — techniquement exact, mais qui
    laisse chercher un fichier au lieu de corriger le champ.
    """
    v = valeur.strip().lower()
    champs = {
        "fichier": "ATELIER_YTDLP_COOKIES_FICHIER",
        "navigateur": "ATELIER_YTDLP_COOKIES",
        "client": "ATELIER_YTDLP_CLIENT",
    }
    trouve = None
    if v in CLIENTS:
        trouve = "client"
    elif v.split(":")[0].split("+")[0] in NAVIGATEURS:
        trouve = "navigateur"
    elif attendu == "fichier" and _ressemble_a_un_profil(v):
        # Un dossier de profil dans le champ « fichier ». Le message
        # « fichier introuvable » serait exact mais trompeur : il ferait
        # chercher un fichier absent au lieu de corriger le champ.
        raise MoteurIndisponible(
            "Ce chemin est un profil de navigateur, pas un fichier cookies.txt.",
            f"ATELIER_YTDLP_COOKIES_FICHIER vaut « {valeur} », qui désigne un "
            "dossier de profil.\n\n"
            "Mets-le plutôt dans ATELIER_YTDLP_COOKIES, préfixé du "
            "navigateur, et vide ATELIER_YTDLP_COOKIES_FICHIER :\n\n"
            f"  ATELIER_YTDLP_COOKIES=firefox:{valeur}\n"
            "  ATELIER_YTDLP_COOKIES_FICHIER=\n\n"
            "Le champ FICHIER attend un cookies.txt au format Netscape, "
            "exporté depuis une extension du navigateur.",
        )

    if trouve and trouve != attendu:
        raise MoteurIndisponible(
            f"« {valeur} » est dans le mauvais réglage.",
            f"C'est une valeur de {trouve}, mais elle se trouve dans "
            f"{champs[attendu]}.\n\n"
            f"Déplace-la vers {champs[trouve]} et vide "
            f"{champs[attendu]}, puis redémarre le service.",
        )


def _resoudre_navigateur(valeur: str) -> str:
    """Valide « navigateur » ou « navigateur:/chemin/du/profil ».

    Le chemin est développé ici parce que yt-dlp est lancé sans shell : un
    « ~ » y resterait littéral, et yt-dlp chercherait un dossier réellement
    nommé « ~ ».
    """
    _champ_confondu(valeur, "navigateur")
    if ":" not in valeur:
        return valeur.strip()

    navigateur, _, profil = valeur.partition(":")
    navigateur, profil = navigateur.strip(), profil.strip()

    # Chrome et dérivés désignent leur profil par un NOM (« Default »,
    # « Profile 1 »), pas par un chemin. Firefox par un chemin. On ne
    # valide donc l'existence que quand la valeur ressemble à un chemin.
    # Le navigateur peut aussi porter un suffixe de trousseau, comme
    # « chrome+gnomekeyring » — yt-dlp l'accepte, notre contrôle doit aussi.
    if not ("/" in profil or profil.startswith("~")):
        return f"{navigateur}:{profil}"

    if any(g in profil.lower() for g in GABARITS):
        raise MoteurIndisponible(
            "Le chemin du profil Firefox est resté un espace réservé.",
            f"ATELIER_YTDLP_COOKIES vaut « {valeur} ».\n\n"
            "« xxxx » n'est pas un nom réel : Firefox génère un identifiant "
            "aléatoire. Trouve le tien :\n\n"
            "  ls -d ~/snap/firefox/common/.mozilla/firefox/*.default* "
            "~/.mozilla/firefox/*.default* 2>/dev/null\n\n"
            "puis recopie le nom complet du dossier obtenu.",
        )

    chemin = Path(profil).expanduser()
    if not chemin.is_dir():
        raise MoteurIndisponible(
            f"Profil {navigateur} introuvable : {chemin}",
            "Vérifie le chemin :\n\n"
            "  ls -d ~/snap/firefox/common/.mozilla/firefox/*.default* "
            "~/.mozilla/firefox/*.default* 2>/dev/null\n\n"
            "Sans chemin, yt-dlp cherche seul : ATELIER_YTDLP_COOKIES=firefox",
        )
    return f"{navigateur}:{chemin}"


async def _lancer(args: list[str], delai: int, brut: bool = False) -> tuple[int, bytes, bytes]:
    if not brut:
        args = [*_options_communes(), *args]
    processus = await asyncio.create_subprocess_exec(
        _binaire(), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        sortie, erreur = await asyncio.wait_for(processus.communicate(), delai)
    except asyncio.TimeoutError:
        processus.kill()
        raise SourceIndisponible(
            f"yt-dlp n'a pas répondu en {delai} s.",
            "Vidéo très longue ou connexion lente. Réessaie, ou télécharge "
            "l'audio à part et importe le fichier.",
        ) from None
    return processus.returncode or 0, sortie, erreur


#: Ordre d'essai quand aucun client n'est imposé. YouTube ne durcit pas ses
#: contrôles de la même façon sur tous ses clients, et celui qui passe change
#: au fil de leurs déploiements. Essayer plusieurs fois coûte quelques
#: secondes et évite un échec là où un autre client aurait suffi.
CLIENTS_DE_REPLI = ("tv", "mweb", "android", "web_safari", "ios")


def options_effectives() -> dict:
    """Ce qui sera réellement passé à yt-dlp. Pour le diagnostic.

    Sans ça, impossible de distinguer « le réglage ne marche pas » de
    « le réglage n'a jamais été chargé » — le second cas arrive dès qu'on
    modifie .env sans redémarrer, puisque uvicorn --reload ne surveille
    que les fichiers Python.
    """
    from app.core.config import reglages

    cfg = reglages()
    try:
        options = _options_communes()
        erreur = None
    except Exception as e:                                  # noqa: BLE001
        options, erreur = [], str(e)

    return {
        "client": cfg.ytdlp_client or "(aucun — repli automatique)",
        "cookies_fichier": cfg.ytdlp_cookies_fichier or "(vide)",
        "cookies_navigateur": cfg.ytdlp_cookies or "(vide)",
        "options_supplementaires": cfg.ytdlp_options or "(vide)",
        "arguments_passes": options,
        "erreur_de_configuration": erreur,
        "clients_de_repli": list(CLIENTS_DE_REPLI),
    }


async def inspecter(url: str) -> Media:
    """Métadonnées et pistes de sous-titres, sans rien télécharger.

    Rapide, et c'est ce qui permet d'annoncer à l'utilisateur « sous-titres
    français disponibles, deux secondes » plutôt que de le lancer dans une
    transcription de vingt minutes dont il n'avait pas besoin.
    """
    from app.core.config import reglages

    base = ["--dump-json", "--no-playlist", "--skip-download", url]

    # Si l'utilisateur a imposé un client, on le respecte sans insister.
    # Sinon on essaie la liste de repli avant d'abandonner.
    if reglages().ytdlp_client:
        tentatives: list[list[str]] = [base]
    else:
        tentatives = [
            ["--extractor-args", f"youtube:player_client={c}", *base]
            for c in CLIENTS_DE_REPLI
        ]

    dernier = b""
    for args in tentatives:
        code, sortie, erreur = await _lancer(args, DELAI_INSPECTION)
        if code == 0:
            break
        dernier = erreur
    else:
        code = 1

    if code != 0:
        texte = dernier.decode("utf-8", "replace").strip()
        remede = diagnostiquer_echec(texte)
        if not reglages().ytdlp_client:
            essayes = ", ".join(CLIENTS_DE_REPLI)
            remede = (
                f"Clients essayés sans succès : {essayes}.\n\n"
                + (remede or texte[:300])
            )
        raise SourceIndisponible(
            "Impossible de lire cette adresse.",
            remede if remede else (texte[:400] or "yt-dlp a échoué."),
        )

    try:
        donnees = json.loads(sortie.decode("utf-8", "replace").splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise SourceIndisponible("Réponse de yt-dlp illisible.", str(e)) from e

    pistes: list[PisteSousTitres] = []
    for langue in (donnees.get("subtitles") or {}):
        pistes.append(PisteSousTitres(langue=langue, automatique=False))
    for langue in (donnees.get("automatic_captions") or {}):
        if not any(p.langue == langue for p in pistes):
            pistes.append(PisteSousTitres(langue=langue, automatique=True))

    return Media(
        titre=donnees.get("title") or "Sans titre",
        duree_secondes=float(donnees.get("duration") or 0),
        url=donnees.get("webpage_url") or url,
        chaine=donnees.get("uploader") or donnees.get("channel") or "",
        pistes=sorted(pistes, key=lambda p: (p.automatique, p.langue)),
    )


# ------------------------------------------------------------- sous-titres

HORODATAGE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
BALISE = re.compile(r"<[^>]+>")
ENTETE_VTT = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE\b|STYLE\b|REGION\b)")


def depouiller_vtt(brut: str) -> str:
    """Extrait le texte d'un VTT ou d'un SRT.

    Les sous-titres automatiques répètent la fin du bloc précédent au début
    du suivant, pour donner l'illusion du défilement. Sans déduplication, le
    texte sort avec chaque phrase écrite deux fois.
    """
    lignes: list[str] = []
    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if (not ligne or ligne.isdigit()
                or HORODATAGE.match(ligne) or ENTETE_VTT.match(ligne)):
            continue
        ligne = BALISE.sub("", ligne).strip()
        if ligne and (not lignes or lignes[-1] != ligne):
            lignes.append(ligne)

    # Recolle en paragraphes sur la ponctuation forte, comme la passe de
    # nettoyage le fera de toute façon.
    texte = " ".join(lignes)
    texte = re.sub(r"\s+", " ", texte)
    paragraphes, courant = [], ""
    for morceau in re.split(r"(?<=[.!?…])\s+", texte):
        courant = f"{courant} {morceau}".strip() if courant else morceau
        if len(courant) > 400:
            paragraphes.append(courant)
            courant = ""
    if courant:
        paragraphes.append(courant)
    return "\n\n".join(paragraphes)


async def recuperer_sous_titres(
    url: str, langue: str, media: Media | None = None, dossier: Path | None = None,
) -> Transcription | None:
    """Télécharge la meilleure piste pour cette langue. None si aucune."""
    import tempfile

    media = media or await inspecter(url)
    piste = media.piste_pour(langue)
    if piste is None:
        return None

    with tempfile.TemporaryDirectory(dir=dossier) as tmp:
        gabarit = str(Path(tmp) / "st")
        drapeau = "--write-auto-subs" if piste.automatique else "--write-subs"
        code, _, erreur = await _lancer(
            [
                "--skip-download", drapeau,
                "--sub-langs", piste.langue,
                "--sub-format", "vtt/srt/best",
                "--convert-subs", "vtt",
                "--no-playlist", "-o", gabarit, url,
            ],
            DELAI_INSPECTION * 3,
        )
        fichiers = sorted(Path(tmp).glob("*.vtt")) or sorted(Path(tmp).glob("*.srt"))
        if code != 0 or not fichiers:
            raise SourceIndisponible(
                f"Sous-titres {piste.langue} annoncés mais non récupérables.",
                erreur.decode("utf-8", "replace").strip()[:300]
                or "Relance en demandant une transcription audio.",
            )
        brut = fichiers[0].read_text(encoding="utf-8", errors="replace")

    return Transcription(
        texte=depouiller_vtt(brut),
        origine=(Origine.SOUS_TITRES_AUTO if piste.automatique
                 else Origine.SOUS_TITRES_HUMAINS),
        langue=piste.langue,
        duree_secondes=media.duree_secondes,
        titre=media.titre,
    )


# ------------------------------------------------------------------- audio

async def extraire_audio(url: str, destination: Path) -> Path:
    """Télécharge la piste audio seule, en 16 kHz mono — le format attendu
    par Whisper. Éviter la vidéo divise le volume téléchargé par dix."""
    if not _ffmpeg_present():
        raise MoteurIndisponible(
            "ffmpeg est absent.",
            "sudo apt install ffmpeg\n\n"
            "Il sert à extraire et rééchantillonner la piste audio.",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    gabarit = str(destination.with_suffix(""))
    code, _, erreur = await _lancer(
        [
            "-f", "bestaudio/best",
            "--extract-audio", "--audio-format", "wav",
            "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
            "--no-playlist", "-o", f"{gabarit}.%(ext)s", url,
        ],
        DELAI_TELECHARGEMENT,
    )
    produit = destination.with_suffix(".wav")
    if code != 0 or not produit.is_file():
        texte = erreur.decode("utf-8", "replace").strip()
        remede = diagnostiquer_echec(texte)
        raise SourceIndisponible(
            "Extraction audio impossible.",
            remede if remede else (texte[:400] or "yt-dlp a échoué."),
        )
    return produit
