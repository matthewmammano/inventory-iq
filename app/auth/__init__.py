from flask import Blueprint

bp = Blueprint("auth", __name__, template_folder="templates")

import app.auth.routes  # noqa: E402,F401 - import after blueprint creation is intentional
