"""Rebuild local SQLite DB with deterministic EMS demo data."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.alert_service import record_action_log_alerts
from app.alerts.models import AlertRecords
from app.auth.models import (
    Agencies,
    AgencyDevices,
    AgencyEmails,
    AgencyItemTags,
    AgencyLocations,
    AgencyStorages,
)
from app.inventory.balance_service import rebuild_inventory_balances
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs, Items
from app.prediction.models import InventoryTrend
from app.prediction.usage_model import train_location_trend
from app.shared.config import settings
from app.shared.database import create_all, get_session, init_db

MAIN_AGENCY = "Point Boro EMS"
MAIN_EMAIL = "mattmammanoweb@gmail.com"
ALERT_EMAIL = "mattmammano@gmail.com"
MAIN_PASSWORD = "Passw0rd!Point"
MAIN_PIN = "1111"
LAST_COUNT_AT = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
SEGMENT_DAYS = 14
POINT_BORO = "Point Boro EMS"
POINT_BEACH = "Point Beach EMS"
STORAGES = ("Back Closet", "Shelf")


@dataclass(frozen=True)
class ItemSeed:
    """Demo item definition for the main agency."""

    name: str
    min_quantity: int
    max_quantity: int
    batch_size: int
    prior_daily_usage: float
    restock_days: int | None = None
    increments: str = "unit"
    tags: tuple[str, ...] = ()
    guest_quick_adjust: bool = False


@dataclass(frozen=True)
class TrendSeed:
    """Count-history shape used to train one item/location trend."""

    item_name: str
    location_name: str
    first_total: int
    daily_delta: float
    segments: int
    after_count_takeout: int = 0
    after_count_restock: int = 0


ITEMS = (
    ItemSeed(
        "Nitrile Gloves - Large Box",
        40,
        240,
        10,
        7.0,
        tags=("PPE",),
        guest_quick_adjust=True,
    ),
    ItemSeed("Trauma Dressing 5x9", 24, 144, 12, 3.0, tags=("Trauma", "Critical")),
    ItemSeed("Epinephrine Auto-Injector", 8, 40, 2, 0.35, 35, tags=("Medication", "Critical")),
    ItemSeed("Adult AED Pads", 4, 24, 2, 0.12, 45, tags=("Cardiac", "Critical")),
    ItemSeed("Oxygen Nasal Cannula", 30, 180, 10, 2.5, tags=("Airway",)),
    ItemSeed("Glucometer Test Strips", 12, 72, 6, 0.6, tags=("Medication",)),
    ItemSeed("SAM Splint Roll", 6, 36, 3, 0.05, tags=("Trauma",)),
    ItemSeed("Saline Flush 10ml", 50, 300, 25, 6.5, tags=("Medication",), guest_quick_adjust=True),
    ItemSeed("Demo Disabled Legacy Item", 1, 10, 1, 0.1),
)

TREND_SEEDS = (
    TrendSeed("Nitrile Gloves - Large Box", POINT_BORO, 620, -1.4, 16, after_count_takeout=18),
    TrendSeed("Nitrile Gloves - Large Box", POINT_BEACH, 360, -0.7, 12),
    TrendSeed("Trauma Dressing 5x9", POINT_BORO, 560, -2.2, 14, after_count_takeout=12),
    TrendSeed("Trauma Dressing 5x9", POINT_BEACH, 260, -1.1, 10, after_count_restock=24),
    TrendSeed("Epinephrine Auto-Injector", POINT_BORO, 130, -0.45, 12),
    TrendSeed("Epinephrine Auto-Injector", POINT_BEACH, 36, -0.2, 8),
    TrendSeed("Adult AED Pads", POINT_BORO, 48, -0.25, 10),
    TrendSeed("Oxygen Nasal Cannula", POINT_BORO, 220, -1.2, 8),
    TrendSeed("Oxygen Nasal Cannula", POINT_BEACH, 420, -1.8, 10),
    TrendSeed("Glucometer Test Strips", POINT_BORO, 52, -0.1, 8),
    TrendSeed("SAM Splint Roll", POINT_BEACH, 34, 0.0, 8),
    TrendSeed("Saline Flush 10ml", POINT_BORO, 900, -5.2, 18, after_count_takeout=75),
    TrendSeed("Saline Flush 10ml", POINT_BEACH, 420, -2.4, 12),
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
    """Rebuild and populate the local SQLite demo database."""
    db_path = _reset_sqlite_database()
    logger.debug(f"Preparing fresh demo database at {db_path}")
    init_db(settings.database_url)
    create_all()
    _verify_empty()
    _populate()
    logger.info("Demo data seed finished")


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
        non_empty = {table.__tablename__: count for table in SEED_TABLES if (count := session.scalar(select(table.id).limit(1))) is not None}
    if non_empty:
        raise RuntimeError(f"Expected empty seed tables, found rows: {non_empty}")


def _populate() -> None:
    with get_session() as session:
        agency = _create_main_agency(session)
        tags = _create_tags(session, agency.id)
        locations = _create_main_locations(session, agency.id)
        items = _create_items(session, agency.id, tags)
        _create_main_history(session, agency.id, items, locations)
        session.flush()
        _create_scan_activity_alerts(session, agency.id)
        _create_isolation_agencies(session)
        _train_main_trends(session, agency.id, items, locations)
        rebuild_inventory_balances(session)
        session.commit()


def _create_main_agency(session: Session) -> Agencies:
    agency = Agencies(
        display_name=MAIN_AGENCY,
        email=MAIN_EMAIL,
        pin=MAIN_PIN,
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=True,
        lead_time_days=21,
        alert_rare_scan_days=45,
        count_last_days=30,
    )
    agency.set_password(MAIN_PASSWORD)
    session.add(agency)
    session.flush()
    session.add(
        AgencyEmails(
            agency_id=agency.id,
            email=ALERT_EMAIL,
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
    return agency


def _create_tags(session: Session, agency_id: int) -> dict[str, AgencyItemTags]:
    tag_specs = {
        "Airway": "#2563EB",
        "Cardiac": "#B91C1C",
        "Critical": "#DC2626",
        "Medication": "#0F766E",
        "PPE": "#15803D",
        "Trauma": "#C2410C",
    }
    tags = {name: AgencyItemTags(agency_id=agency_id, tag_name=name, color=color) for name, color in tag_specs.items()}
    session.add_all(tags.values())
    session.flush()
    return tags


def _create_main_locations(session: Session, agency_id: int) -> dict[str, list[AgencyStorages]]:
    layout = {
        POINT_BORO: STORAGES,
        POINT_BEACH: STORAGES,
    }
    return _create_locations(session, agency_id, layout)


def _create_locations(session: Session, agency_id: int, layout: Mapping[str, Sequence[str]]) -> dict[str, list[AgencyStorages]]:
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
                user_access_from=True,
                user_access_to=True,
            )
            for storage_name in storage_names
        ]
        session.add_all(storages)
        session.flush()
        locations[location_name] = storages
    return locations


def _create_items(session: Session, agency_id: int, tags: dict[str, AgencyItemTags]) -> dict[str, Items]:
    items: dict[str, Items] = {}
    for seed in ITEMS:
        item = Items(
            agency_id=agency_id,
            name=seed.name,
            active=not seed.name.startswith("Demo Disabled"),
            min_quantity=seed.min_quantity,
            max_quantity=seed.max_quantity,
            batch_size=seed.batch_size,
            restock_delivery_days=seed.restock_days,
            prior_daily_usage=seed.prior_daily_usage,
            guest_quick_adjust=seed.guest_quick_adjust,
            increments=seed.increments,
            tag_ids=[tags[tag].id for tag in seed.tags],
            last_accessed=LAST_COUNT_AT,
        )
        session.add(item)
        items[seed.name] = item
    session.flush()
    return items


def _create_main_history(
    session: Session,
    agency_id: int,
    items: dict[str, Items],
    locations: dict[str, list[AgencyStorages]],
) -> None:
    for trend in TREND_SEEDS:
        _add_trend_history(session, agency_id, items[trend.item_name], locations, trend)

    _add_current_stockout(session, agency_id, items["Trauma Dressing 5x9"], locations[POINT_BORO])
    _add_current_low(session, agency_id, items["Oxygen Nasal Cannula"], locations[POINT_BORO])
    _add_sparse_fallback(session, agency_id, items["SAM Splint Roll"], locations[POINT_BORO])
    _add_stale_count_case(session, agency_id, items["Glucometer Test Strips"], locations[POINT_BEACH])
    _add_rare_takeout_case(session, agency_id, items["Glucometer Test Strips"], locations[POINT_BORO])
    _add_transfer_case(session, agency_id, items["Nitrile Gloves - Large Box"], locations)
    _add_missing_safe_counts(session, agency_id, items, locations)


def _add_trend_history(
    session: Session,
    agency_id: int,
    item: Items,
    locations: dict[str, list[AgencyStorages]],
    trend: TrendSeed,
) -> None:
    storages = locations[trend.location_name]
    for index in range(trend.segments + 1):
        counted_at = LAST_COUNT_AT - timedelta(days=(trend.segments - index) * SEGMENT_DAYS)
        total = max(round(trend.first_total + trend.daily_delta * SEGMENT_DAYS * index), 0)
        _add_location_count(session, agency_id, item.id, storages, total, counted_at)

    if trend.after_count_takeout:
        _add_action(
            session,
            agency_id,
            item.id,
            OperationType.TAKEOUT,
            storages[0].id,
            None,
            trend.after_count_takeout,
            LAST_COUNT_AT + timedelta(hours=2),
            admin=False,
        )
    if trend.after_count_restock:
        _add_action(
            session,
            agency_id,
            item.id,
            OperationType.RESTOCK,
            None,
            storages[0].id,
            trend.after_count_restock,
            LAST_COUNT_AT + timedelta(hours=3),
            admin=True,
        )


def _add_current_stockout(session: Session, agency_id: int, item: Items, storages: list[AgencyStorages]) -> None:
    _add_location_count(session, agency_id, item.id, storages, 8, LAST_COUNT_AT)
    _add_action(
        session,
        agency_id,
        item.id,
        OperationType.TAKEOUT,
        storages[0].id,
        None,
        10,
        LAST_COUNT_AT + timedelta(hours=4),
        admin=False,
    )


def _add_current_low(session: Session, agency_id: int, item: Items, storages: list[AgencyStorages]) -> None:
    _add_location_count(session, agency_id, item.id, storages, 18, LAST_COUNT_AT)


def _add_sparse_fallback(session: Session, agency_id: int, item: Items, storages: list[AgencyStorages]) -> None:
    old_at = LAST_COUNT_AT - timedelta(days=28)
    _add_location_count(session, agency_id, item.id, storages, 56, old_at)
    _add_location_count(session, agency_id, item.id, storages, 35, LAST_COUNT_AT)


def _add_stale_count_case(session: Session, agency_id: int, item: Items, storages: list[AgencyStorages]) -> None:
    _add_location_count(
        session,
        agency_id,
        item.id,
        storages,
        28,
        LAST_COUNT_AT - timedelta(days=62),
    )


def _add_rare_takeout_case(session: Session, agency_id: int, item: Items, storages: list[AgencyStorages]) -> None:
    _add_location_count(session, agency_id, item.id, storages, 30, LAST_COUNT_AT)
    _add_action(
        session,
        agency_id,
        item.id,
        OperationType.TAKEOUT,
        storages[0].id,
        None,
        2,
        LAST_COUNT_AT - timedelta(days=73),
        admin=False,
    )


def _add_transfer_case(
    session: Session,
    agency_id: int,
    item: Items,
    locations: dict[str, list[AgencyStorages]],
) -> None:
    _add_action(
        session,
        agency_id,
        item.id,
        OperationType.TRANSFER,
        locations[POINT_BEACH][0].id,
        locations[POINT_BORO][1].id,
        20,
        LAST_COUNT_AT + timedelta(hours=5),
        admin=True,
    )


def _add_missing_safe_counts(
    session: Session,
    agency_id: int,
    items: dict[str, Items],
    locations: dict[str, list[AgencyStorages]],
) -> None:
    session.flush()
    for item in items.values():
        if not item.active:
            continue
        safe_total = max(item.min_quantity * 2, item.max_quantity // 2)
        for storages in locations.values():
            if not _has_location_count(session, agency_id, item.id, storages):
                _add_location_count(session, agency_id, item.id, storages, safe_total, LAST_COUNT_AT)


def _has_location_count(
    session: Session,
    agency_id: int,
    item_id: int,
    storages: list[AgencyStorages],
) -> bool:
    storage_ids = [storage.id for storage in storages]
    return (
        session.scalar(
            select(ActionLogs.id)
            .where(
                ActionLogs.agency_id == agency_id,
                ActionLogs.item_id == item_id,
                ActionLogs.operation_type == OperationType.COUNT,
                ActionLogs.to_location_id.in_(storage_ids),
            )
            .limit(1)
        )
        is not None
    )


def _add_location_count(
    session: Session,
    agency_id: int,
    item_id: int,
    storages: list[AgencyStorages],
    total: int,
    counted_at: datetime,
) -> None:
    for storage, quantity in zip(storages, _split_quantity(total, len(storages)), strict=True):
        _add_action(
            session,
            agency_id,
            item_id,
            OperationType.COUNT,
            None,
            storage.id,
            quantity,
            counted_at,
            admin=True,
        )


def _add_action(
    session: Session,
    agency_id: int,
    item_id: int,
    operation: OperationType,
    from_storage_id: int | None,
    to_storage_id: int | None,
    quantity: int,
    scanned_at: datetime,
    *,
    admin: bool,
) -> None:
    session.add(
        ActionLogs(
            agency_id=agency_id,
            item_id=item_id,
            operation_type=operation,
            from_location_id=from_storage_id,
            to_location_id=to_storage_id,
            quantity_delta=quantity,
            admin_action=admin,
            time_scanned=scanned_at,
        )
    )


def _split_quantity(total: int, bucket_count: int) -> list[int]:
    base = total // bucket_count
    remainder = total % bucket_count
    return [base + (1 if index < remainder else 0) for index in range(bucket_count)]


def _create_isolation_agencies(session: Session) -> None:
    _create_small_agency(
        session,
        "Lakewood EMS Demo",
        "mattmammanoweb+lakewood@gmail.com",
        "2222",
        "Lakewood HQ",
        "Main Closet",
    )
    _create_small_agency(
        session,
        "Seaside Rescue Demo",
        "mattmammano+seaside@gmail.com",
        "3333",
        "Seaside HQ",
        "Rig Cabinet",
    )


def _create_small_agency(
    session: Session,
    name: str,
    email: str,
    pin: str,
    location_name: str,
    storage_name: str,
) -> None:
    agency = Agencies(
        display_name=name,
        email=email,
        pin=pin,
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=False,
        lead_time_days=21,
        alert_rare_scan_days=45,
        count_last_days=30,
    )
    agency.set_password("Passw0rd!Demo")
    session.add(agency)
    session.flush()
    locations = _create_locations(session, agency.id, {location_name: (storage_name,)})
    item = Items(
        agency_id=agency.id,
        name="Isolation Check Item",
        active=True,
        min_quantity=2,
        max_quantity=10,
        batch_size=1,
        prior_daily_usage=0.1,
        increments="unit",
        tag_ids=[],
        last_accessed=LAST_COUNT_AT,
    )
    session.add(item)
    session.flush()
    _add_location_count(session, agency.id, item.id, locations[location_name], 5, LAST_COUNT_AT)


def _create_scan_activity_alerts(session: Session, agency_id: int) -> None:
    wanted = {
        OperationType.COUNT,
        OperationType.RESTOCK,
        OperationType.TAKEOUT,
        OperationType.TRANSFER,
    }
    selected: dict[OperationType, ActionLogs] = {}
    actions = session.execute(
        select(ActionLogs).where(ActionLogs.agency_id == agency_id).order_by(ActionLogs.time_scanned.desc(), ActionLogs.id.desc())
    ).scalars()
    for action in actions:
        if action.operation_type in wanted and action.operation_type not in selected:
            selected[action.operation_type] = action
        if len(selected) == len(wanted):
            break
    record_action_log_alerts(session, list(selected.values()))


def _train_main_trends(
    session: Session,
    agency_id: int,
    items: dict[str, Items],
    locations: dict[str, list[AgencyStorages]],
) -> None:
    location_ids = {storage.location_id for storages in locations.values() for storage in storages}
    for item in items.values():
        if item.active:
            for location_id in location_ids:
                train_location_trend(session, agency_id, item.id, location_id)


if __name__ == "__main__":
    run()
