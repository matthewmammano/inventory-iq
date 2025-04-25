from flask_login import UserMixin
from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


class Users(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password = db.Column(db.String(128))
    pin = db.Column(db.String(4), nullable=False, default="1234")
    image = db.Column(db.String(255))
    notes = db.Column(db.Text)
    timezone = db.Column(db.String(50), default="America/New_York", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    items = db.relationship('Items', backref='user', lazy=True)
    logs = db.relationship('ActionLogs', backref='user', lazy=True)
    alerts = db.relationship('UserAlerts', backref='user', lazy=True)
    locations = db.relationship('UserLocations', backref='user', lazy=True)

    def set_password(self, password):
        '''Set the password hash.'''
        self.password = generate_password_hash(password)

    def check_password(self, password):
        '''Check the password hash.'''
        return check_password_hash(self.password, password)
    
    def __repr__(self):
        return f'<User {self.display_name}>'
    
    @property
    def user_context(self):
        '''Return the user context for Flask-Login.'''
        return {
            'user_id': self.id,
            'display_name': self.display_name,
            'image': self.image,
            'timezone': self.timezone
        }
    

class UserAlerts(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    # Email or phone number for alerts
    contact_info = db.Column(db.String(255), nullable=False)
    # Alert Types
    alert_on_low_stock = db.Column(db.Boolean, default=True, nullable=False)
    alert_on_scan = db.Column(db.Boolean, default=False, nullable=False)
    alert_on_unusual_scan = db.Column(db.Boolean, default=True, nullable=False)
    # Scheduled alerts
    daily_summary = db.Column(db.Boolean, default=False, nullable=False)
    weekly_report = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<UserAlerts {self.user_id}>'
    

class UserLocations(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    location_name = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f'<UserLocations {self.location_name}>'
    

class UserCategories(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category_name = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f'<UserCategories {self.category_name}>'