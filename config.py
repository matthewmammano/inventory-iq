import os
from datetime import timedelta


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=2)
    SESSION_PROTECTION = "strong"
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=30).total_seconds()  # 30 days for static files

    # TODO RED: Add data backup and restore functionality for production safety
    # - Automated daily database backups to cloud storage
    # - Backup retention policy (keep 30 days, monthly for 1 year)
    # - One-click restore functionality in admin panel
    # - Export/import entire squad data as JSON/SQL

    # Default security options (overridden in prod)
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    @classmethod
    def init_app(cls, app):
        pass  # do nothing by default


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///inventory_iq.db"


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    # Force secure session cookies in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Strict"

    @classmethod
    def init_app(cls, app):
        """Validate production configuration."""
        if not os.environ.get("SECRET_KEY"):
            raise ValueError("No SECRET_KEY set for production environment")

        if not os.environ.get("DATABASE_URL"):
            raise ValueError("No DATABASE_URL set for production environment")


# Configuration dictionary
config_by_name = {
    "dev": DevelopmentConfig,
    "prod": ProductionConfig,
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
