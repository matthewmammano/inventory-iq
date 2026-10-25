from apiflask import APIBlueprint

bp = APIBlueprint("auth", __name__, template_folder="templates", enable_openapi=False)
