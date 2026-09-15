"""Configuration de l'atelier. Tout se pilote par variables d'environnement."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE = Path(__file__).resolve().parents[2]


class Reglages(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATELIER_", env_file=".env", extra="ignore"
    )

    # ---- service
    titre: str = "Atelier de transcription"
    version: str = "5.0.0"
    origines_autorisees: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ---- chemins
    dossier_ressources: Path = RACINE / "ressources"
    dossier_cache: Path = RACINE / ".cache"
    dossier_modeles: Path = RACINE / "modeles"

    # ---- moteurs NMT (CTranslate2)
    # Un dossier par paire : modeles/opus-en-fr-ct2/, modeles/opus-fr-en-ct2/...
    ct2_calcul: str = "int8"
    ct2_threads: int = 0          # 0 = tous les coeurs physiques
    ct2_lots_tokens: int = 4096
    #: Recherche en faisceau. 1 = glouton, le plus rapide et nettement le
    #: plus mauvais. 4 est le réglage usuel en traduction automatique : il
    #: coûte deux à trois fois plus de temps et change beaucoup le résultat.
    #: Sur un document qu'on garde, ce coût est le bon.
    ct2_faisceau: int = 4
    #: Favorise les sorties légèrement plus longues. En dessous de 1, le
    #: décodeur tronque les phrases complexes ; l'anglais vers le français
    #: allonge naturellement de 15 à 20 %.
    ct2_penalite_longueur: float = 1.1
    #: Freine les boucles de répétition, défaut typique des modèles NMT
    #: quand ils décrochent sur une phrase difficile.
    ct2_penalite_repetition: float = 1.05
    #: Interdit de répéter un n-gramme de cette taille. 0 = désactivé.
    ct2_sans_repetition: int = 4
    #: Recopie le mot source quand le modèle ne sait pas traduire. Rend des
    #: mots anglais dans le texte français : mieux vaut un trou visible
    #: qu'un anglicisme qui passe inaperçu à la relecture.
    ct2_recopier_inconnus: bool = False

    # ---- moteur LLM
    llm_url: str = "http://localhost:11434"
    llm_api: str = "ollama"       # ollama | openai
    #: Modèle pour la traduction (langue A -> langue B). Un modèle
    #: spécialisé traduction excelle ici.
    llm_modele: str = "hy-mt-1.8b"
    #: Modèle pour les tâches monolingues — réparation, révision,
    #: vérification de fidélité. Prends un GÉNÉRALISTE : un modèle
    #: spécialisé traduction suit mal une consigne de réécriture dans une
    #: seule langue, et ne produit pas le JSON attendu par la vérification.
    #: Vide = on réutilise `llm_modele`.
    llm_modele_reecriture: str = ""
    llm_temperature: float = 0.3
    llm_contexte: int = 4096
    llm_delai: int = 600

    # ---- transcription audio (faster-whisper)
    whisper_modele: str = "small"
    whisper_calcul: str = "int8"
    #: Vide = détection automatique. La préciser est plus sûr : sur un
    #: français parsemé de citations anglaises, la détection bascule parfois
    #: d'une langue à l'autre en cours de route.
    whisper_langue: str = ""

    # ---- yt-dlp
    #: Navigateur d'où lire les cookies quand YouTube exige une
    #: authentification : firefox, chrome, chromium, brave, edge. Vide = aucun.
    #: Accepte aussi un profil explicite : « firefox:/chemin/du/profil ».
    #: Nécessaire quand le navigateur est installé en snap ou en flatpak,
    #: qui rangent le profil ailleurs que là où yt-dlp le cherche.
    ytdlp_cookies: str = ""
    #: Chemin d'un fichier cookies.txt au format Netscape. Plus fiable que
    #: la lecture directe du navigateur : pas de trousseau à déverrouiller,
    #: pas de base verrouillée par un navigateur ouvert. Prioritaire.
    ytdlp_cookies_fichier: str = ""
    #: Client à imiter. Utile comme contournement quand un client est bloqué
    #: mais pas un autre : tv, web_safari, android, ios, mweb.
    ytdlp_client: str = ""
    #: Options supplémentaires, séparées par des espaces.
    ytdlp_options: str = ""

    # ---- LanguageTool
    languagetool_url: str = "http://localhost:8081"

    # ---- travaux
    travaux_simultanes: int = 1   # sans GPU, un seul a la fois
    retention_travaux_h: int = 24

    def __init__(self, **donnees):
        super().__init__(**donnees)
        self.dossier_cache.mkdir(parents=True, exist_ok=True)
        self.dossier_modeles.mkdir(parents=True, exist_ok=True)


@lru_cache
def reglages() -> Reglages:
    return Reglages()
