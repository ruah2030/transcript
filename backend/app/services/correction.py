"""Passes 1 à 4 : marqueurs temporels, typographie, dictionnaires, grammaire.

Portage des scripts `nettoyer_timestamps.py` et `corriger_transcription.py`.
Ces passes sont pures et rapides — pas de modèle, pas de réseau sauf pour
LanguageTool. Elles s'exécutent en ligne, sans passer par un travail.

Le principe des dictionnaires est conservé tel quel, y compris la
distinction entre `regles` (appliquées) et `signalements` (comptés et
rapportés, jamais appliqués, parce que le bon choix dépend de la phrase).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import reglages
from app.core.erreurs import DocumentInvalide

# ------------------------------------------------------- marqueurs temporels

CODE_TEMPS = r"\d{1,2}:\d{2}(?::\d{2})?"
# Le nombre est optionnel : la transcription produit parfois « 0:07 secondes »
# sans répéter la valeur. L'unité, elle, reste obligatoire — sans quoi on
# effacerait les références du type « 3:16 Dieu a tant aimé ».
UNITE = r"\d*\s*(?:heures?|minutes?|secondes?)"
DUREE = rf"{UNITE}(?:\s*(?:,|et)\s*{UNITE})*"
MARQUEUR = re.compile(rf"^\s*{CODE_TEMPS}\s*{DUREE}\s*", re.MULTILINE)
ESPACES = re.compile(r"[ \t\u00a0]+")


def nettoyer_timestamps(texte: str, fusionner: bool = True) -> tuple[str, int]:
    """Retire les marqueurs YouTube. `fusionner` recolle en prose continue.

    Garder la fusion activée : sans elle, la passe de réécriture perd le fil
    d'un bloc à l'autre parce qu'elle reçoit des lignes de sous-titres.
    """
    supprimes = len(MARQUEUR.findall(texte))
    texte = MARQUEUR.sub("", texte)

    lignes = [ESPACES.sub(" ", l).strip() for l in texte.split("\n")]
    lignes = [l for l in lignes if l]

    if not fusionner:
        return "\n".join(lignes), supprimes

    paragraphes, courant = [], ""
    for ligne in lignes:
        courant = f"{courant} {ligne}".strip() if courant else ligne
        if courant.endswith((".", "!", "?", ":", "»", '"')):
            paragraphes.append(courant)
            courant = ""
    if courant:
        paragraphes.append(courant)

    return "\n\n".join(paragraphes), supprimes


# ---------------------------------------------------------- dictionnaires

@dataclass(slots=True)
class Regle:
    categorie: str
    motif: str
    remplacement: str
    regex: bool = True
    casse: bool = False
    note: str = ""
    _compile: re.Pattern | None = field(default=None, repr=False)

    def compiler(self) -> re.Pattern:
        if self._compile is None:
            brut = self.motif if self.regex else rf"\b{re.escape(self.motif)}\b"
            drapeaux = 0 if self.casse else re.IGNORECASE
            self._compile = re.compile(brut, drapeaux)
        return self._compile

    @property
    def substitution(self) -> str:
        """Convertit la notation $1 des JSON en \\1 attendue par Python."""
        return re.sub(r"\$(\d+)", r"\\\1", self.remplacement)


@dataclass(slots=True)
class Dictionnaire:
    nom: str
    regles: list[Regle] = field(default_factory=list)
    signalements: list[Regle] = field(default_factory=list)


def _lire_regles(brut: list[dict]) -> list[Regle]:
    return [
        Regle(
            categorie=r.get("categorie", "Divers"),
            motif=r["motif"],
            remplacement=r.get("remplacement", ""),
            regex=r.get("regex", True),
            casse=r.get("casse", False),
            note=r.get("note", ""),
        )
        for r in brut
    ]


def charger_dictionnaire(chemin: Path) -> Dictionnaire:
    if not chemin.is_file():
        raise DocumentInvalide(f"Dictionnaire introuvable : {chemin.name}")
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    return Dictionnaire(
        nom=donnees.get("nom", chemin.stem),
        regles=_lire_regles(donnees.get("regles", [])),
        signalements=_lire_regles(donnees.get("signalements", [])),
    )


def dictionnaires_disponibles() -> list[dict]:
    dossier = reglages().dossier_ressources
    resultat = []
    for chemin in sorted(dossier.glob("dictionnaire*.json")):
        d = charger_dictionnaire(chemin)
        resultat.append({
            "fichier": chemin.name,
            "nom": d.nom,
            "regles": len(d.regles),
            "signalements": len(d.signalements),
        })
    return resultat


@dataclass(slots=True)
class Rapport:
    """Ce qui a été fait, et ce qui demande un arbitrage humain."""

    applique: dict[str, int] = field(default_factory=dict)
    signale: list[dict] = field(default_factory=list)
    doublons_retires: int = 0
    marqueurs_retires: int = 0
    corrections_grammaire: int = 0

    @property
    def total_applique(self) -> int:
        return sum(self.applique.values())


def appliquer_dictionnaire(texte: str, dico: Dictionnaire, rapport: Rapport) -> str:
    for regle in dico.regles:
        motif = regle.compiler()
        texte, n = motif.subn(regle.substitution, texte)
        if n:
            cle = f"{regle.categorie} — {regle.motif[:40]}"
            rapport.applique[cle] = rapport.applique.get(cle, 0) + n

    for regle in dico.signalements:
        occurrences = len(regle.compiler().findall(texte))
        if occurrences:
            rapport.signale.append({
                "categorie": regle.categorie,
                "motif": regle.motif,
                "occurrences": occurrences,
                "raison": regle.note or "le contexte décide, rien n'a été remplacé",
            })
    return texte


# ------------------------------------------------------------- doublons

def _normaliser(phrase: str) -> str:
    return re.sub(r"[^\w\s]", "", phrase.lower()).strip()


def dedoublonner(texte: str, seuil: int = 40) -> tuple[str, int]:
    """Retire les répétitions consécutives de la reconnaissance vocale."""
    phrases = re.split(r"(?<=[.!?…])\s+", texte)
    gardees: list[str] = []
    retires = 0
    precedente = ""

    for phrase in phrases:
        normalisee = _normaliser(phrase)
        if (len(normalisee) >= seuil and normalisee == precedente):
            retires += 1
            continue
        gardees.append(phrase)
        precedente = normalisee

    return " ".join(gardees), retires


# ------------------------------------------------------------ références

MOTIF_REF = re.compile(
    r"\b([1-3]?\s*[A-ZÉÈÀ][a-zéèêàçîôûï]+)\s+(\d{1,3})\s*"
    r"(?:verset|versets|v\.?)\s*(\d{1,3})"
    r"(?:\s*(?:à|-|au)\s*(\d{1,3}))?",
    re.IGNORECASE,
)


def normaliser_references(texte: str) -> tuple[str, int]:
    """« Jean 3 verset 16 à 17 » devient « Jean 3.16-17 »."""

    def remplacer(m: re.Match) -> str:
        livre = re.sub(r"\s+", " ", m.group(1)).strip()
        base = f"{livre} {m.group(2)}.{m.group(3)}"
        return f"{base}-{m.group(4)}" if m.group(4) else base

    return MOTIF_REF.subn(remplacer, texte)


# ------------------------------------------------------------- grammaire

def _morceaux(texte: str, maxi: int = 7000):
    """LanguageTool refuse les requêtes trop longues : on découpe."""
    paras = texte.split("\n\n")
    bloc = ""
    for para in paras:
        if bloc and len(bloc) + len(para) + 2 > maxi:
            yield bloc
            bloc = para
        else:
            bloc = f"{bloc}\n\n{para}" if bloc else para
    if bloc:
        yield bloc


async def grammaire(texte: str, serveur: str | None = None) -> tuple[str, int]:
    """Passe LanguageTool. Applique uniquement les remplacements sûrs.

    On ignore délibérément les règles de style et de typographie : elles
    entrent en conflit avec la passe typographique, qui est déterministe et
    dépend de la langue d'arrivée.
    """
    url = (serveur or reglages().languagetool_url).rstrip("/") + "/v2/check"
    ignorees = {"TYPOGRAPHY", "STYLE", "REDUNDANCY", "CASING"}
    total = 0
    sortie: list[str] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for bloc in _morceaux(texte):
            reponse = await client.post(
                url, data={"text": bloc, "language": "fr", "enabledOnly": "false"}
            )
            reponse.raise_for_status()
            matches = reponse.json().get("matches", [])

            # De la fin vers le début : les décalages restent valides.
            corrige = bloc
            for m in sorted(matches, key=lambda x: -x["offset"]):
                if m.get("rule", {}).get("category", {}).get("id") in ignorees:
                    continue
                remplacements = m.get("replacements", [])
                if len(remplacements) != 1:
                    continue   # ambigu : on laisse à l'humain
                debut, longueur = m["offset"], m["length"]
                corrige = (
                    corrige[:debut]
                    + remplacements[0]["value"]
                    + corrige[debut + longueur:]
                )
                total += 1
            sortie.append(corrige)

    return "\n\n".join(sortie), total
