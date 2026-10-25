"""Fail when the committed OpenAPI document no longer matches the routes.

The document is the only source the TypeScript client is generated from, so a
stale copy silently ships a frontend that disagrees with the backend.
"""

import json
import sys
from pathlib import Path

from app import create_app
from app.api.constants import OPENAPI_SPEC_FILE

SPEC_INDENT = 2


def current_spec() -> str:
    app = create_app()
    with app.app_context():
        return json.dumps(app.spec, indent=SPEC_INDENT, sort_keys=True) + "\n"


def main() -> int:
    spec_file = Path(OPENAPI_SPEC_FILE)
    generated = current_spec()
    committed = spec_file.read_text() if spec_file.exists() else ""
    if generated == committed:
        return 0

    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text(generated)
    print(f"{spec_file} was out of date and has been rewritten. Stage it, then regenerate the client with: npm --prefix web run generate")
    return 1


if __name__ == "__main__":
    sys.exit(main())
