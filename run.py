"""Application entry point."""

import os

from loguru import logger

from app import create_app
from app.shared.config import settings
from app.shared.scheduler import start_scheduler

app = create_app()
start_scheduler(app)


def _is_serving_process() -> bool:
    return not settings.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"


if __name__ == "__main__":
    local_url = f"http://127.0.0.1:{settings.port}"
    process_label = "serving process" if _is_serving_process() else "debug reloader parent"
    logger.info(
        f"Flask web server starting ({process_label}): "
        f"url={local_url} env={settings.app_env} debug={settings.debug}"
    )
    if _is_serving_process():
        print(f"\nOpen Inventory IQ: {local_url}\n")
    app.run(host="0.0.0.0", port=settings.port, debug=settings.debug)
