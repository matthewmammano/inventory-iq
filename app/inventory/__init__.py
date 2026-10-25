from apiflask import APIBlueprint

admin_bp = APIBlueprint("admin", __name__, template_folder="templates", enable_openapi=False)
guest_bp = APIBlueprint("guest", __name__, template_folder="templates", enable_openapi=False)
