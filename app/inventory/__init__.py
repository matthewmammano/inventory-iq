from flask import Blueprint

# Create separate blueprints for admin and guest routes
admin_bp = Blueprint('admin', __name__, template_folder='templates', url_prefix='/inventory')
guest_bp = Blueprint('guest', __name__, template_folder='templates', url_prefix='/inventory')

# Import routes after blueprint definitions
from app.inventory.admin_routes import *
from app.inventory.guest_routes import *