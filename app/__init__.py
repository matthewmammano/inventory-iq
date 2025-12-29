import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, url_for
from flask_login import LoginManager
from flask_mailman import Mail
from loguru import logger

from . import db as db_module

load_dotenv()


login_manager = LoginManager()
mail = Mail()


def create_app() -> Flask:
    """
    Application factory function for creating a Flask app instance.

    Returns
    -------
    Flask
        A fully configured Flask application.
    """
    import logging

    from config import config_by_name

    app = Flask(__name__)

    # Suppress verbose Werkzeug development server HTTP request logs
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    # logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Load environment-specific configuration
    env: str = os.getenv("FLASK_ENV", "prod")
    config_class = config_by_name.get(env, config_by_name["dev"])
    app.config.from_object(config_class)

    # Call optional init_app method on config class
    config_class.init_app(app)

    # Ensure instance folder exists for SQLite in dev mode
    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        os.makedirs(app.instance_path, exist_ok=True)

    # Initialize Flask extensions / database
    # For the DB, call the explicit init_db function on the db module.
    db_module.init_db(app)
    login_manager.init_app(app)
    mail.init_app(app)

    # Configure Flask-Login
    # Assign login view via typing.cast to Any so static checkers allow the
    # runtime assignment while preserving type-safety elsewhere.
    # Assign login_view at runtime; the explicit attribute exists on LoginManager
    login_manager.login_view = "auth.login"  # type: ignore[attr-defined]
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # Ensure session expires with browser (better UX/security)
    app.config["SESSION_PERMANENT"] = False

    # Custom template filter for general image handling with error fallback
    @app.template_filter("image_src")
    def image_src(image_path: str | None) -> str:
        """
        Custom Jinja filter to generate safe image URLs.

        Parameters
        ----------
        image_path : str or None
            The image path or full URL.

        Returns
        -------
        str
            A valid URL for the image, or fallback.
        """
        if not image_path:
            return url_for("static", filename="images/not-found.jpg")

        # Allow full URLs, file:// paths, or relative disk paths
        if re.match(r"^(https?://|file://|[a-zA-Z]:|\.\.?/)", str(image_path)):
            return image_path

        filename = str(image_path).replace("\\", "/").lstrip("/")
        filename = filename.removeprefix("static/")

        static_folder = app.static_folder or ""
        static_path = Path(static_folder) / filename.replace("/", os.sep)
        if static_folder and static_path.exists():
            return url_for("static", filename=filename)

        return url_for("static", filename="images/not-found.jpg")

    # Import and register Blueprints and models
    from app.alerts import bp as alerts_bp
    from app.auth import bp as auth_bp
    from app.auth.models import Users
    from app.inventory import admin_bp, guest_bp

    app.register_blueprint(auth_bp, url_prefix="/")
    app.register_blueprint(guest_bp, url_prefix="/inventory")
    app.register_blueprint(admin_bp, url_prefix="/inventory")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")

    # Register error handlers
    from app.errors import register_error_handlers

    register_error_handlers(app)

    # Create all database tables
    @login_manager.user_loader
    def load_user(user_id: str) -> Users | None:
        """
        Load a user by ID for Flask-Login.

        Parameters
        ----------
        user_id : str
            User ID (must be cast to int).

        Returns
        -------
        Users or None
            The user instance if found.
        """
        # Use new session helper to query user by primary key
        from app.db import get_session

        try:
            with get_session() as session:
                return session.get(Users, int(user_id))
        except Exception:
            return None

    with app.app_context():
        logger.info("Initializing database tables...")
        try:
            db_module.create_all()
            logger.info("Database tables created successfully!")
        except Exception as e:
            logger.critical(f"Failed to create database tables: {e}")
            sys.exit(1)

    # Log DB URI (mask sensitive info in prod)
    db_uri: str = app.config["SQLALCHEMY_DATABASE_URI"]
    if env == "prod" and db_uri:
        db_type = db_uri.split("://")[0] if "://" in db_uri else "unknown"
        logger.info(f"Application initialized with {db_type} database")
    else:
        logger.info(f"Application initialized with database: {db_uri}")

    # Add health check endpoint for Railway
    @app.route("/health")
    def health_check():
        """Health check endpoint for Railway deployment"""
        from datetime import datetime

        return {"status": "healthy", "timestamp": datetime.now().isoformat()}

    return app
