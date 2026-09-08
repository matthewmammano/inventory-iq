"""CLI entrypoint: generate a synthetic-but-realistic inventory dataset by
replaying it through the real Flask app's service layer.

Usage (from repo root):
    DEV_CLOCK_ENABLED=true DATABASE_URL=sqlite:///instance/inventory_iq.db \\
        python3 scripts/demo_data/generate.py --location "POINT BORO:1.0" --location "POINT BEACH:0.6" --seed 42

Default (--accuracy demo) showcases every feature -- low-stock catches,
expiration tracking, every alert/notification type -- with only a small,
deliberate sprinkle of realistic imperfection, for showing the app to a
stakeholder. --accuracy real reproduces actual observed squad discipline
instead. --disable-feature expiration turns expiration tracking off entirely
for a squad that doesn't need it.

Requires pandas/numpy/tqdm -- see scripts/demo_data/requirements.txt.

Every knob that shapes the output lives in config.py -- this file only wires
setup -> plan -> replay -> final rebuild together and prints a summary.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import event
from sqlalchemy.engine import Engine

import config as cfg
import planner
import replay
import setup as setup_mod
from app.shared.config import settings
from app.shared.database import create_all, get_session, init_db
from app.shared.model_registry import import_model_modules

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@event.listens_for(Engine, "connect")
def _tune_sqlite_for_bulk_writes(dbapi_conn, _record) -> None:
    """replay.py commits once per event (thousands of them) -- SQLite's default
    fsync-every-commit is the actual bottleneck, not CPU (which is why
    multithreading wouldn't help: SQLite only allows one writer at a time
    anyway). WAL + synchronous=NORMAL is the standard, safe speedup for this
    exact pattern; durability-on-crash is not a concern for a disposable demo
    DB. No-op for non-sqlite connections."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001 -- e.g. a non-sqlite DBAPI connection
        pass
    finally:
        cursor.close()


@dataclass(slots=True)
class LocationArg:
    name: str
    multiplier: float

    @classmethod
    def parse(cls, raw: str) -> "LocationArg":
        name, _, mult = raw.partition(":")
        return cls(name=name, multiplier=float(mult) if mult else 1.0)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--location", action="append", type=LocationArg.parse, dest="locations",
        help="NAME:MULTIPLIER, repeatable. 1.0 = reference-dataset scale. Default: BORO:1.0",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agency-name", default=cfg.DEFAULT_AGENCY_NAME)
    parser.add_argument(
        "--accuracy", choices=["demo", "real"], default="demo",
        help="'demo' (default) = near-best-case squad discipline -- showcases every feature "
        "(low-stock catches, expiration tracking, etc.) with only a small, deliberate sprinkle "
        "of realistic imperfection, for showing the app to a stakeholder. "
        "'real' = observed POINT BORO guest scan accuracy (7%% forgot, 2%% under, 1%% over, "
        "75%% chance a low item gets restocked that check-in) -- for comparing against what an "
        "actual squad's real historical discipline looks like.",
    )
    parser.add_argument(
        "--disable-feature", action="append", choices=["expiration"], dest="disabled_features", default=[],
        help="Turn off a feature entirely for this squad (repeatable) -- e.g. a squad that doesn't "
        "stock anything expiration-sensitive: --disable-feature expiration. No items get "
        "expiration_tracking_enabled, and no expiration events/alerts are generated for them.",
    )
    return parser.parse_args(argv)


def _ensure_sqlite_dir(database_url: str) -> None:
    """sqlite3 refuses to create a db file if its parent directory is missing --
    normally create_app() mkdir's instance/ for us, but this script never calls it."""
    if database_url.startswith("sqlite:///"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    locations = args.locations or [LocationArg("BORO", 1.0)]

    if not settings.dev_clock_enabled:
        raise SystemExit("Set DEV_CLOCK_ENABLED=true before running this script.")

    # App code logs via loguru on every mutation; a raw print mid-render tears up
    # tqdm's progress bars. Silence it entirely rather than fight the interleaving.
    logger.remove()

    if args.accuracy == "demo":
        cfg.GUEST_FORGOT_RATE = 0.005
        cfg.GUEST_UNDER_RATE = 0.0
        cfg.GUEST_OVER_RATE = 0.0
        # Real squads leave ~25% of low items unaddressed a given check-in (see
        # RESTOCK_ACTION_PROBABILITY's docstring in config.py) -- fine for realism,
        # but a demo shouldn't risk a stakeholder clicking into an item that's
        # been sitting below reorder point for months untouched.
        cfg.RESTOCK_ACTION_PROBABILITY = 0.95

    disabled_features = frozenset(args.disabled_features)
    location_specs = [cfg.LocationSpec(loc.name, loc.multiplier) for loc in locations]

    _ensure_sqlite_dir(settings.database_url)  # create_app() normally does this; this script skips create_app() entirely
    import_model_modules()
    init_db(settings.database_url)
    create_all()
    # create_all() builds straight from current ORM models, skipping every
    # intermediate historical migration shape -- stamp head so the next `flask run`
    # doesn't try to replay the full migration history against an already-latest
    # schema (some old migrations assume old table/column names that no longer exist).
    command.stamp(Config(str(_REPO_ROOT / "alembic.ini")), "head")

    rng = random.Random(args.seed)
    ref = planner.load_refdata()
    catalog = ref.catalog

    with get_session() as db:
        result = setup_mod.setup_agency(
            db, rng, catalog, reset_display_name=args.agency_name, locations=location_specs, disabled_features=disabled_features
        )
        db.commit()
        print(f"Agency #{result.agency.id} '{result.agency.display_name}' -- {len(result.items)} items, {len(result.locations)} location(s)")

        total_applied = 0
        total_skipped = 0
        for i, rig in enumerate(result.locations):
            storages = list(rig.storages.keys())
            plan = planner.build_location_plan(
                rig.location.name, rig.multiplier, storages, catalog, ref, seed=args.seed + i, disabled_features=disabled_features
            )
            t0 = time.time()
            stats = replay.replay_location(db, result.agency.id, rig, result.items_by_name, plan)
            elapsed = time.time() - t0
            total_applied += stats.applied
            total_skipped += stats.skipped
            print(
                f"  {rig.location.name} (x{rig.multiplier}): {len(plan)} planned, "
                f"{stats.applied} applied, {stats.skipped} skipped in {elapsed:.1f}s"
            )
            if stats.skip_counts:
                for key, count in sorted(stats.skip_counts.items(), key=lambda kv: -kv[1]):
                    print(f"    skip[{key}] x{count}: {stats.skip_examples[key]}")

        upc_plan = planner.build_unknown_upc_plan(ref, seed=args.seed)
        upc_stats = replay.replay_unknown_upcs(db, result.agency.id, result.items_by_name, upc_plan)
        total_applied += upc_stats.applied
        total_skipped += upc_stats.skipped
        print(f"  unknown-UPC lifecycle: {upc_stats.applied} applied, {upc_stats.skipped} skipped")

        t0 = time.time()
        replay.final_rebuild(db, result.agency.id)
        print(f"Final rebuild (balances/states/alerts) at real now: {time.time() - t0:.1f}s")

    print(f"\nDone. {total_applied} events applied, {total_skipped} rejected by real validation across the run.")
    print(f"Agency display name: {args.agency_name} -- log in at / with that agency + PIN {cfg.DEFAULT_AGENCY_PIN}")


if __name__ == "__main__":
    main()
