from app import db, create_app
from app.auth.models import User
from app.inventory.models import get_squad_models
from sqlalchemy import create_engine
import os

ROOT = os.path.abspath(os.path.dirname(__file__))
SQUADS_DIR = os.path.join(ROOT, '..', 'instance', 'squads')

app = create_app()

with app.app_context():
    username = input('username: ')
    email = input('email: ')
    image = input('image url: ')
    notes = input('any additional notes about squad (phone, contact, full name of squad, etc): ')

    if not User.query.filter_by(username=username).first():
        user = User(username=username, email=email, image=image, notes=notes)
        db.session.add(user)
        db.session.commit()
        print(f"[INFO] {username} added to instance/users.db")

        db_path = f'instance/squads/{username}.db'

        app.config['SQLALCHEMY_BINDS'][username] = f'sqlite:///{db_path}'

        os.makedirs(SQUADS_DIR, exist_ok=True)
        db_path = os.path.abspath(os.path.join(SQUADS_DIR, f'{username}.db'))
        app.config['SQLALCHEMY_BINDS'][username] = f'sqlite:///{db_path}'

        # Create engine and tables for new squad
        engine = create_engine(f'sqlite:///{db_path}')
        Item, Scan = get_squad_models(username)
        with engine.connect() as connection:
            db.metadata.create_all(bind=engine)
        print(f"[INFO] Database created at {db_path}")


    else:
        print(f'{username} already exists in user.db')

    print('Done!')