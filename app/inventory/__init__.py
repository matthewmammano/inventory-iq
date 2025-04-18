from flask import Blueprint

bp = Blueprint('inventory', __name__)

from app.inventory.admin_routes import *
from app.inventory.guest_routes import *
