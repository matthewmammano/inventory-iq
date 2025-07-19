import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Only run with debug in development
    env = os.environ.get("FLASK_ENV", "dev")
    debug_mode = env == "dev"
    app.run(host="0.0.0.0", debug=debug_mode)
