"""Flask application factory."""

import logging
import re
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from flask import Flask, has_request_context, request, send_from_directory, url_for
from flask_login import LoginManager, current_user
from flask_wtf import CSRFProtect
from loguru import logger
from werkzeug.middleware.proxy_fix import ProxyFix

from app.alerts import bp as alerts_bp
from app.auth import bp as auth_bp
from app.auth.queries import get_agency
from app.diagnostics import bp as diagnostics_bp
from app.errors import register_error_handlers
from app.inventory import admin_bp, guest_bp
from app.shared.config import settings
from app.shared.database import init_db
from app.shared.email_client import log_email_config_status
from app.shared.form_validation import validation_attrs, validation_group_attrs
from app.shared.html_formatting import bold_item_name
from app.shared.logging import setup_logging
from app.shared.model_registry import import_model_modules
from app.shared.rate_limit import register_rate_limiting
from app.shared.request_logging import register_request_logging
from app.shared.security_headers import register_security_headers
from app.shared.text_formatting import pluralize

csrf = CSRFProtect()

login_manager = LoginManager()

ROUTE_MODULES = (
    "app.auth.routes",
    "app.diagnostics.routes",
    "app.inventory.routes.admin",
    "app.inventory.routes.admin_bulk",
    "app.inventory.routes.admin_data",
    "app.inventory.routes.admin_help",
    "app.inventory.routes.admin_reports",
    "app.inventory.routes.admin_scan",
    "app.inventory.routes.admin_upc",
    "app.inventory.routes.guest",
)


def create_app() -> Flask:
    """Create and configure the Flask application."""
    _setup_process_logging()
    import_model_modules()
    for module_name in ROUTE_MODULES:
        import_module(module_name)
    app = Flask(__name__, instance_path=str(_instance_path()))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # Railway sits one reverse-proxy hop in front
    _configure_app(app)
    register_request_logging(app)  # must register before any extension that can short-circuit via before_request (CSRF, login)
    _init_extensions(app)
    _register_blueprints(app)
    register_security_headers(app)
    register_rate_limiting(app)
    register_error_handlers(app)
    _register_template_filters(app)
    _register_template_context(app)
    _register_auth_loader()
    _register_favicon_route(app)
    _register_health_check(app)

    logger.debug(
        "Flask app startup completed",
        extra={
            "database": settings.database_url.split("://")[0] if "://" in settings.database_url else "unknown",
            "app_env": settings.app_env,
        },
    )
    log_email_config_status(app.config)
    return app


def _setup_process_logging() -> None:
    setup_logging(json_logs=settings.is_prod)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _instance_path() -> Path:
    return settings.resolved_instance_path


def _configure_app(app: Flask) -> None:
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        CONTACT_PHONE=settings.contact_phone,
        DEBUG=False,
        EMAIL_API_URL=settings.email_api_url,
        EMAIL_API_KEY=settings.email_api_key,
        EMAIL_SENDER_EMAIL=settings.email_sender_email,
        EMAIL_SENDER_NAME=settings.email_sender_name,
        EMAIL_TIMEOUT_SECONDS=settings.email_timeout_seconds,
        ADMIN_ALERT_EMAIL=settings.admin_alert_email,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.is_prod,
    )
    if settings.database_url.startswith("sqlite"):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)


def _init_extensions(app: Flask) -> None:
    _run_dev_migrations()
    init_db(settings.database_url)
    login_manager.init_app(app)
    cast(Any, login_manager).login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)


def _run_dev_migrations() -> None:
    if settings.is_dev:
        logger.info("Running dev database migrations")
        command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp, url_prefix="/")
    app.register_blueprint(guest_bp, url_prefix="/inventory")
    app.register_blueprint(admin_bp, url_prefix="/inventory")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")
    app.register_blueprint(diagnostics_bp, url_prefix="/")


def _register_template_filters(app: Flask) -> None:
    app.add_template_filter(bold_item_name, "bold_item_name")
    app.add_template_filter(pluralize, "pluralize")
    app.add_template_global(validation_attrs, "validation_attrs")
    app.add_template_global(validation_group_attrs, "validation_group_attrs")

    @app.template_filter("image_src")
    def image_src(image_path: str | None) -> str:
        if not image_path:
            return url_for("static", filename="images/not-found.jpg")
        if re.match(r"^(https?://|file://|[a-zA-Z]:|\.\.?/)", str(image_path)):  # keep absolute/URL inputs untouched
            return image_path
        filename = str(image_path).replace("\\", "/").lstrip("/").removeprefix("static/")  # normalize to static-relative path
        static_folder = app.static_folder or ""
        if static_folder and (Path(static_folder) / Path(filename)).exists():
            return url_for("static", filename=filename)
        return url_for("static", filename="images/not-found.jpg")


def _register_template_context(app: Flask) -> None:
    @app.context_processor
    def admin_pending_tasks() -> dict[str, Any]:
        if not has_request_context():
            return {"admin_pending_task_count": 0}
        squad = request.view_args.get("squad") if request.view_args else None
        if request.endpoint != "admin.admin_panel" or not squad or not current_user.is_authenticated:
            return {"admin_pending_task_count": 0}
        try:
            from app.inventory.pending_tasks_service import pending_task_count
            from app.shared.database import get_session

            with get_session() as session:
                count = pending_task_count(session, current_user.id)
        except Exception:
            logger.debug("Admin pending task badge count could not be loaded")
            count = 0
        return {"admin_pending_task_count": count}


def _register_auth_loader() -> None:
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return get_agency(int(user_id))
        except (TypeError, ValueError):
            return None


def _register_favicon_route(app: Flask) -> None:
    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            Path(app.static_folder or "") / "favicons",
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )


def _register_health_check(app: Flask) -> None:
    @app.route("/health")
    def health_check():
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
