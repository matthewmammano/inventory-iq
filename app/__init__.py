"""Flask application factory."""

import logging
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, url_for
from flask_login import LoginManager
from loguru import logger

from app.alerts import bp as alerts_bp
from app.auth import bp as auth_bp
from app.auth.queries import get_agency
from app.errors import register_error_handlers
from app.inventory import admin_bp, guest_bp
from app.inventory.routes import admin as _admin_routes  # noqa: F401 - register routes
from app.inventory.routes import guest as _guest_routes  # noqa: F401 - register routes
from app.prediction import models as _prediction_models  # noqa: F401 - register ORM models
from app.shared.config import settings
from app.shared.database import init_db
from app.shared.logging import setup_logging

login_manager = LoginManager()


def create_app() -> Flask:
    """Create and configure the Flask application."""
    setup_logging(debug=settings.debug)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    _instance = Path(__file__).resolve().parent.parent / "instance"
    app = Flask(__name__, instance_path=str(_instance))

    # Core config
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SESSION_PERMANENT=False,
        PERMANENT_SESSION_LIFETIME=settings.session_lifetime,
        CONTACT_PHONE=settings.contact_phone,
        DEBUG=settings.debug,
        BREVO_API_KEY=settings.brevo_api_key,
        BREVO_SENDER_EMAIL=settings.brevo_sender_email,
        BREVO_SENDER_NAME=settings.brevo_sender_name,
        BREVO_TIMEOUT_SECONDS=settings.brevo_timeout_seconds,
    )

    if settings.database_url.startswith("sqlite"):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    # Initialize extensions
    init_db(settings.database_url)
    login_manager.init_app(app)

    login_manager.login_view = "auth.login"  # type: ignore[attr-defined]
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    app.register_blueprint(auth_bp, url_prefix="/")
    app.register_blueprint(guest_bp, url_prefix="/inventory")
    app.register_blueprint(admin_bp, url_prefix="/inventory")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")

    register_error_handlers(app)

    # Template filter: safe image URL
    @app.template_filter("image_src")
    def image_src(image_path: str | None) -> str:
        if not image_path:
            return url_for("static", filename="images/not-found.jpg")
        if re.match(
            r"^(https?://|file://|[a-zA-Z]:|\.\.?/)", str(image_path)
        ):  # keep absolute/URL inputs untouched
            return image_path
        filename = (
            str(image_path).replace("\\", "/").lstrip("/").removeprefix("static/")
        )  # normalize to static-relative path
        static_folder = app.static_folder or ""
        if (
            static_folder and (Path(static_folder) / filename.replace("/", "\\")).exists()
        ):  # local file exists under /static
            return url_for("static", filename=filename)
        return url_for("static", filename="images/not-found.jpg")

    # Flask-Login user loader
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return get_agency(int(user_id))
        except Exception:
            return None

    # Health check
    @app.route("/health")
    def health_check():
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}

    db_type = settings.database_url.split("://")[0] if "://" in settings.database_url else "unknown"
    logger.info(f"App started with {db_type} database (debug={settings.debug})")
    return app
