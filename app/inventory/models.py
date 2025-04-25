from datetime import datetime
from app import db
from app.auth.models import Users


class Items(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    upc = db.Column(db.String(12))
    # Like 'Trauma', 'Medications', etc.
    category_id = db.Column(db.Integer, db.ForeignKey('user_categories.id'), nullable=False)
    # Like 'individual', 'box', 'case', etc.
    increments = db.Column(db.String(50))
    name = db.Column(db.String(100), nullable=False)
    # For low stock and reorders
    min_quantity = db.Column(db.Integer, nullable=False)
    max_quantity = db.Column(db.Integer, nullable=False)
    # Quantitiy is updated on EVERY change in log (to that item) and also admin table edits
    quantity = db.Column(db.Integer)
    image = db.Column(db.String(255))
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow)
    # Foreign Key to Users table
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    category = db.relationship('UserCategories', backref='item', lazy=True)
    action_logs = db.relationship('ActionLogs', backref='item', lazy=True)
    
    # Create index on user_id and others
    __table_args__ = (
        db.Index('idx_user_upc', 'user_id', 'upc'),
        db.Index('idx_user_category', 'user_id', 'category_id'),
        db.Index('idx_user_name', 'user_id', 'name'),
        db.Index('idx_user_quantity', 'user_id', 'quantity'),
        db.Index('idx_user_last_accessed', 'user_id', 'last_accessed'),
    )
    
    def __repr__(self):
        return f'<Item {self.name}>'
    
    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_upc_from_id(item_id: int) -> str:
        base = str(item_id).zfill(11)
        return base + Items.calculate_upc_check_digit(base)


class ActionLogs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # All timestamps are UTC (then changed on the client side)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Foreign Key to Items table
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'))
    # Foreign Keys to UserLocations table
    from_location_id = db.Column(db.Integer, db.ForeignKey('user_locations.id'), nullable=True)
    to_location_id = db.Column(db.Integer, db.ForeignKey('user_locations.id'), nullable=True)
    quantity_delta = db.Column(db.Integer, nullable=False)
    admin_action = db.Column(db.Boolean, default=False)
    # Foreign Key to Users table
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    from_location = db.relationship('UserLocations', foreign_keys=[from_location_id], backref='from_location_logs', lazy=True)
    to_location = db.relationship('UserLocations', foreign_keys=[to_location_id], backref='to_location_logs', lazy=True)
    
    # Create index on user_id and others
    __table_args__ = (
        db.Index('idx_user_timestamp', 'user_id', 'timestamp'),
        db.Index('idx_user_item_id', 'user_id', 'item_id'),
        db.Index('idx_user_from_location', 'user_id', 'from_location_id'),
        db.Index('idx_user_to_location', 'user_id', 'to_location_id'),
    )
    
    def __repr__(self):
        return f'<ActionLog {self.from_location} to {self.to_location}>'