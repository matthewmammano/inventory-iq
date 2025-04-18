import pytz
from app import db
from app.auth.models import User


class ItemBase(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True, index=True)
    upc = db.Column(db.String(12), unique=True, index=True)
    category = db.Column(db.String(255), nullable=False)
    increments = db.Column(db.String(255))
    name = db.Column(db.String(255), unique=False, nullable=False)
    min_quantity = db.Column(db.Integer)
    max_quantity = db.Column(db.Integer)
    # updated on EVERY change in log (to that item) and also admin table edits
    quantity = db.Column(db.Integer, nullable=True)
    image = db.Column(db.String(255))


class LogBase(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True, index=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    upc = db.Column(db.String(12), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    quantity_delta = db.Column(db.Integer, nullable=False)
    admin = db.Column(db.Boolean, default=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'))
    item = db.relationship('Item', backref='logs')


_squad_model_cache = {}


def get_squad_models(squad_name):
    if squad_name in _squad_model_cache:
        return _squad_model_cache[squad_name]
    
    class Item(ItemBase):
        __bind_key__ = squad_name
        __tablename__ = 'all_items'
        __table_args__ = {'extend_existing': True}

    class Log(LogBase):
        __bind_key__ = squad_name
        __tablename__ = 'logs'
        __table_args__ = {'extend_existing': True}

        def get_timestamp(self, user_id):
            # Get the user's timezone from the User model
            user = User.query.get(user_id)
            timezone = pytz.timezone(user.timezone if user else 'UTC')
            return self.timestamp.astimezone(timezone)

    _squad_model_cache[squad_name] = (Item, Log)
    return Item, Log
