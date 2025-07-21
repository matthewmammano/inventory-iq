import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, request
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

# Only load dotenv in dev
if os.environ.get("FLASK_ENV") in (None, "", "dev", "development"):
    load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    """Create and configure the Flask application."""
    from config import config_by_name

    app = Flask(__name__)

    # Get environment configuration
    env = os.environ.get("FLASK_ENV", "dev")
    config_class = config_by_name.get(env, config_by_name["dev"])
    app.config.from_object(config_class)

    # Initialize production validation if needed
    config_class.init_app(app)

    # Create instance folder (needed for SQLite in dev)
    if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
        os.makedirs(app.instance_path, exist_ok=True)

    # Initialize database
    db.init_app(app)
    login_manager.init_app(app)

    # Set the login view for unauthorized users
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # Set session to expire when browser closes (security improvement)
    app.config['SESSION_PERMANENT'] = False

    # Custom template filter for handling missing images
    @app.template_filter('default_image')
    def default_image(image_url):
        from flask import url_for
        return image_url if image_url else url_for('static', filename='images/not-found.jpg')


    # Import models to ensure they're registered with SQLAlchemy
    # Register blueprints
    from app.auth import bp as auth_bp
    from app.auth.models import Users
    from app.inventory import admin_bp, guest_bp

    app.register_blueprint(auth_bp, url_prefix="/")
    app.register_blueprint(guest_bp, url_prefix="/inventory")
    app.register_blueprint(admin_bp, url_prefix="/inventory")

    # Create all database tables
    @login_manager.user_loader
    def load_user(user_id):
        """Load a user from the database by ID."""
        return db.session.get(Users, int(user_id))

    with app.app_context():
        print("[INFO] Initializing database tables...")
        try:
            db.create_all()
            print("[INFO] Database tables created successfully!")
        except Exception as e:
            print(f"[CRITICAL] Failed to create database tables: {e}")
            sys.exit(1)

    # Print startup information
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    # Mask sensitive database URL for production
    if env == "prod" and db_uri:
        # Show only the database type for security
        db_type = db_uri.split("://")[0] if "://" in db_uri else "unknown"
        print(f"[INFO] Application initialized with {db_type} database")
    else:
        print(f"[INFO] Application initialized with database: {db_uri}")

    return app
