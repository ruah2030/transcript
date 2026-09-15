"""Point d'entrée du service.

    uvicorn app.main:application --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import routeur as routeur_v1
from app.core.config import reglages
from app.core.erreurs import ErreurAtelier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
journal = logging.getLogger("atelier")


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    from app.services.traduction.registre import registre

    cfg = reglages()
    journal.info("Ressources  : %s", cfg.dossier_ressources)
    journal.info("Modèles     : %s", cfg.dossier_modeles)
    journal.info("Cache       : %s", cfg.dossier_cache)

    for rapport in await registre().diagnostiquer():
        marque = "✓" if rapport["disponible"] else "·"
        journal.info(
            "  %s %-10s %s", marque, rapport["nom"], rapport["detail"]
        )

    yield
    journal.info("Arrêt du service.")


def creer_application() -> FastAPI:
    cfg = reglages()
    app = FastAPI(
        title=cfg.titre,
        version=cfg.version,
        description=(
            "Chaîne de remise en état de transcriptions et de traduction "
            "locale. Trois familles de moteurs : NMT rapide (Opus-MT, Argos), "
            "LLM complet, et hybride qui combine les deux."
        ),
        lifespan=cycle_de_vie,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.origines_autorisees,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ErreurAtelier)
    async def _erreur_metier(requete: Request, e: ErreurAtelier) -> JSONResponse:
        """Une erreur métier porte toujours un message ET une piste d'action.

        C'est ce qui permet au front d'afficher « Opus-MT ne sait pas
        réparer » suivi de la marche à suivre, plutôt qu'un 500 muet.

        Le message est aussi journalisé : quelqu'un qui regarde le terminal
        ne doit pas avoir à ouvrir les outils réseau du navigateur pour
        savoir pourquoi une requête a échoué.
        """
        journal.warning(
            "%s %s -> %s (%s) : %s",
            requete.method, requete.url.path, e.code_http, e.code, e.message,
        )
        if e.detail:
            for ligne in e.detail.splitlines():
                if ligne.strip():
                    journal.warning("    %s", ligne)
        return JSONResponse(
            status_code=e.code_http,
            content={"code": e.code, "message": e.message, "detail": e.detail},
        )

    app.include_router(routeur_v1)

    @app.get("/sante", tags=["service"])
    async def sante() -> dict:
        return {"etat": "ok", "version": cfg.version}

    return app


application = creer_application()
