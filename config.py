import os
from datetime import timedelta


class Config:
    """Base configuration."""

    # Core Flask settings
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Required by SQLAlchemy

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_PROTECTION = "strong"  # Flask-Login uses this

    # Email Configuration
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")

    # App-specific
    CONTACT_PHONE = "(908) 910-5439"  # Used in admin_routes.py

    @classmethod
    def init_app(cls, app):
        pass


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///inventory_iq.db"


class ProductionConfig(Config):
    """Production configuration optimized for Railway."""

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    # Railway production optimizations
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # Handle Railway DB disconnects
        "pool_recycle": 300,  # Recycle connections every 5 min
        "connect_args": {
            "connect_timeout": 10,  # Faster connection timeout
        },
    }

    # Security hardening for production
    SESSION_COOKIE_SECURE = True  # HTTPS only
    SESSION_COOKIE_HTTPONLY = True  # No JS access
    SESSION_COOKIE_SAMESITE = "Strict"

    @classmethod
    def init_app(cls, app):
        """Validate required production environment variables."""
        required_vars = [
            "SECRET_KEY",
            "DATABASE_URL",
            "MAIL_SERVER",
            "MAIL_USERNAME",
            "MAIL_PASSWORD",
            "MAIL_DEFAULT_SENDER",
        ]

        missing = [var for var in required_vars if not os.environ.get(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


# Configuration dictionary
config_by_name = {
    "dev": DevelopmentConfig,
    "prod": ProductionConfig,
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
