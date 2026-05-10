"""Rebuild local SQLite DB with deterministic QA data.

This script is destructive and intended for local/customer-testing fixtures.
It creates multiple agency locations, multiple storages per location, and item
histories designed to exercise the location-level trend model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import select

from app.alerts.models import AlertRecords
from app.auth.models import (
    Agencies,
    AgencyDevices,
    AgencyEmails,
    AgencyItemTags,
    AgencyLocations,
    AgencyStorages,
)
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs, Items
from app.prediction.models import InventoryTrend
from app.shared.config import settings
from app.shared.database import create_all, get_session, init_db

LAST_COUNT_AT = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
SEGMENT_DAYS = 14


@dataclass(frozen=True)
class SeedItem:
    name: str
    min_quantity: int
    max_quantity: int
    batch_size: int
    lead_days: int | None
    prior_usage: float
    increments: str


@dataclass(frozen=True)
class TrendCase:
    item_name: str
    location_name: str
    start_total: int
    daily_delta: float
    segments: int
    correction_on_latest: bool = False
    post_count_takeout: int = 0


ITEMS = (
    SeedItem("Nitrile Gloves Box", 30, 220, 10, None, 6.0, "box"),
    SeedItem("Surgical Masks Pack", 40, 320, 25, None, 8.0, "pack"),
    SeedItem("IV Saline 500ml", 20, 160, 8, None, 3.5, "bag"),
    SeedItem("Epinephrine Auto-Injector", 8, 48, 2, 35, 0.4, "unit"),
    SeedItem("Burn Dressing Kit", 5, 40, 5, 7, 0.2, "kit"),
    SeedItem("Oxygen Tubing", 12, 100, 10, None, 2.0, "unit"),
    SeedItem("Sparse Fallback Item", 10, 60, 5, None, 1.5, "unit"),
    SeedItem("Disabled Legacy Item", 1, 20, 1, None, 0.1, "unit"),
)

TREND_CASES = (
    TrendCase(
        "Nitrile Gloves Box",
        "Point Boro NJ",
        1200,
        -5.5,
        12,
        correction_on_latest=True,
        post_count_takeout=24,
    ),
    TrendCase("Nitrile Gloves Box", "Lakewood NJ", 420, -2.0, 7, post_count_takeout=8),
    TrendCase("Surgical Masks Pack", "Point Boro NJ", 1600, -9.0, 10, post_count_takeout=60),
    TrendCase("Surgical Masks Pack", "Warehouse", 120, 2.5, 8),
    TrendCase("IV Saline 500ml", "Lakewood NJ", 700, -3.2, 9, correction_on_latest=True),
    TrendCase("Epinephrine Auto-Injector", "Point Boro NJ", 30, -0.15, 6),
    TrendCase("Burn Dressing Kit", "Warehouse", 18, 0.0, 5),
    TrendCase("Oxygen Tubing", "Lakewood NJ", 500, -7.0, 4, post_count_takeout=35),
    TrendCase("Sparse Fallback Item", "Point Boro NJ", 50, -2.0, 1),
)

SEED_TABLES = (
    Agencies,
    AgencyEmails,
    AgencyDevices,
    AgencyLocations,
    AgencyStorages,
    AgencyItemTags,
    Items,
    ActionLogs,
    AlertRecords,
    InventoryTrend,
)


def run() -> None:
    """Rebuild and populate the local SQLite database."""
    db_path = _reset_sqlite_database()
    logger.info("Preparing fresh QA database: {}", db_path)
    init_db(settings.database_url)
    create_all()
    _verify_empty()
    _populate()
    logger.info("QA seed complete")


def _reset_sqlite_database() -> Path:
    db_path = _resolve_sqlite_path(settings.database_url)
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _resolve_sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite" or not parsed.path:
        raise ValueError("setup_test_data only supports SQLite database URLs")
    return Path(parsed.path)


def _verify_empty() -> None:
    with get_session() as session:
        non_empty = {
            table.__tablename__: count
            for table in SEED_TABLES
            if (count := len(session.execute(select(table)).scalars().all())) > 0
        }
    if non_empty:
        raise RuntimeError(f"Expected empty seed tables, found rows: {non_empty}")


def _populate() -> None:
    with get_session() as session:
        agency = _create_agency(session)
        locations = _create_locations(session, agency.id)
        items = _create_items(session, agency.id)
        _create_tags(session, agency.id)
        _create_history(session, agency.id, items, locations)
        _create_secondary_agency(session)
        session.commit()


def _create_agency(session) -> Agencies:
    agency = Agencies(
        display_name="Point Boro EMS",
        email="point.boro.qa@gmail.com",
        pin="1111",
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=True,
        lead_time_days=21,
        alert_rare_scan_days=90,
        count_last_days=90,
    )
    agency.set_password("Passw0rd!Point")
    session.add(agency)
    session.flush()
    session.add(
        AgencyEmails(
            agency_id=agency.id,
            email="point.boro.alerts@gmail.com",
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
            weekly_summary=True,
            monthly_summary=True,
            yearly_summary=True,
        )
    )
    return agency


def _create_secondary_agency(session) -> None:
    agency = Agencies(
        display_name="Shoreline Backup Squad",
        email="shoreline.qa@gmail.com",
        pin="2222",
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=False,
    )
    agency.set_password("Passw0rd!Shore")
    session.add(agency)
    session.flush()
    location = AgencyLocations(agency_id=agency.id, name="Backup HQ")
    session.add(location)
    session.flush()
    session.add(AgencyStorages(agency_id=agency.id, location_id=location.id, name="Main Closet"))


def _create_locations(session, agency_id: int) -> dict[str, list[AgencyStorages]]:
    layout = {
        "Point Boro NJ": ("Shelf A", "Supply Cage", "Ambulance Bay"),
        "Lakewood NJ": ("Main Closet", "Narcotics Locker", "Medication Fridge"),
        "Warehouse": ("Receiving", "Overflow Rack"),
    }
    locations: dict[str, list[AgencyStorages]] = {}
    for location_name, storage_names in layout.items():
        location = AgencyLocations(agency_id=agency_id, name=location_name)
        session.add(location)
        session.flush()
        storages = [
            AgencyStorages(
                agency_id=agency_id,
                location_id=location.id,
                name=storage_name,
                user_access_from=storage_name != "Narcotics Locker",
                user_access_to=True,
            )
            for storage_name in storage_names
        ]
        session.add_all(storages)
        session.flush()
        locations[location_name] = storages
    return locations


def _create_items(session, agency_id: int) -> dict[str, Items]:
    created: dict[str, Items] = {}
    for seed in ITEMS:
        item = Items(
            agency_id=agency_id,
            name=seed.name,
            upc=None,
            active=seed.name != "Disabled Legacy Item",
            min_quantity=seed.min_quantity,
            max_quantity=seed.max_quantity,
            batch_size=seed.batch_size,
            restock_delivery_days=seed.lead_days,
            prior_daily_usage=seed.prior_usage,
            increments=seed.increments,
            tag_ids=[],
            last_accessed=LAST_COUNT_AT,
        )
        session.add(item)
        created[seed.name] = item
    session.flush()
    return created


def _create_tags(session, agency_id: int) -> None:
    session.add_all(
        [
            AgencyItemTags(agency_id=agency_id, tag_name="PPE", color="#2CA02C"),
            AgencyItemTags(agency_id=agency_id, tag_name="Medication", color="#1F77B4"),
            AgencyItemTags(agency_id=agency_id, tag_name="Critical", color="#D62728"),
            AgencyItemTags(agency_id=agency_id, tag_name="Low Velocity", color="#9467BD"),
        ]
    )


def _create_history(
    session,
    agency_id: int,
    items: dict[str, Items],
    locations: dict[str, list[AgencyStorages]],
) -> None:
    for case in TREND_CASES:
        item = items[case.item_name]
        storages = locations[case.location_name]
        counts = _totals(case.start_total, case.daily_delta, case.segments)
        for index, total in enumerate(counts):
            counted_at = LAST_COUNT_AT - timedelta(days=(len(counts) - index - 1) * SEGMENT_DAYS)
            _add_full_location_count(session, agency_id, item.id, storages, total, counted_at)

            if case.correction_on_latest and index == len(counts) - 1:
                _add_full_location_count(
                    session,
                    agency_id,
                    item.id,
                    storages,
                    max(total - 3, 0),
                    counted_at + timedelta(hours=2),
                )

        if case.post_count_takeout > 0:
            session.add(
                ActionLogs(
                    agency_id=agency_id,
                    item_id=item.id,
                    operation_type=OperationType.TAKEOUT,
                    from_location_id=storages[0].id,
                    to_location_id=None,
                    quantity_delta=case.post_count_takeout,
                    admin_action=False,
                    time_scanned=LAST_COUNT_AT + timedelta(hours=4),
                )
            )

    _add_stale_restock_blocker(
        session, agency_id, items["Epinephrine Auto-Injector"].id, locations["Lakewood NJ"]
    )


def _totals(start_total: int, daily_delta: float, segments: int) -> list[int]:
    return [
        max(round(start_total + daily_delta * SEGMENT_DAYS * index), 0)
        for index in range(segments + 1)
    ]


def _add_full_location_count(
    session,
    agency_id: int,
    item_id: int,
    storages: list[AgencyStorages],
    total_quantity: int,
    counted_at: datetime,
) -> None:
    quantities = _split_quantity(total_quantity, len(storages))
    for storage, quantity in zip(storages, quantities, strict=True):
        session.add(
            ActionLogs(
                agency_id=agency_id,
                item_id=item_id,
                operation_type=OperationType.COUNT,
                from_location_id=None,
                to_location_id=storage.id,
                quantity_delta=quantity,
                admin_action=True,
                time_scanned=counted_at,
            )
        )


def _split_quantity(total_quantity: int, buckets: int) -> list[int]:
    base = total_quantity // buckets
    remainder = total_quantity % buckets
    return [base + (1 if index < remainder else 0) for index in range(buckets)]


def _add_stale_restock_blocker(
    session,
    agency_id: int,
    item_id: int,
    storages: list[AgencyStorages],
) -> None:
    stale_time = LAST_COUNT_AT - timedelta(days=3)
    _add_full_location_count(session, agency_id, item_id, storages, 20, stale_time)


if __name__ == "__main__":
    run()
