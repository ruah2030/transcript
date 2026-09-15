"""Modèles LLM disponibles, et lequel sert à quoi.

Alimente le sélecteur de l'interface. Sans cet endpoint, comparer deux
modèles impose d'éditer `.env` et de redémarrer entre chaque essai — assez
de friction pour que la comparaison n'ait jamais lieu.
"""

import httpx
from fastapi import APIRouter

from app.core.config import reglages
from app.schemas.atelier import ModeleDisponible, ReponseModeles
from app.services.traduction.base import Capacite
from app.services.traduction.llm import MoteurLLM

routeur = APIRouter(tags=["modèles"])


@routeur.get("/modeles", response_model=ReponseModeles)
async def lister_modeles() -> ReponseModeles:
    """Ce qu'Ollama a en magasin, plus le routage courant par tâche."""
    cfg = reglages()
    url = cfg.llm_url.rstrip("/")
    actifs = {
        "traduction": MoteurLLM.modele_pour(Capacite.TRADUCTION),
        "reecriture": MoteurLLM.modele_pour(Capacite.REPARATION),
    }

    point = f"{url}/api/tags" if cfg.llm_api == "ollama" else f"{url}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            reponse = await client.get(point)
            reponse.raise_for_status()
            donnees = reponse.json()
    except Exception as e:                                  # noqa: BLE001
        # Pas d'erreur HTTP : l'interface doit rester utilisable et afficher
        # le routage configuré même quand le serveur de modèles est éteint.
        return ReponseModeles(
            disponibles=[], actifs=actifs, source=cfg.llm_api,
            detail=f"serveur injoignable sur {url} ({e})",
        )

    if cfg.llm_api == "ollama":
        disponibles = [
            ModeleDisponible(
                nom=m["name"],
                taille_octets=m.get("size"),
                parametres=(m.get("details") or {}).get("parameter_size"),
            )
            for m in donnees.get("models", [])
        ]
    else:
        disponibles = [
            ModeleDisponible(nom=m["id"]) for m in donnees.get("data", [])
        ]

    return ReponseModeles(
        disponibles=sorted(disponibles, key=lambda m: m.nom),
        actifs=actifs, source=cfg.llm_api,
    )
