from apiflask import APIBlueprint

bp = APIBlueprint("alerts", __name__, template_folder="templates", enable_openapi=False)
