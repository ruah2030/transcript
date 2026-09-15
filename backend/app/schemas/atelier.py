"""Contrat d'API. Ces modèles sont la seule chose que le front doit connaître."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.traduction.base import Capacite, Registre


# ------------------------------------------------------------ nettoyage

class DemandeNettoyage(BaseModel):
    texte: str
    fusionner_paragraphes: bool = Field(
        True,
        description="Recolle les segments de sous-titres en prose continue. "
                    "À garder activé : sinon la passe de réécriture perd le fil.",
    )


class ReponseNettoyage(BaseModel):
    texte: str
    marqueurs_retires: int


# ----------------------------------------------------------- correction

class DemandeCorrection(BaseModel):
    texte: str
    dictionnaires: list[str] = ["dictionnaire.json", "dictionnaire-calques.json"]
    typographie: bool = True
    dedoublonner: bool = True
    references: bool = True
    grammaire: bool = False   # demande un serveur LanguageTool


class Signalement(BaseModel):
    categorie: str
    motif: str
    occurrences: int
    raison: str


class ReponseCorrection(BaseModel):
    texte: str
    regles_appliquees: dict[str, int]
    total_applique: int
    signalements: list[Signalement]
    doublons_retires: int
    references_normalisees: int
    corrections_grammaire: int


# ----------------------------------------------------------- traduction

class DemandeTraduction(BaseModel):
    texte: str
    moteur: str = Field("hybride", description="opusmt | argos | llm | hybride")
    source: str = "en"
    cible: str = "fr"
    capacite: Capacite = Capacite.TRADUCTION
    registre: Registre = Registre.COURANT
    glossaire: str | None = "glossaire.json"
    modele: str | None = Field(
        None,
        description="Surcharge le modèle LLM pour cet appel. Sans effet sur "
                    "les moteurs NMT. Vide = celui de la configuration.",
    )


class ReponseTraduction(BaseModel):
    texte: str
    moteur: str
    doutes: list[str] = []
    confiance: float | None = None


# --------------------------------------------------------------- plan

class SectionLue(BaseModel):
    indice: int
    titre: str
    caracteres: int


class Alerte(BaseModel):
    gravite: str   # info | attention
    message: str


class ReponseAnalyse(BaseModel):
    caracteres: int
    mots: int
    paragraphes: int
    sections: list[SectionLue]
    segments: int
    phrases: int
    alertes: list[Alerte]
    estimations: dict[str, float]   # moteur -> secondes


# ------------------------------------------------------------- moteurs

class EtatMoteur(BaseModel):
    nom: str
    libelle: str
    capacites: list[str]
    debit_mots_seconde: float
    disponible: bool
    detail: str
    paires: list[str] = []
    remede: str | None = None


# ------------------------------------------------------------- travaux

class TravailOuvert(BaseModel):
    identifiant: str
    genre: str
    etat: str
    flux: str = Field(description="URL SSE à laquelle s'abonner")


class InstantaneTravail(BaseModel):
    identifiant: str
    genre: str
    etat: str
    faits: int
    total: int
    progression: float
    etiquette: str
    secondes_restantes: float | None = None
    erreur: dict | None = None
    cree_le: str


# ------------------------------------------------------------ glossaire

class TermeGlossaire(BaseModel):
    source: str
    rendu: str
    jamais: str = ""


class Glossaire(BaseModel):
    terminologie: list[TermeGlossaire] = []
    ne_pas_traduire: list[str] = []
    calques_a_bannir: list[str] = []
    consignes_de_style: list[str] = []


# ---------------------------------------------------------- mise en page

class OptionsMiseEnPage(BaseModel):
    titre: str = ""
    auteur: str = ""
    taille: str = Field("a5", description="a5 | a4 | lettre")
    police: str = Field("serif", description="serif | sans")
    corps: float = 11
    interligne: float = 1.5
    sans_toc: bool = False
    sans_lettrine: bool = False


class DemandeMiseEnPage(BaseModel):
    texte: str
    format: str = Field("html", description="html | md")
    options: OptionsMiseEnPage = OptionsMiseEnPage()


class ChapitreDetecte(BaseModel):
    titre: str | None
    exergue: str | None
    paragraphes: int
    intertitres: list[str]
    listes_principes: int


class ReponseStructure(BaseModel):
    chapitres: list[ChapitreDetecte]
    avertissement: str | None = None


class ReponseMiseEnPage(BaseModel):
    contenu: str
    format: str
    chapitres: int


# --------------------------------------------------------- vérification

class DemandeVerification(BaseModel):
    avant: str
    apres: str
    source: str = "fr"
    cible: str = "fr"
    propositions: bool = False


class ConstatSens(BaseModel):
    etiquette: str
    explication: str
    avant: str
    apres: str
    paire: int
    propositions: list[str] = []


class ReponseVerification(BaseModel):
    constats: list[ConstatSens]
    paires_comparees: int
    par_etiquette: dict[str, int]
    markdown: str



# -------------------------------------------------------------- modèles

class ModeleDisponible(BaseModel):
    nom: str
    taille_octets: int | None = None
    parametres: str | None = None


class ReponseModeles(BaseModel):
    disponibles: list[ModeleDisponible]
    actifs: dict[str, str]
    source: str
    detail: str | None = None



# --------------------------------------------------------- transcription

class DemandeSource(BaseModel):
    url: str


class PisteLue(BaseModel):
    langue: str
    automatique: bool


class ReponseSource(BaseModel):
    titre: str
    chaine: str
    duree_secondes: float
    url: str
    pistes: list[PisteLue]
    #: Ce que le service fera si on lance la récupération telle quelle.
    voie_prevue: str
    detail: str
    estimations: dict[str, float]


class DemandeTranscription(BaseModel):
    url: str = ""
    langue: str = Field("fr", description="Langue attendue, ex. fr ou en")
    modele: str = Field("small", description="tiny | base | small | medium | large-v3")
    #: Forcer la transcription audio même si des sous-titres existent.
    forcer_audio: bool = False
    horodatages: bool = False


class ReponseTranscription(BaseModel):
    texte: str
    origine: str
    langue: str
    titre: str = ""
    duree_secondes: float = 0
    mots: int = 0
    segments: list[dict] = []
