"""Resolve a stored image path to a URL the browser can load."""

import re
from datetime import timedelta
from pathlib import Path

from flask import current_app, url_for

IMAGE_DIRECTORY = "images/"
NOT_FOUND_IMAGE = f"{IMAGE_DIRECTORY}not-found.jpg"
IMAGE_CACHE_MAX_AGE_SECONDS = int(timedelta(days=1).total_seconds())
ABSOLUTE_IMAGE_PATTERN = re.compile(r"^(https?://|file://|[a-zA-Z]:|\.\.?/)")


def static_image_url(image_path: str | None) -> str:
    """A stored image path as a servable URL, falling back to the placeholder when the file is missing."""
    if not image_path:
        return url_for("static", filename=NOT_FOUND_IMAGE)
    if ABSOLUTE_IMAGE_PATTERN.match(str(image_path)):
        return str(image_path)
    filename = str(image_path).replace("\\", "/").lstrip("/").removeprefix("static/")
    static_folder = current_app.static_folder or ""
    if static_folder and (Path(static_folder) / Path(filename)).exists():
        return url_for("static", filename=filename)
    return url_for("static", filename=NOT_FOUND_IMAGE)
