import os
from datetime import timedelta


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=2)
    SESSION_PROTECTION = "strong"
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=30).total_seconds()  # 30 days for static files

    # Email Configuration - All from environment for security
    # Required .env variables:
    # MAIL_SERVER=smtp-relay.brevo.com
    # MAIL_USERNAME=92bba2001@smtp-brevo.com
    # MAIL_PASSWORD=<your_brevo_master_password>
    # MAIL_DEFAULT_SENDER=<your_squad_email@domain.com>
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))  # Port can have safe default
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    MAIL_SUPPRESS_SEND = False  # Can be overridden in testing

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
    MAIL_DEBUG = True  # Enable verbose SMTP logging in development
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///inventory_iq.db"


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    MAIL_DEBUG = False  # Disable verbose SMTP logging in production
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
            
        # Validate email configuration for production
        if not os.environ.get("MAIL_SERVER"):
            raise ValueError("No MAIL_SERVER set for production environment")
        if not os.environ.get("MAIL_USERNAME"):
            raise ValueError("No MAIL_USERNAME set for production environment")
        if not os.environ.get("MAIL_PASSWORD"):
            raise ValueError("No MAIL_PASSWORD set for production environment")
        if not os.environ.get("MAIL_DEFAULT_SENDER"):
            raise ValueError("No MAIL_DEFAULT_SENDER set for production environment")


# Configuration dictionary
config_by_name = {
    "dev": DevelopmentConfig,
    "prod": ProductionConfig,
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
