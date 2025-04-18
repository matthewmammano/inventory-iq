from app import db, create_app
from app.auth.models import User
import os

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

    else:
        print(f"[INFO] {username} already exists in users.db ❌")

    print('Done!')