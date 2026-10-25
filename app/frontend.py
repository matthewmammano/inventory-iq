"""Serve the built React bundle so v2 shares one origin and one deployment with v1."""

from pathlib import Path

from apiflask import APIFlask
from flask import send_from_directory
from werkzeug.exceptions import NotFound

V2_MOUNT_PATH = "/v2"
V2_BUILD_DIRNAME = "v2"
V2_ENTRY_FILE = "index.html"


def register_frontend(app: APIFlask) -> None:
    """Mount the bundle at /v2, falling back to its entry file for client-side routes."""
    build_dir = Path(app.static_folder or "") / V2_BUILD_DIRNAME

    def _entry():
        return send_from_directory(build_dir, V2_ENTRY_FILE)

    @app.route(V2_MOUNT_PATH)
    @app.route(f"{V2_MOUNT_PATH}/")
    @app.doc(hide=True)
    def v2_index():
        return _entry()

    @app.route(f"{V2_MOUNT_PATH}/<path:asset_path>")
    @app.doc(hide=True)
    def v2_asset(asset_path: str):
        try:
            return send_from_directory(build_dir, asset_path)
        except NotFound:
            return _entry()  # unknown paths belong to the client-side router
