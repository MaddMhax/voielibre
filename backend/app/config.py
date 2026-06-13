"""Configuration de l'application, lue depuis les variables d'environnement."""
import os


class Settings:
    # Clé API SNCF (https://numerique.sncf.com/startup/api/)
    SNCF_API_KEY: str = os.getenv("SNCF_API_KEY", "")

    # Base de l'API SNCF (Navitia). "sncf" est la couverture France.
    SNCF_API_BASE: str = os.getenv(
        "SNCF_API_BASE", "https://api.sncf.com/v1/coverage/sncf"
    )

    # Identifiant et mot de passe du menu d'administration.
    # Pas de mot de passe par défaut : tant qu'ADMIN_PASSWORD n'est pas défini,
    # la connexion admin est désactivée (sécurité par défaut).
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

    # Route du panneau d'administration : personnalisable pour ne pas être
    # devinable par un attaquant (ex. ADMIN_PATH=/masuperpageadmin).
    ADMIN_PATH: str = "/" + os.getenv("ADMIN_PATH", "/voielibre-admin").strip("/ ")

    # Clé secrète pour signer le cookie de session admin. Si absente, une clé
    # aléatoire éphémère est générée au démarrage (voir main.py) : les sessions
    # sautent à chaque redémarrage mais ne sont jamais forgeables.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # Chemin du fichier SQLite (monté sur un volume Docker).
    DB_PATH: str = os.getenv("DB_PATH", "/data/ter.db")

    # Heure (24h) qui sépare "matin" et "soir" sur le tableau de bord.
    MORNING_EVENING_CUTOFF: int = int(os.getenv("MORNING_EVENING_CUTOFF", "14"))

    # Quotas de l'offre gratuite de l'API SNCF (pour l'affichage admin et
    # l'avertissement public en cas de dépassement journalier).
    SNCF_API_MONTHLY_QUOTA: int = int(os.getenv("SNCF_API_MONTHLY_QUOTA", "150000"))
    SNCF_API_DAILY_QUOTA: int = int(os.getenv("SNCF_API_DAILY_QUOTA", "5000"))

    # Cookie de session marqué `Secure` : à activer derrière un proxy HTTPS (Caddy).
    SESSION_HTTPS_ONLY: bool = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in (
        "1", "true", "yes"
    )

    # Notifications ntfy (optionnel). URL complète du topic, vide = désactivé.
    # Ex : NTFY_URL=https://ntfy.sh/mon-topic-voie-libre
    NTFY_URL: str = os.getenv("NTFY_URL", "").rstrip("/")

    # Authentification ntfy (optionnel, pour un topic protégé / serveur privé).
    # Au choix : un jeton d'accès (recommandé, prioritaire) OU identifiant +
    # mot de passe. Laisser vide pour un topic public.
    # Ex : NTFY_TOKEN=tk_xxxxxxxxxxxxxxxxxxxxxxxxx
    NTFY_TOKEN: str = os.getenv("NTFY_TOKEN", "").strip()
    NTFY_USERNAME: str = os.getenv("NTFY_USERNAME", "").strip()
    NTFY_PASSWORD: str = os.getenv("NTFY_PASSWORD", "")

    # Analytics Ackee (optionnel). Laisser vide pour désactiver.
    # Ex : ACKEE_URL=https://ackee.example.com  ACKEE_DOMAIN_ID=xxxx-xxxx-xxxx
    ACKEE_URL: str = os.getenv("ACKEE_URL", "").rstrip("/")
    ACKEE_DOMAIN_ID: str = os.getenv("ACKEE_DOMAIN_ID", "")


settings = Settings()
