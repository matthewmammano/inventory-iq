import os

from loguru import logger

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Railway auto-sets PORT, default to prod for safety
    env = os.environ.get("FLASK_ENV", "prod")
    debug_mode = env in ["dev", "development"]
    port = int(os.environ.get("PORT", 5000))  # Railway provides PORT

    # Log startup information
    logger.info(f"Starting Flask application in {env} mode (debug={debug_mode})")
    logger.info(f"Application listening on host 0.0.0.0:{port}")

    try:
        app.run(host="0.0.0.0", port=port, debug=debug_mode)
    except Exception as e:
        logger.critical(f"Flask application failed to start: {e}")
        raise
