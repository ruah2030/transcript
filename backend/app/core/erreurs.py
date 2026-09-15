"""Erreurs métier. Traduites en réponses HTTP par le gestionnaire de main.py."""


class ErreurAtelier(Exception):
    """Racine de toutes les erreurs métier."""

    code_http = 400
    code = "erreur_atelier"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class MoteurIndisponible(ErreurAtelier):
    """Le moteur existe mais n'est pas utilisable : modèle absent, serveur éteint."""

    code_http = 503
    code = "moteur_indisponible"


class MoteurInconnu(ErreurAtelier):
    code_http = 404
    code = "moteur_inconnu"


class CapaciteAbsente(ErreurAtelier):
    """Le moteur ne sait pas faire ce qu'on lui demande (ex. Opus-MT en réparation)."""

    code_http = 422
    code = "capacite_absente"


class RessourceIntrouvable(ErreurAtelier):
    code_http = 404
    code = "ressource_introuvable"


class DocumentInvalide(ErreurAtelier):
    code_http = 422
    code = "document_invalide"
