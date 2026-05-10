"""Application entry point."""

from loguru import logger

from app import create_app
from app.shared.config import settings
from app.shared.scheduler import start_scheduler

app = create_app()
start_scheduler(app)

if __name__ == "__main__":
    local_url = f"http://127.0.0.1:{settings.port}"
    logger.info(f"Starting app on port {settings.port} (debug={settings.debug})")
    print(f"\nOpen Inventory IQ: {local_url}\n")
    app.run(host="0.0.0.0", port=settings.port, debug=settings.debug)
