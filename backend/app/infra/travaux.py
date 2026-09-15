"""Travaux longs et diffusion de leur avancement.

Une traduction de 80 000 mots prend des minutes au mieux, des heures au
pire. Une requête HTTP synchrone est donc exclue : le navigateur coupe, le
reverse-proxy coupe, et l'utilisateur n'a aucune visibilité.

Le modèle retenu : POST ouvre un travail et rend un identifiant, puis le
client s'abonne à `GET /travaux/{id}/flux` en Server-Sent Events. SSE plutôt
que WebSocket parce que le flux est unidirectionnel — le client n'a rien à
dire pendant le traitement.

Chaque travail garde une file d'événements par abonné, ce qui permet à
plusieurs onglets de suivre le même travail, et à un onglet rouvert de
récupérer l'état courant sans avoir manqué la fin.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable

from app.core.config import reglages
from app.core.erreurs import ErreurAtelier, RessourceIntrouvable


class EtatTravail(StrEnum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    ECHOUE = "echoue"
    ANNULE = "annule"


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Travail:
    identifiant: str
    genre: str
    etat: EtatTravail = EtatTravail.EN_ATTENTE
    faits: int = 0
    total: int = 0
    etiquette: str = ""
    resultat: Any = None
    erreur: dict | None = None
    cree_le: datetime = field(default_factory=_maintenant)
    demarre_le: datetime | None = None
    fini_le: datetime | None = None
    _abonnes: list[asyncio.Queue] = field(default_factory=list, repr=False)
    _tache: asyncio.Task | None = field(default=None, repr=False)

    @property
    def progression(self) -> float:
        return round(self.faits / self.total, 4) if self.total else 0.0

    @property
    def secondes_restantes(self) -> float | None:
        if not (self.demarre_le and self.faits and self.total):
            return None
        ecoule = (_maintenant() - self.demarre_le).total_seconds()
        return round(ecoule / self.faits * (self.total - self.faits), 1)

    @property
    def termine(self) -> bool:
        return self.etat in (
            EtatTravail.TERMINE, EtatTravail.ECHOUE, EtatTravail.ANNULE
        )

    def instantane(self) -> dict:
        return {
            "identifiant": self.identifiant,
            "genre": self.genre,
            "etat": str(self.etat),
            "faits": self.faits,
            "total": self.total,
            "progression": self.progression,
            "etiquette": self.etiquette,
            "secondes_restantes": self.secondes_restantes,
            "erreur": self.erreur,
            "cree_le": self.cree_le.isoformat(),
        }


class GestionnaireTravaux:
    def __init__(self):
        self._travaux: dict[str, Travail] = {}
        self._verrou = asyncio.Semaphore(reglages().travaux_simultanes)

    # -- cycle de vie ----------------------------------------------------

    def ouvrir(self, genre: str, total: int = 0) -> Travail:
        travail = Travail(
            identifiant=uuid.uuid4().hex[:12], genre=genre, total=total
        )
        self._travaux[travail.identifiant] = travail
        self._purger()
        return travail

    def obtenir(self, identifiant: str) -> Travail:
        travail = self._travaux.get(identifiant)
        if travail is None:
            raise RessourceIntrouvable(f"Travail inconnu : {identifiant}")
        return travail

    def lancer(
        self,
        travail: Travail,
        besogne: Callable[[Travail], Awaitable[Any]],
    ) -> Travail:
        travail._tache = asyncio.create_task(self._executer(travail, besogne))
        return travail

    async def annuler(self, identifiant: str) -> Travail:
        travail = self.obtenir(identifiant)
        if travail._tache and not travail._tache.done():
            travail._tache.cancel()
        return travail

    async def _executer(self, travail: Travail, besogne) -> None:
        async with self._verrou:
            travail.etat = EtatTravail.EN_COURS
            travail.demarre_le = _maintenant()
            await self._diffuser(travail, "etat")
            try:
                travail.resultat = await besogne(travail)
                travail.etat = EtatTravail.TERMINE
            except asyncio.CancelledError:
                travail.etat = EtatTravail.ANNULE
                raise
            except ErreurAtelier as e:
                travail.etat = EtatTravail.ECHOUE
                travail.erreur = {
                    "code": e.code, "message": e.message, "detail": e.detail
                }
            except Exception as e:                          # noqa: BLE001
                travail.etat = EtatTravail.ECHOUE
                travail.erreur = {
                    "code": "erreur_interne",
                    "message": str(e),
                    "detail": type(e).__name__,
                }
            finally:
                travail.fini_le = _maintenant()
                await self._diffuser(travail, "fin")
                await self._clore(travail)

    # -- progression -----------------------------------------------------

    def rappel(self, travail: Travail):
        """Fabrique le callback de progression passé aux moteurs."""

        async def signaler(faits: int, total: int, etiquette: str) -> None:
            travail.faits, travail.total, travail.etiquette = faits, total, etiquette
            await self._diffuser(travail, "progression")

        return signaler

    async def _diffuser(self, travail: Travail, evenement: str) -> None:
        charge = json.dumps(travail.instantane(), ensure_ascii=False)
        message = f"event: {evenement}\ndata: {charge}\n\n"
        for file in list(travail._abonnes):
            try:
                file.put_nowait(message)
            except asyncio.QueueFull:
                pass   # abonné trop lent : on saute, il rattrapera au suivant

    async def _clore(self, travail: Travail) -> None:
        for file in list(travail._abonnes):
            file.put_nowait(None)

    async def flux(self, identifiant: str) -> AsyncIterator[str]:
        travail = self.obtenir(identifiant)
        file: asyncio.Queue = asyncio.Queue(maxsize=64)
        travail._abonnes.append(file)

        try:
            # État courant d'abord : un onglet rouvert n'est jamais perdu.
            charge = json.dumps(travail.instantane(), ensure_ascii=False)
            yield f"event: etat\ndata: {charge}\n\n"

            if travail.termine:
                yield f"event: fin\ndata: {charge}\n\n"
                return

            while True:
                try:
                    message = await asyncio.wait_for(file.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": battement\n\n"   # garde la connexion ouverte
                    continue
                if message is None:
                    return
                yield message
        finally:
            if file in travail._abonnes:
                travail._abonnes.remove(file)

    # -- entretien -------------------------------------------------------

    def _purger(self) -> None:
        limite = _maintenant() - timedelta(hours=reglages().retention_travaux_h)
        perimes = [
            i for i, t in self._travaux.items()
            if t.termine and t.fini_le and t.fini_le < limite
        ]
        for i in perimes:
            del self._travaux[i]

    def lister(self, limite: int = 50) -> list[dict]:
        travaux = sorted(
            self._travaux.values(), key=lambda t: t.cree_le, reverse=True
        )
        return [t.instantane() for t in travaux[:limite]]


gestionnaire = GestionnaireTravaux()
