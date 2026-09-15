"""Traduction : analyse, exécution courte, travail long.

Trois entrées parce que trois usages qui n'ont pas les mêmes contraintes :

    /analyse      instantané, aucun modèle appelé. Sert à décider avant de
                  s'engager : combien de segments, quelle durée, quels
                  problèmes dans le document.
    /traduction   synchrone. Réservé aux textes courts (un paragraphe, un
                  essai de réglage) — au-delà, le client attend trop.
    /travaux      asynchrone avec suivi SSE. Le vrai chemin pour un livre.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.erreurs import DocumentInvalide
from app.domain import decoupage
from app.infra.travaux import gestionnaire
from app.schemas.atelier import (
    Alerte, DemandeTraduction, ReponseAnalyse, ReponseTraduction, SectionLue,
    TravailOuvert,
)
from app.services import glossaire as service_glossaire
from app.services.traduction.base import Requete
from app.services.traduction.registre import registre

routeur = APIRouter(tags=["traduction"])

#: Au-delà, on refuse le mode synchrone et on oriente vers un travail.
LIMITE_SYNCHRONE = 6_000


def _construire_requete(demande: DemandeTraduction) -> Requete:
    glossaire = (
        service_glossaire.charger(demande.glossaire) if demande.glossaire else None
    )
    return Requete(
        texte=demande.texte,
        source=demande.source,
        cible=demande.cible,
        capacite=demande.capacite,
        registre=demande.registre,
        glossaire=glossaire,
        modele=demande.modele,
    )


@routeur.post("/analyse", response_model=ReponseAnalyse)
async def analyser(demande: DemandeTraduction) -> ReponseAnalyse:
    """Profil du document. Aucun appel de modèle, réponse immédiate.

    Reprend les alertes de `traduire.py --analyser` : ce sont elles qui
    évitent de lancer huit heures de traitement sur un document mal préparé.
    """
    texte = demande.texte
    plan = decoupage.construire_plan(texte)
    phrases = decoupage.decouper_phrases(texte)

    paras = [p for p in texte.split("\n\n") if p.strip()]
    lignes = [l for l in texte.split("\n") if l.strip()]
    mots = len(texte.split())

    alertes: list[Alerte] = []

    if paras and len(paras) < len(lignes) / 4:
        alertes.append(Alerte(
            gravite="attention",
            message="Peu de paragraphes pour beaucoup de lignes : le document "
                    "ressemble à des sous-titres bruts. Passe d'abord par le "
                    "nettoyage avec fusion des paragraphes, sinon le modèle "
                    "perdra le fil d'un bloc à l'autre.",
        ))

    if longs := [p for p in paras if len(p) > 4000]:
        alertes.append(Alerte(
            gravite="attention",
            message=f"{len(longs)} paragraphe(s) de plus de 4000 caractères : "
                    "ils seront traités d'un bloc.",
        ))

    if len(plan.sections) < 2:
        alertes.append(Alerte(
            gravite="info",
            message="Aucune structure reconnue : le document sera traité d'un "
                    "seul tenant, sans réinitialisation du contexte.",
        ))

    import re
    if re.search(r"^\s*\d{1,2}:\d{2}", texte, re.MULTILINE):
        alertes.append(Alerte(
            gravite="attention",
            message="Marqueurs temporels détectés. Lance la passe de nettoyage "
                    "avant de traduire.",
        ))

    estimations = {
        moteur.nom: round(moteur.duree_estimee(mots), 1) for moteur in registre()
    }

    return ReponseAnalyse(
        caracteres=len(texte),
        mots=mots,
        paragraphes=len(paras),
        sections=[
            SectionLue(indice=s.indice, titre=s.titre, caracteres=s.caracteres)
            for s in plan.sections
        ],
        segments=len(plan.segments),
        phrases=len(phrases),
        alertes=alertes,
        estimations=estimations,
    )


@routeur.post("/traduction", response_model=ReponseTraduction)
async def traduire(demande: DemandeTraduction) -> ReponseTraduction:
    """Traduction synchrone. Textes courts uniquement."""
    if len(demande.texte) > LIMITE_SYNCHRONE:
        raise DocumentInvalide(
            f"Texte trop long pour le mode direct "
            f"({len(demande.texte)} caractères, limite {LIMITE_SYNCHRONE}).",
            "Ouvre un travail via POST /api/v1/travaux/traduction : tu auras "
            "la progression, la reprise après coupure et l'annulation.",
        )

    moteur = registre().resoudre(demande.moteur, demande.capacite)
    resultat = await moteur.traduire(_construire_requete(demande))
    return ReponseTraduction(
        texte=resultat.texte,
        moteur=resultat.moteur,
        doutes=resultat.doutes,
        confiance=resultat.confiance,
    )


@routeur.post("/travaux/traduction", response_model=TravailOuvert, status_code=202)
async def ouvrir_travail(demande: DemandeTraduction, requete: Request) -> TravailOuvert:
    """Ouvre un travail de traduction et rend son identifiant.

    La compatibilité moteur/capacité est vérifiée ici, avant l'ouverture :
    on refuse en une seconde plutôt qu'après dix minutes de calcul.
    """
    moteur = registre().resoudre(demande.moteur, demande.capacite)
    plan = decoupage.construire_plan(demande.texte)

    travail = gestionnaire.ouvrir(
        genre=f"traduction:{moteur.nom}", total=len(plan.segments)
    )

    async def besogne(t):
        resultat = await moteur.traduire(
            _construire_requete(demande), progression=gestionnaire.rappel(t)
        )
        return {
            "texte": resultat.texte,
            "moteur": resultat.moteur,
            "doutes": resultat.doutes,
            "confiance": resultat.confiance,
        }

    gestionnaire.lancer(travail, besogne)

    base = str(requete.base_url).rstrip("/")
    return TravailOuvert(
        identifiant=travail.identifiant,
        genre=travail.genre,
        etat=str(travail.etat),
        flux=f"{base}/api/v1/travaux/{travail.identifiant}/flux",
    )


@routeur.post("/diagnostic-reparation")
async def diagnostic_reparation(demande: DemandeTraduction) -> dict:
    """Combien de segments seraient réécrits, et pourquoi. Aucun appel de
    modèle : sert à régler le seuil avant de lancer un traitement long."""
    from app.services.traduction.reparation import MoteurReparationCiblee

    moteur = registre().obtenir("reparation_ciblee")
    assert isinstance(moteur, MoteurReparationCiblee)
    glossaire = (
        service_glossaire.charger(demande.glossaire) if demande.glossaire else None
    )
    rapport = moteur.diagnostiquer(demande.texte, glossaire)

    mots = rapport["mots_a_reecrire"]
    rapport["estimation_secondes"] = {
        "4B (batch 8)": round(mots * 1.4 / 45, 1),
        "8B (batch 4)": round(mots * 1.4 / 22, 1),
        "12B (batch 2)": round(mots * 1.4 / 7, 1),
    }
    return rapport
