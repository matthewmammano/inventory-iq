from flask import Blueprint

# Create separate blueprints for admin and guest routes
admin_bp = Blueprint(
    "admin", __name__, template_folder="templates", url_prefix="/inventory"
)
guest_bp = Blueprint(
    "guest", __name__, template_folder="templates", url_prefix="/inventory"
)

# Import routes after blueprint definitions
from app.inventory.routes.admin import *  # noqa: E402, F403 - Flask blueprint pattern
from app.inventory.routes.guest import *  # noqa: E402, F403 - Flask blueprint pattern
