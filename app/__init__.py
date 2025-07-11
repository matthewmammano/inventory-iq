import os
import sys
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    """Create and configure the Flask application."""

    app = Flask(__name__)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Set up SQLAlchemy with a single database for users, items, and logs
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"sqlite:///{os.path.join(app.instance_path, 'inventory_iq.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Session settings: Handle session lifetime
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=2
    )  # Session expires after 2 days of inactivity
    app.config["SESSION_PROTECTION"] = (
        "strong"  # Strong protection against session hijacking
    )

    # Initialize database
    db.init_app(app)
    login_manager.init_app(app)

    # Set the login view for unauthorized users
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # Import models to ensure they're registered with SQLAlchemy
    # Register blueprints
    from app.auth import bp as auth_bp
    from app.auth.models import UserItemLocations, Users, UserSettings
    from app.inventory import admin_bp, guest_bp
    from app.inventory.models import ActionLogs, Items

    app.register_blueprint(auth_bp, url_prefix="/")
    app.register_blueprint(guest_bp, url_prefix="/inventory")
    app.register_blueprint(admin_bp, url_prefix="/inventory")

    # Create all database tables
    @login_manager.user_loader
    def load_user(user_id):
        """Load a user from the database by ID."""
        return Users.query.get(int(user_id))

    with app.app_context():
        print("[INFO] Initializing database tables...")
        try:
            db.create_all()
            print("[INFO] ✅ Database tables created successfully!")
        except Exception as e:
            print(f"[CRITICAL] Failed to create database tables: {e}")
            sys.exit(1)

    # Print startup information
    print(
        f"[INFO] Application initialized with database: {app.config['SQLALCHEMY_DATABASE_URI']}"
    )

    return app
