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


def load_squad_dbs():
    '''Load squad database binds from the instance/squads directory.'''
    binds = {}
    os.makedirs(SQUADS_DIR, exist_ok=True)

    for db_file in os.listdir(SQUADS_DIR):
        if db_file.endswith('.db'):
            squad_name = db_file[:-3]
            full_path = os.path.abspath(os.path.join(SQUADS_DIR, db_file))
            binds[squad_name] = f'sqlite:///{full_path}'
            print(f"Loaded squad database: {squad_name} -> {full_path}")

    
    if not binds: 
        print("[INFO] No squad databases found in the squads directory.")

    return binds


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.abspath(USERS_DB)}'
    app.config['SQLALCHEMY_BINDS'] = load_squad_dbs()

    print(f"SQLALCHEMY_DATABASE_URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"SQLALCHEMY_BINDS: {app.config['SQLALCHEMY_BINDS']}")

    db.init_app(app)

    from . import auth, inventory
    app.register_blueprint(auth.bp, url_prefix='/')
    app.register_blueprint(inventory.bp, url_prefix='/inventory')

    # with app.app_context():
    #     print("[INFO] Attempting to create all tables...")
    #     try:
    #         print(app.config['SQLALCHEMY_BINDS'])
    #         db.create_all()
    #         print("[INFO] Tables created successfully!")
    #     except Exception as e:
    #         print(f"[CRITICAL] Error during db.create_all(): {e}")
    #         sys.exit(1)

    with app.app_context():
        print("[INFO] Attempting to create all tables...")
        try:
            db.create_all()  # Default DB
            for bind in app.config.get('SQLALCHEMY_BINDS', {}):
                print(f"[INFO] Creating tables for bind: {bind}")
                db.create_all(bind_key=bind)
            print("[INFO] All tables created successfully!")
        except Exception as e:
            print(f"[CRITICAL] Error during db.create_all(): {e}")
            sys.exit(1)


    return app
