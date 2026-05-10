from flask import Blueprint

bp = Blueprint("alerts", __name__, template_folder="templates")

from . import models  # noqa: E402,F401 - ensure ORM models are registered
