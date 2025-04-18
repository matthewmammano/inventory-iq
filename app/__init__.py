from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
import sys

load_dotenv()

db = SQLAlchemy()

ROOT = os.path.abspath(os.path.dirname(__file__))
SQUADS_DIR = os.path.join(ROOT, '..', 'instance', 'squads')
USERS_DB = os.path.join(ROOT, '..', 'instance', 'users.db')


def create_app():
    """Create and configure the Flask application."""
    from sqlalchemy import create_engine
    from app.auth.models import User
    from app.inventory.models import get_squad_models

    app = Flask(__name__)
    os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)
    os.makedirs(SQUADS_DIR, exist_ok=True)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.abspath(USERS_DB)}'
    app.config['SQLALCHEMY_BINDS'] = {}

    print(f"SQLALCHEMY_DATABASE_URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"SQLALCHEMY_BINDS: {app.config['SQLALCHEMY_BINDS']}")

    db.init_app(app)

    from . import auth, inventory
    app.register_blueprint(auth.bp, url_prefix='/')
    app.register_blueprint(inventory.bp, url_prefix='/inventory')

    with app.app_context():
        print("[INFO] Creating users.db tables...")
        try:
            db.create_all()
            print("[INFO] ✅ users.db initialized successfully!")
        except Exception as e:
            print(f"[CRITICAL] Failed to create users.db: {e}")
            sys.exit(1)

        print("[INFO] Checking squads in users.db...")
        try:
            squad_names = [user.username for user in User.query.all()]
        except Exception as e:
            print(f"[CRITICAL] Failed to load users from users.db: {e}")
            sys.exit(1)

        for squad_name in squad_names:
            db_path = os.path.abspath(os.path.join(SQUADS_DIR, f"{squad_name}.db"))
            app.config['SQLALCHEMY_BINDS'][squad_name] = f"sqlite:///{db_path}"

            if not os.path.exists(db_path):
                print(f"[INFO] Creating squad DB for: {squad_name}")
                engine = create_engine(f"sqlite:///{db_path}")
                Item, Log = get_squad_models(squad_name)
                Item.metadata.create_all(bind=engine)
                Log.metadata.create_all(bind=engine)
                print(f"[INFO] ✅ Created {db_path} with tables [all_items, logs]")
            else:
                print(f"[INFO] Squad DB already exists: {db_path}")

    return app
