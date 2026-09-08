"""Apply an id->image JSON (downloaded from image_review.py's page) back to the DB.

Goes through the real Item.image setter, so a bad URL is rejected exactly
like it would be in the app (see app/inventory/models.py Item.validate_image).

Usage (from repo root):
    python3 -m scripts.image_review.apply image_updates.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.inventory.models import Item
from app.shared.config import settings
from app.shared.database import get_session, init_db
from app.shared.model_registry import import_model_modules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("updates_json", type=Path)
    args = parser.parse_args()

    import_model_modules()
    init_db(settings.database_url)
    updates: dict[str, str] = json.loads(args.updates_json.read_text())

    applied = failed = 0
    with get_session() as db:
        for id_str, image_url in updates.items():
            item = db.get(Item, int(id_str))
            if item is None:
                print(f"  skip {id_str}: no such item")
                failed += 1
                continue
            try:
                item.image = image_url
                db.flush()
            except ValueError as exc:
                db.rollback()
                print(f"  reject item {item.id} ({item.name}): {exc}")
                failed += 1
            else:
                applied += 1
        db.commit()

    print(f"applied {applied}, rejected {failed}")


if __name__ == "__main__":
    main()
