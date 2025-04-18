from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()


def load_squad_dbs():
    binds = {}
    for db_file in os.listdir('instance/squads'):
        if db_file.endswith('.db'):
            squad_name = db_file[:-3]
            binds[squad_name] = f'sqlite:///squads/{squad_name}.db'
    return binds


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
    app.config['SQLALCHEMY_BINDS'] = load_squad_dbs()

    db.init_app(app)

    from . import auth, inventory

    app.register_blueprint(auth.bp, url_prefix='/')
    app.register_blueprint(inventory.bp, url_prefix='/inventory')

    with app.app_context():
        db.create_all()

    return app
