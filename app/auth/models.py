from app import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password = db.Column(db.String(128))
    image = db.Column(db.String(255))
    notes = db.Column(db.String(255))
    timezone = db.Column(db.String(255), default="America/New_York", nullable=False)
