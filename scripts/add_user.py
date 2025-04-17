from app import db, create_app
from app.auth.models import User
from app.inventory.models import get_squad_models
from sqlalchemy import create_engine

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
        print(f'{username} added to instance/users.db')

        db_path = f'instance/squads/{username}.db'
        if 'SQLALCHEMY_BINDS' not in app.config:
            app.config['SQLALCHEMY_BINDS'] = {}
        app.config['SQLALCHEMY_BINDS'][username] = f'sqlite:///{db_path}'
        
        new_engine = create_engine(f'sqlite:///{db_path}')
        db.engines[username] = new_engine

        Item, Scan = get_squad_models(username)
        db.create_all(bind_key=username)
        print(f'Database created at instance/squads/{username}.db')

    else:
        print(f'{username} already exists in user.db')

    print('Done!')