"""Contrôle de fidélité. Long : passe par un travail suivi."""

from fastapi import APIRouter, Request

from app.infra.travaux import gestionnaire
from app.schemas.atelier import DemandeVerification, TravailOuvert
from app.services.verification import VerificateurSens, apparier, en_markdown

routeur = APIRouter(tags=["vérification"])


@routeur.post("/travaux/verification", response_model=TravailOuvert, status_code=202)
async def ouvrir(demande: DemandeVerification, requete: Request) -> TravailOuvert:
    """Compare deux versions et classe ce qui a bougé.

    Le meilleur usage est de comparer contre le texte d'origine, pas contre
    une version déjà dégradée : aucun modèle ne retrouve un sens absent des
    deux versions comparées.
    """
    verificateur = VerificateurSens()
    total = len(apparier(demande.avant, demande.apres))
    travail = gestionnaire.ouvrir("verification", total=total)

    async def besogne(t):
        rapport = await verificateur.verifier(
            demande.avant, demande.apres, demande.source, demande.cible,
            demande.propositions, progression=gestionnaire.rappel(t),
        )
        return {
            "constats": [
                {
                    "etiquette": c.etiquette, "explication": c.explication,
                    "avant": c.avant, "apres": c.apres, "paire": c.paire,
                    "propositions": c.propositions,
                }
                for c in rapport.constats
            ],
            "paires_comparees": rapport.paires_comparees,
            "par_etiquette": rapport.par_etiquette(),
            "markdown": en_markdown(rapport),
        }

    gestionnaire.lancer(travail, besogne)
    base = str(requete.base_url).rstrip("/")
    return TravailOuvert(
        identifiant=travail.identifiant, genre=travail.genre,
        etat=str(travail.etat),
        flux=f"{base}/api/v1/travaux/{travail.identifiant}/flux",
    )
