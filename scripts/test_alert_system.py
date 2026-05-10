"""End-to-end QA runner for inventory alert generation and delivery.

This is intentionally a script, not pytest, because the repo has no test
framework yet and the output is meant to be readable during local QA.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.config import settings

TEST_DB = Path("instance/alert_system_test.db")
START_AT = datetime(2026, 5, 10, 6, 0, tzinfo=UTC)

settings.database_url = f"sqlite:///{TEST_DB.as_posix()}"
settings.mail_server = ""
settings.mail_username = ""
settings.mail_password = ""
settings.mail_default_sender = ""
settings.dev_clock_enabled = True
settings.scheduler_enabled = False

from app import create_app  # noqa: E402
from app.alerts.alert_service import (  # noqa: E402
    generate_scheduled_alerts,
    record_action_log_alerts,
)
from app.alerts.constants import AlertAction, AlertType  # noqa: E402
from app.alerts.email_service import process_all_alerts  # noqa: E402
from app.alerts.models import AlertRecords  # noqa: E402
from app.auth.models import Agencies, AgencyEmails, AgencyLocations, AgencyStorages  # noqa: E402
from app.inventory.constants import OperationType  # noqa: E402
from app.inventory.models import ActionLogs, Items  # noqa: E402
from app.prediction.estimator import get_location_item_quantity  # noqa: E402
from app.prediction.models import InventoryTrend  # noqa: E402
from app.shared.clock import CLOCK_FILE, utc_now  # noqa: E402
from app.shared.database import create_all, get_session  # noqa: E402


@dataclass(frozen=True)
class AlertTestContext:
    agency_id: int
    hq_location_id: int
    main_storage_id: int
    shelf_storage_id: int
    items: dict[str, int]


def main() -> None:
    """Run the full alert QA suite against an isolated SQLite database."""
    _reset_environment()
    app = create_app()
    try:
        with app.app_context():
            create_all()
            initial_files = _alert_files()
            ctx = _seed_database()
            _create_runtime_alerts(ctx)
            _assert_generated_alerts(ctx)
            _assert_no_email_before_due(initial_files)
            early_files = _assert_early_stockout_email(initial_files)
            _assert_daily_scan_email(initial_files | early_files)
            _assert_final_state()
        logger.info("Alert system QA completed successfully")
    finally:
        _reset_clock()


def _reset_environment() -> None:
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    TEST_DB.unlink(missing_ok=True)
    _set_clock(START_AT)


def _seed_database() -> AlertTestContext:
    with get_session() as session:
        agency = _create_agency(session)
        hq = _create_location(session, agency.id, "Alert HQ")
        storages = {
            "main": _create_storage(session, agency.id, hq.id, "Main Shelf"),
            "shelf": _create_storage(session, agency.id, hq.id, "Overflow Shelf"),
        }
        items = _create_items(session, agency.id)
        session.flush()
        _seed_counts(session, agency.id, storages, items)
        _seed_trends(session, agency.id, hq.id, items)
        session.commit()
        return AlertTestContext(
            agency_id=agency.id,
            hq_location_id=hq.id,
            main_storage_id=storages["main"].id,
            shelf_storage_id=storages["shelf"].id,
            items={name: item.id for name, item in items.items()},
        )


def _create_agency(session: Session) -> Agencies:
    agency = Agencies(
        display_name="Alert QA Squad",
        email="alert.qa.squad@gmail.com",
        pin="1111",
        timezone="America/New_York",
        active=True,
        user_count_allow=True,
        user_restock_allow=True,
        lead_time_days=21,
        alert_rare_scan_days=30,
        count_last_days=5,
    )
    agency.set_password("Passw0rd!Alerts")
    session.add(agency)
    session.flush()
    session.add_all(
        [
            _recipient(agency.id, "all.alert.qa@gmail.com", include_all=True),
            _recipient(agency.id, "stock.alert.qa@gmail.com", include_all=False),
        ]
    )
    return agency


def _recipient(agency_id: int, email: str, *, include_all: bool) -> AgencyEmails:
    return AgencyEmails(
        agency_id=agency_id,
        email=email,
        alert_for_stockout=True,
        alert_for_stockout_pred=True,
        alert_for_low=True,
        alert_for_low_pred=True,
        alert_for_stale_count=include_all,
        alert_for_rare_takeout=include_all,
        alert_for_count=include_all,
        alert_for_restock=include_all,
        alert_for_takeout=include_all,
        alert_for_transfer=include_all,
    )


def _create_location(session: Session, agency_id: int, name: str) -> AgencyLocations:
    location = AgencyLocations(agency_id=agency_id, name=name)
    session.add(location)
    session.flush()
    return location


def _create_storage(
    session: Session,
    agency_id: int,
    location_id: int,
    name: str,
) -> AgencyStorages:
    storage = AgencyStorages(agency_id=agency_id, location_id=location_id, name=name)
    session.add(storage)
    session.flush()
    return storage


def _create_items(session: Session, agency_id: int) -> dict[str, Items]:
    specs = {
        "Stockout Negative": (5, None, 0.0),
        "Low Crossing": (10, None, 0.0),
        "Cleared Stockout": (5, None, 0.0),
        "Pred Stockout Override": (5, 14, 0.0),
        "Pred Low Default": (25, None, 0.0),
        "Pred Both Suppression": (5, None, 0.0),
        "Fallback Pred Stockout": (5, None, 1.0),
        "Stale Count": (5, None, 0.0),
        "Never Counted": (5, None, 0.0),
        "Rare Takeout": (5, None, 0.0),
        "Old Transfer Only": (5, None, 0.0),
        "Recent Takeout": (5, None, 0.0),
        "Scan Count": (5, None, 0.0),
        "Scan Restock": (5, None, 0.0),
        "Scan Takeout": (5, None, 0.0),
        "Scan Transfer": (5, None, 0.0),
        "Healthy No Alert": (5, None, 0.0),
    }
    items = {
        name: Items(
            agency_id=agency_id,
            name=name,
            active=True,
            min_quantity=min_quantity,
            max_quantity=100,
            batch_size=5,
            restock_delivery_days=lead_days,
            prior_daily_usage=prior_usage,
            increments="unit",
            tag_ids=[],
            last_accessed=START_AT,
        )
        for name, (min_quantity, lead_days, prior_usage) in specs.items()
    }
    session.add_all(items.values())
    session.flush()
    return items


def _seed_counts(
    session: Session,
    agency_id: int,
    storages: dict[str, AgencyStorages],
    items: dict[str, Items],
) -> None:
    recent = START_AT - timedelta(days=1)
    old = START_AT - timedelta(days=12)
    count_quantities = {
        "Stockout Negative": 3,
        "Low Crossing": 12,
        "Cleared Stockout": 2,
        "Pred Stockout Override": 10,
        "Pred Low Default": 40,
        "Pred Both Suppression": 10,
        "Fallback Pred Stockout": 10,
        "Stale Count": 40,
        "Rare Takeout": 20,
        "Old Transfer Only": 20,
        "Recent Takeout": 20,
        "Scan Count": 20,
        "Scan Restock": 20,
        "Scan Takeout": 20,
        "Scan Transfer": 20,
        "Healthy No Alert": 20,
    }
    for name, quantity in count_quantities.items():
        counted_at = old if name == "Stale Count" else recent
        _add_log(
            session,
            agency_id,
            items[name].id,
            OperationType.COUNT,
            quantity,
            counted_at,
            None,
            storages["main"].id,
        )

    _add_log(
        session,
        agency_id,
        items["Rare Takeout"].id,
        OperationType.TAKEOUT,
        1,
        START_AT - timedelta(days=35),
        storages["main"].id,
        None,
    )
    _add_log(
        session,
        agency_id,
        items["Old Transfer Only"].id,
        OperationType.TRANSFER,
        1,
        START_AT - timedelta(days=35),
        storages["main"].id,
        storages["shelf"].id,
    )
    _add_log(
        session,
        agency_id,
        items["Recent Takeout"].id,
        OperationType.TAKEOUT,
        1,
        START_AT - timedelta(days=10),
        storages["main"].id,
        None,
    )


def _seed_trends(
    session: Session,
    agency_id: int,
    hq_location_id: int,
    items: dict[str, Items],
) -> None:
    trend_specs = {
        "Pred Stockout Override": (-1.0, 80, "override"),
        "Pred Low Default": (-1.0, 70, "default-low"),
        "Pred Both Suppression": (-1.0, 90, "both"),
        "Healthy No Alert": (0.25, 60, "healthy"),
    }
    session.add_all(
        InventoryTrend(
            agency_id=agency_id,
            item_id=items[name].id,
            agency_location_id=hq_location_id,
            trend_per_day=trend,
            confidence_percent=confidence,
            segment_count=6,
            data_signature=signature,
        )
        for name, (trend, confidence, signature) in trend_specs.items()
    )


def _create_runtime_alerts(ctx: AlertTestContext) -> None:
    _set_clock(START_AT)
    with get_session() as session:
        _scan(
            session,
            ctx,
            "Stockout Negative",
            OperationType.TAKEOUT,
            5,
            from_id=ctx.main_storage_id,
        )
        _scan(session, ctx, "Low Crossing", OperationType.TAKEOUT, 5, from_id=ctx.main_storage_id)
        _scan(
            session,
            ctx,
            "Cleared Stockout",
            OperationType.TAKEOUT,
            2,
            from_id=ctx.main_storage_id,
        )
        _scan(session, ctx, "Cleared Stockout", OperationType.COUNT, 10, to_id=ctx.main_storage_id)
        _scan(session, ctx, "Scan Count", OperationType.COUNT, 21, to_id=ctx.main_storage_id)
        _scan(session, ctx, "Scan Restock", OperationType.RESTOCK, 3, to_id=ctx.main_storage_id)
        _scan(session, ctx, "Scan Takeout", OperationType.TAKEOUT, 2, from_id=ctx.main_storage_id)
        _scan(
            session,
            ctx,
            "Scan Transfer",
            OperationType.TRANSFER,
            4,
            from_id=ctx.main_storage_id,
            to_id=ctx.shelf_storage_id,
        )
        generate_scheduled_alerts(session, ctx.agency_id)
        session.commit()


def _scan(
    session: Session,
    ctx: AlertTestContext,
    item_name: str,
    operation_type: OperationType,
    quantity: int,
    *,
    from_id: int | None = None,
    to_id: int | None = None,
) -> None:
    item_id = ctx.items[item_name]
    before = _location_snapshots(session, ctx.agency_id, item_id, from_id, to_id)
    action = _add_log(
        session, ctx.agency_id, item_id, operation_type, quantity, utc_now(), from_id, to_id
    )
    after = _updated_snapshots(session, ctx.agency_id, item_id, before)
    record_action_log_alerts(session, [action], after)


def _location_snapshots(
    session: Session,
    agency_id: int,
    item_id: int,
    from_id: int | None,
    to_id: int | None,
) -> dict[int, int]:
    location_ids = {
        storage.location_id
        for storage_id in (from_id, to_id)
        if storage_id and (storage := session.get(AgencyStorages, storage_id))
    }
    return {
        location_id: get_location_item_quantity(session, agency_id, item_id, location_id)
        for location_id in location_ids
    }


def _updated_snapshots(
    session: Session,
    agency_id: int,
    item_id: int,
    previous: dict[int, int],
) -> dict[tuple[int, int, int], tuple[int, int]]:
    return {
        (agency_id, item_id, location_id): (
            before,
            get_location_item_quantity(session, agency_id, item_id, location_id),
        )
        for location_id, before in previous.items()
    }


def _add_log(
    session: Session,
    agency_id: int,
    item_id: int,
    operation_type: OperationType,
    quantity: int,
    scanned_at: datetime,
    from_id: int | None,
    to_id: int | None,
) -> ActionLogs:
    action = ActionLogs(
        agency_id=agency_id,
        item_id=item_id,
        operation_type=operation_type,
        from_location_id=from_id,
        to_location_id=to_id,
        quantity_delta=quantity,
        admin_action=True,
        time_scanned=scanned_at,
    )
    session.add(action)
    session.flush()
    return action


def _assert_generated_alerts(ctx: AlertTestContext) -> None:
    with get_session() as session:
        alerts = _alerts(session)
        _print_alert_counts(alerts)
        _assert_type_actions(alerts)
        _assert_alert_identity(alerts, AlertType.STOCKOUT, AlertAction.PENDING, "Stockout Negative")
        _assert_alert_identity(alerts, AlertType.STOCKOUT, AlertAction.PENDING, "Never Counted")
        _assert_alert_identity(alerts, AlertType.LOW, AlertAction.PENDING, "Low Crossing")
        _assert_alert_identity(alerts, AlertType.STOCKOUT, AlertAction.CLEARED, "Cleared Stockout")
        _assert_alert_identity(alerts, AlertType.LOW, AlertAction.SUPPRESSED, "Stockout Negative")
        _assert_alert_identity(
            alerts, AlertType.LOW_PRED, AlertAction.SUPPRESSED, "Pred Both Suppression"
        )
        _assert_absent(alerts, AlertType.RARE_TAKEOUT, "Old Transfer Only")
        _assert_absent(alerts, AlertType.RARE_TAKEOUT, "Recent Takeout")
        _assert_prediction_details(alerts)
        _assert_schedules(alerts)
        _assert_current_total(session, ctx, "Stockout Negative", -2)


def _assert_type_actions(alerts: list[AlertRecords]) -> None:
    expected = {
        (AlertType.STOCKOUT, AlertAction.PENDING): 2,
        (AlertType.STOCKOUT, AlertAction.CLEARED): 1,
        (AlertType.STOCKOUT_PRED, AlertAction.PENDING): 3,
        (AlertType.LOW, AlertAction.PENDING): 1,
        (AlertType.LOW, AlertAction.SUPPRESSED): 2,
        (AlertType.LOW_PRED, AlertAction.PENDING): 1,
        (AlertType.LOW_PRED, AlertAction.SUPPRESSED): 3,
        (AlertType.STALE_COUNT, AlertAction.PENDING): 2,
        (AlertType.RARE_TAKEOUT, AlertAction.PENDING): 1,
        (AlertType.COUNT_ACTION, AlertAction.PENDING): 2,
        (AlertType.RESTOCK_ACTION, AlertAction.PENDING): 1,
        (AlertType.TAKEOUT_ACTION, AlertAction.PENDING): 4,
        (AlertType.TRANSFER_ACTION, AlertAction.PENDING): 1,
    }
    counts = Counter((alert.type, alert.action) for alert in alerts)
    for key, count in expected.items():
        _check(counts[key] == count, f"{key[0].value}/{key[1].value} count is {count}")


def _assert_prediction_details(alerts: list[AlertRecords]) -> None:
    override = _one(alerts, AlertType.STOCKOUT_PRED, "Pred Stockout Override")
    default = _one(alerts, AlertType.LOW_PRED, "Pred Low Default")
    fallback = _one(alerts, AlertType.STOCKOUT_PRED, "Fallback Pred Stockout")
    _check(override.details_json["lead_time_days"] == 14, "item lead-time override used")
    _check(default.details_json["lead_time_days"] == 21, "agency lead-time default used")
    _check(fallback.details_json.get("confidence_percent") is None, "fallback confidence is blank")


def _assert_schedules(alerts: list[AlertRecords]) -> None:
    hourly = _one(alerts, AlertType.STOCKOUT, "Stockout Negative").scheduled
    daily = _one(alerts, AlertType.LOW, "Low Crossing").scheduled
    action = _one(alerts, AlertType.COUNT_ACTION, "Scan Count").scheduled
    _check(hourly == datetime(2026, 5, 10, 7, 0), "stockout schedules next UTC hour")
    _check(daily == datetime(2026, 5, 10, 12, 0), "warning schedules 8am agency local")
    _check(action == datetime(2026, 5, 10, 12, 0), "scan activity waits for 8am local")


def _assert_no_email_before_due(initial_files: set[Path]) -> None:
    _set_clock(datetime(2026, 5, 10, 6, 59, tzinfo=UTC))
    result = process_all_alerts()
    _check(result == {"processed": 0, "sent": 0}, "no email before first due alert")
    _check(_alert_files() == initial_files, "no files written before due time")


def _assert_early_stockout_email(initial_files: set[Path]) -> set[Path]:
    _set_clock(datetime(2026, 5, 10, 7, 0, tzinfo=UTC))
    result = process_all_alerts()
    html_files = _new_html_files(initial_files)
    _check(result == {"processed": 1, "sent": 1}, "early stockout batch processed")
    _check(len(html_files) == 2, "two early recipient files written")
    contents = [_read(path) for path in html_files]
    _check(any("Stockouts" in text for text in contents), "early email includes stockouts")
    _check(
        any("Predicted Stockouts" in text for text in contents),
        "early email includes predictions",
    )
    _check(any("Low Stock" in text for text in contents), "early email includes low stock")
    _check(any("Predicted Low Stock" in text for text in contents), "early email includes low pred")
    _check(any("Stale Counts" in text for text in contents), "early email includes stale counts")
    _check(any("Rare Takeouts" in text for text in contents), "early email includes rare takeouts")
    _check(all("Scan Activity" not in text for text in contents), "scan activity is not early")
    _check(any("14 days" in text for text in contents), "email shows item lead-time override")
    _check(any("21 days" in text for text in contents), "email shows agency lead-time fallback")
    _check(
        any("Fallback Pred Stockout" in text for text in contents),
        "email includes fallback prediction",
    )
    _check(not any("Cleared Stockout" in text for text in contents), "cleared alert not emailed")
    return html_files


def _assert_daily_scan_email(previous_files: set[Path]) -> None:
    _set_clock(datetime(2026, 5, 10, 12, 0, tzinfo=UTC))
    result = process_all_alerts()
    html_files = _new_html_files(previous_files)
    _check(result == {"processed": 1, "sent": 1}, "daily scan batch processed")
    _check(len(html_files) == 1, "one daily scan recipient file written")
    text = _read(next(iter(html_files)))
    _check("🟢 Inventory Alert Report" in text, "scan-only subject is green")
    _check("Scan Activity" in text, "daily email includes scan activity")
    for label in ("Count", "Restock", "Takeout", "Transfer"):
        _check(label in text, f"daily scan email includes {label}")
    _check("Stockouts" not in text, "daily scan email does not resend stock sections")


def _assert_final_state() -> None:
    with get_session() as session:
        alerts = _alerts(session)
        pending = [alert for alert in alerts if alert.action == AlertAction.PENDING]
        sent_actions = [
            alert
            for alert in alerts
            if alert.type
            in {
                AlertType.COUNT_ACTION,
                AlertType.RESTOCK_ACTION,
                AlertType.TAKEOUT_ACTION,
                AlertType.TRANSFER_ACTION,
            }
            and alert.action == AlertAction.SENT
        ]
        _check(not pending, "no pending alerts remain after due sends")
        _check(len(sent_actions) == 8, "all scan activity rows sent at daily cadence")


def _print_alert_counts(alerts: list[AlertRecords]) -> None:
    print("\nGenerated alert rows:")
    for (alert_type, action), count in sorted(
        Counter((alert.type, alert.action) for alert in alerts).items(),
        key=lambda row: (row[0][0].value, row[0][1].value),
    ):
        print(f"  {alert_type.value:<18} {action.value:<10} {count}")


def _assert_alert_identity(
    alerts: list[AlertRecords],
    alert_type: AlertType,
    action: AlertAction,
    item_name: str,
) -> None:
    found = any(
        alert.type == alert_type
        and alert.action == action
        and alert.details_json.get("item_name") == item_name
        for alert in alerts
    )
    _check(found, f"{item_name} has {alert_type.value}/{action.value}")


def _assert_absent(alerts: list[AlertRecords], alert_type: AlertType, item_name: str) -> None:
    found = any(
        alert.type == alert_type and alert.details_json.get("item_name") == item_name
        for alert in alerts
    )
    _check(not found, f"{item_name} has no {alert_type.value}")


def _assert_current_total(
    session: Session,
    ctx: AlertTestContext,
    item_name: str,
    expected: int,
) -> None:
    total = get_location_item_quantity(
        session, ctx.agency_id, ctx.items[item_name], ctx.hq_location_id
    )
    _check(total == expected, f"{item_name} current total is {expected}")


def _one(alerts: list[AlertRecords], alert_type: AlertType, item_name: str) -> AlertRecords:
    matches = [
        alert
        for alert in alerts
        if alert.type == alert_type and alert.details_json.get("item_name") == item_name
    ]
    _check(len(matches) == 1, f"exactly one {alert_type.value} for {item_name}")
    return matches[0]


def _alerts(session: Session) -> list[AlertRecords]:
    return list(
        session.execute(select(AlertRecords).order_by(AlertRecords.type, AlertRecords.id))
        .scalars()
        .all()
    )


def _set_clock(value: datetime) -> None:
    CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOCK_FILE.write_text(
        json.dumps({"mode": "fixed", "fake_anchor": value.astimezone(UTC).isoformat()}),
        encoding="utf-8",
    )


def _reset_clock() -> None:
    CLOCK_FILE.unlink(missing_ok=True)


def _alert_files() -> set[Path]:
    alerts_dir = Path("instance/alerts")
    alerts_dir.mkdir(parents=True, exist_ok=True)
    return set(alerts_dir.glob("*_alert.html"))


def _new_html_files(previous_files: set[Path]) -> set[Path]:
    return _alert_files() - previous_files


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


if __name__ == "__main__":
    main()
