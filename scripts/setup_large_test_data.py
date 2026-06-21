"""Build a separate large SQLite stress seed for local performance testing."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyEmails, AgencyItemTags, AgencyLocations, AgencyStorages
from app.inventory.balance_service import rebuild_inventory_balances
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs, InventoryBalances, Items
from app.prediction.models import InventoryTrend
from app.shared.database import create_all, get_session, init_db

DEFAULT_OUTPUT = Path("seed/2026-06-19_stress_large.db")
STRESS_AGENCY = "Stress Test EMS"
STRESS_EMAIL = "stress@example.com"
STRESS_PASSWORD = "Passw0rd!Stress"
STRESS_PIN = "1111"
STRESS_ALERT_EMAIL = "stress-alerts@example.com"
TAG_SPECS = (
    ("Airway", "#2563EB"),
    ("Cardiac", "#B91C1C"),
    ("Critical", "#DC2626"),
    ("Medication", "#0F766E"),
    ("PPE", "#15803D"),
    ("Trauma", "#C2410C"),
    ("Diagnostics", "#7C3AED"),
    ("Vehicle", "#475569"),
)
BASE_TIME = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class StressSeedConfig:
    """Volume controls for the large local stress seed."""

    item_count: int = 500
    location_count: int = 8
    storages_per_location: int = 5
    count_cycles: int = 6
    count_spacing_days: int = 28
    chunk_size: int = 5000


def build_large_seed(
    output_path: Path = DEFAULT_OUTPUT,
    config: StressSeedConfig | None = None,
) -> dict[str, Any]:
    """Create a deterministic large SQLite database for local performance benchmarks."""
    if config is None:
        config = StressSeedConfig()
    output_path = output_path.resolve()
    _reset_database(output_path)
    init_db(_sqlite_url(output_path))
    create_all()

    with get_session() as session:
        agency = _create_agency(session)
        tags = _create_tags(session, agency.id)
        _create_locations(session, agency.id, config)
        _create_items(session, agency.id, tags, config)
        session.commit()

    with get_session() as session:
        agency_id = _load_agency_id(session, STRESS_EMAIL)
        storages_by_location = _load_storages_by_location(session, agency_id=agency_id)
        item_ids = _load_item_ids(session, agency_id=agency_id)
        _insert_action_logs(session, agency_id=agency_id, item_ids=item_ids, storages_by_location=storages_by_location, config=config)
        _insert_trends(session, agency_id=agency_id, item_ids=item_ids, location_ids=list(storages_by_location), config=config)
        rebuild_inventory_balances(session, agency_id)
        session.commit()

    counts = _table_counts(output_path)
    summary = {
        "output_path": str(output_path),
        "config": asdict(config),
        "agency": {
            "display_name": STRESS_AGENCY,
            "email": STRESS_EMAIL,
            "pin": STRESS_PIN,
        },
        "counts": counts,
    }
    _write_metadata(output_path, summary)
    return summary


def _reset_database(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()


def _sqlite_url(output_path: Path) -> str:
    return f"sqlite:///{output_path.as_posix()}"


def _create_agency(session: Session) -> Agencies:
    agency = Agencies(
        display_name=STRESS_AGENCY,
        email=STRESS_EMAIL,
        pin=STRESS_PIN,
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=True,
        lead_time_days=21,
        alert_rare_scan_days=60,
        count_last_days=45,
    )
    agency.set_password(STRESS_PASSWORD)
    session.add(agency)
    session.flush()
    session.add(
        AgencyEmails(
            agency_id=agency.id,
            email=STRESS_ALERT_EMAIL,
            alert_for_stockout=True,
            alert_for_stockout_pred=True,
            alert_for_low=True,
            alert_for_low_pred=True,
            alert_for_stale_count=True,
            alert_for_rare_takeout=True,
            alert_for_count=True,
            alert_for_restock=True,
            alert_for_takeout=True,
            alert_for_transfer=True,
            daily_summary=True,
            weekly_summary=True,
            monthly_summary=True,
            yearly_summary=True,
        )
    )
    session.flush()
    return agency


def _create_tags(session: Session, agency_id: int) -> list[AgencyItemTags]:
    tags = [AgencyItemTags(agency_id=agency_id, tag_name=name, color=color) for name, color in TAG_SPECS]
    session.add_all(tags)
    session.flush()
    return tags


def _create_locations(
    session: Session,
    agency_id: int,
    config: StressSeedConfig,
) -> list[AgencyLocations]:
    locations: list[AgencyLocations] = []
    for location_index in range(1, config.location_count + 1):
        location = AgencyLocations(agency_id=agency_id, name=f"Station {location_index:02d}")
        session.add(location)
        session.flush()
        storages = [
            AgencyStorages(
                agency_id=agency_id,
                location_id=location.id,
                name=f"Shelf {storage_index:02d}",
                user_access_from=True,
                user_access_to=True,
            )
            for storage_index in range(1, config.storages_per_location + 1)
        ]
        session.add_all(storages)
        locations.append(location)
    session.flush()
    return locations


def _create_items(
    session: Session,
    agency_id: int,
    tags: list[AgencyItemTags],
    config: StressSeedConfig,
) -> list[Items]:
    items: list[Items] = []
    for item_index in range(1, config.item_count + 1):
        min_quantity = 10 + item_index % 25
        max_quantity = min_quantity * 4 + (item_index % 4) * 5
        item = Items(
            agency_id=agency_id,
            name=f"Stress Item {item_index:04d}",
            active=True,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            batch_size=5 + item_index % 6,
            restock_delivery_days=7 + item_index % 21,
            prior_daily_usage=round(0.2 + (item_index % 9) * 0.35, 2),
            guest_quick_adjust=item_index % 7 == 0,
            increments="unit",
            tag_ids=_item_tag_ids(item_index, tags),
            last_accessed=BASE_TIME - timedelta(minutes=item_index),
        )
        session.add(item)
        items.append(item)
    session.flush()
    return items


def _item_tag_ids(item_index: int, tags: list[AgencyItemTags]) -> list[int]:
    first = tags[item_index % len(tags)].id
    second = tags[(item_index * 3) % len(tags)].id
    if first == second:
        return [first]
    return [first, second]


def _load_storages_by_location(session: Session, agency_id: int) -> dict[int, list[AgencyStorages]]:
    storages = list(
        session.execute(select(AgencyStorages).where(AgencyStorages.agency_id == agency_id).order_by(AgencyStorages.location_id, AgencyStorages.name))
        .scalars()
        .all()
    )
    by_location: dict[int, list[AgencyStorages]] = {}
    for storage in storages:
        by_location.setdefault(storage.location_id, []).append(storage)
    return by_location


def _load_agency_id(session: Session, email: str) -> int:
    agency_id = session.scalar(select(Agencies.id).where(Agencies.email == email))
    if agency_id is None:
        raise RuntimeError(f"Stress seed agency not found for {email}")
    return int(agency_id)


def _load_item_ids(session: Session, agency_id: int) -> list[int]:
    return list(session.execute(select(Items.id).where(Items.agency_id == agency_id).order_by(Items.id)).scalars().all())


def _insert_action_logs(
    session: Session,
    agency_id: int,
    item_ids: list[int],
    storages_by_location: dict[int, list[AgencyStorages]],
    config: StressSeedConfig,
) -> None:
    rows: list[dict[str, Any]] = []
    for item_offset, item_id in enumerate(item_ids, start=1):
        for location_offset, (location_id, storages) in enumerate(storages_by_location.items(), start=1):
            rows.extend(_count_rows_for_item_location(agency_id, item_id, item_offset, location_offset, storages, config))
            rows.extend(_activity_rows_for_item_location(agency_id, item_id, item_offset, location_offset, location_id, storages))
            if len(rows) >= config.chunk_size:
                session.execute(insert(ActionLogs), rows)
                rows.clear()
    if rows:
        session.execute(insert(ActionLogs), rows)


def _count_rows_for_item_location(
    agency_id: int,
    item_id: int,
    item_offset: int,
    location_offset: int,
    storages: list[AgencyStorages],
    config: StressSeedConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    storage_count = len(storages)
    base_total = 60 + (item_offset % 40) * 3 + location_offset * 5
    for cycle in range(config.count_cycles):
        counted_at = BASE_TIME - timedelta(days=(config.count_cycles - cycle) * config.count_spacing_days)
        total = max(base_total + cycle * ((item_offset + location_offset) % 4) - cycle * 2, storage_count)
        for storage, quantity in zip(storages, _split_quantity(total, storage_count), strict=True):
            rows.append(
                {
                    "agency_id": agency_id,
                    "item_id": item_id,
                    "operation_type": OperationType.COUNT,
                    "from_location_id": None,
                    "to_location_id": storage.id,
                    "quantity_delta": quantity,
                    "admin_action": True,
                    "time_scanned": counted_at,
                }
            )
    return rows


def _activity_rows_for_item_location(
    agency_id: int,
    item_id: int,
    item_offset: int,
    location_offset: int,
    location_id: int,
    storages: list[AgencyStorages],
) -> list[dict[str, Any]]:
    primary = storages[0]
    secondary = storages[min(1, len(storages) - 1)]
    transfer_from = storages[-1]
    transfer_to = storages[0]
    days_back = (item_offset + location_offset) % 17
    rows = [
        {
            "agency_id": agency_id,
            "item_id": item_id,
            "operation_type": OperationType.TAKEOUT,
            "from_location_id": primary.id,
            "to_location_id": None,
            "quantity_delta": 1 + (item_offset + location_offset) % 4,
            "admin_action": False,
            "time_scanned": BASE_TIME - timedelta(days=days_back, hours=location_offset),
        },
        {
            "agency_id": agency_id,
            "item_id": item_id,
            "operation_type": OperationType.RESTOCK,
            "from_location_id": None,
            "to_location_id": secondary.id,
            "quantity_delta": 2 + (item_offset * 2 + location_offset) % 7,
            "admin_action": True,
            "time_scanned": BASE_TIME - timedelta(days=max(days_back - 2, 0), hours=item_offset % 12),
        },
    ]
    if len(storages) > 1 and (item_offset + location_id) % 3 == 0:
        rows.append(
            {
                "agency_id": agency_id,
                "item_id": item_id,
                "operation_type": OperationType.TRANSFER,
                "from_location_id": transfer_from.id,
                "to_location_id": transfer_to.id,
                "quantity_delta": 1 + (item_offset + location_offset) % 3,
                "admin_action": True,
                "time_scanned": BASE_TIME - timedelta(days=max(days_back - 1, 0), hours=6),
            }
        )
    return rows


def _insert_trends(
    session: Session,
    agency_id: int,
    item_ids: list[int],
    location_ids: list[int],
    config: StressSeedConfig,
) -> None:
    rows: list[dict[str, Any]] = []
    for item_offset, item_id in enumerate(item_ids, start=1):
        for location_offset, location_id in enumerate(location_ids, start=1):
            trend = round(-0.15 - ((item_offset + location_offset) % 11) * 0.18, 4)
            confidence = float(min(95, 55 + ((item_offset * location_offset) % 40)))
            rows.append(
                {
                    "agency_id": agency_id,
                    "item_id": item_id,
                    "agency_location_id": location_id,
                    "trend_per_day": trend,
                    "confidence_percent": confidence,
                    "segment_count": max(config.count_cycles - 1, 1),
                    "data_signature": hashlib.sha256(f"stress:{item_id}:{location_id}".encode()).hexdigest(),
                    "trained_at": BASE_TIME,
                }
            )
            if len(rows) >= config.chunk_size:
                session.execute(insert(InventoryTrend), rows)
                rows.clear()
    if rows:
        session.execute(insert(InventoryTrend), rows)


def _split_quantity(total: int, bucket_count: int) -> list[int]:
    base = total // bucket_count
    remainder = total % bucket_count
    return [base + (1 if index < remainder else 0) for index in range(bucket_count)]


def _table_counts(output_path: Path) -> dict[str, int]:
    init_db(_sqlite_url(output_path))
    with get_session() as session:
        return {
            "agencies": _count(session, Agencies),
            "agency_emails": _count(session, AgencyEmails),
            "agency_locations": _count(session, AgencyLocations),
            "agency_storages": _count(session, AgencyStorages),
            "agency_item_tags": _count(session, AgencyItemTags),
            "items": _count(session, Items),
            "action_logs": _count(session, ActionLogs),
            "inventory_trends": _count(session, InventoryTrend),
            "inventory_balances": _count(session, InventoryBalances),
        }


def _count(session: Session, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _write_metadata(output_path: Path, summary: dict[str, Any]) -> None:
    metadata_path = output_path.with_suffix(f"{output_path.suffix}.meta.json")
    metadata_path.write_text(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a separate large SQLite stress seed database.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="SQLite database file to create")
    parser.add_argument("--items", type=int, default=StressSeedConfig.item_count, help="Number of active items")
    parser.add_argument("--locations", type=int, default=StressSeedConfig.location_count, help="Number of locations")
    parser.add_argument("--storages", type=int, default=StressSeedConfig.storages_per_location, help="Storages per location")
    parser.add_argument("--count-cycles", type=int, default=StressSeedConfig.count_cycles, help="Historical full-count cycles per item/location")
    parser.add_argument("--count-spacing-days", type=int, default=StressSeedConfig.count_spacing_days, help="Days between historical count cycles")
    parser.add_argument("--chunk-size", type=int, default=StressSeedConfig.chunk_size, help="Bulk insert chunk size")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = StressSeedConfig(
        item_count=args.items,
        location_count=args.locations,
        storages_per_location=args.storages,
        count_cycles=args.count_cycles,
        count_spacing_days=args.count_spacing_days,
        chunk_size=args.chunk_size,
    )
    summary = build_large_seed(args.output, config)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
