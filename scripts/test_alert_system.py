"""End-to-end QA runner for inventory alert generation and delivery.

This is intentionally a script, not pytest, because the repo has no test
framework yet and the output is meant to be readable during local QA.
"""

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
settings.email_api_key = ""
settings.email_sender_email = ""
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
from app.prediction.estimator import get_location_item_quantity, project_location_item  # noqa: E402
from app.prediction.models import InventoryTrend  # noqa: E402
from app.shared.clock import CLOCK_FILE, utc_now  # noqa: E402
from app.shared.database import create_all, get_session  # noqa: E402


@dataclass(frozen=True)
class AlertTestContext:
    """IDs needed across the end-to-end alert QA script."""

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
            hourly_files = _assert_hourly_email(initial_files)
            _assert_daily_email(initial_files | hourly_files)
            _assert_final_state()
            _assert_resolved_condition_can_alert_again(ctx)
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
        "Pred Stockout Override": (-150.0, 80, "override"),
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
    action = _add_log(
        session, ctx.agency_id, item_id, operation_type, quantity, utc_now(), from_id, to_id
    )
    record_action_log_alerts(session, [action])


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
        _assert_current_total(session, ctx, "Stockout Negative", -2)


def _assert_type_actions(alerts: list[AlertRecords]) -> None:
    expected = {
        (AlertType.STOCKOUT, AlertAction.PENDING): 4,
        (AlertType.STOCKOUT, AlertAction.CLEARED): 2,
        (AlertType.STOCKOUT_PRED, AlertAction.PENDING): 6,
        (AlertType.LOW, AlertAction.PENDING): 2,
        (AlertType.LOW, AlertAction.SUPPRESSED): 4,
        (AlertType.LOW_PRED, AlertAction.PENDING): 2,
        (AlertType.LOW_PRED, AlertAction.SUPPRESSED): 6,
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
    with get_session() as session:
        item = session.scalar(select(Items).where(Items.name == "Pred Stockout Override"))
        _check(item is not None, "override item exists for trend cap check")
        assert item is not None
        projection = project_location_item(
            session,
            item.agency_id,
            item,
            int(override.details_json["agency_location_id"]),
        )
        _check(projection.daily_usage == 99.0, "daily usage is capped at 99")
        _check(-projection.daily_usage == -99.0, "effective trend is capped at -99")


def _assert_hourly_email(initial_files: set[Path]) -> set[Path]:
    _set_clock(datetime(2026, 5, 10, 7, 0, tzinfo=UTC))
    result = process_all_alerts()
    html_files = _new_html_files(initial_files)
    _check(result == {"processed": 2, "sent": 2, "failed": 0}, "hourly batches processed")
    _check(len(html_files) == 2, "two hourly recipient files written")
    contents = [_read(path) for path in html_files]
    _check(any("Stockouts" in text for text in contents), "hourly email includes stockouts")
    _check(any("Scan Activity" in text for text in contents), "hourly email includes scan activity")
    _check(all("Predicted Stockouts" not in text for text in contents), "predictions wait daily")
    _check(all("Low Stock" not in text for text in contents), "low stock waits daily")
    return html_files


def _assert_daily_email(previous_files: set[Path]) -> None:
    _set_clock(datetime(2026, 5, 10, 12, 0, tzinfo=UTC))
    result = process_all_alerts()
    html_files = _new_html_files(previous_files)
    _check(result == {"processed": 2, "sent": 2, "failed": 0}, "daily warning batches processed")
    _check(len(html_files) == 2, "two daily recipient files written")
    contents = [_read(path) for path in html_files]
    _check(any("Predicted Stockouts" in text for text in contents), "daily email has predictions")
    _check(any("Low Stock" in text for text in contents), "daily email has low stock")
    _check(any("Stale Counts" in text for text in contents), "daily email has stale counts")
    _check(any("Rare Takeouts" in text for text in contents), "daily email has rare takeouts")
    _check(
        all("Scan Activity" not in text for text in contents),
        "hourly scans do not resend daily",
    )


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


def _assert_resolved_condition_can_alert_again(ctx: AlertTestContext) -> None:
    _set_clock(datetime(2026, 5, 10, 13, 0, tzinfo=UTC))
    with get_session() as session:
        _scan(session, ctx, "Low Crossing", OperationType.TAKEOUT, 1, from_id=ctx.main_storage_id)
        session.commit()
    with get_session() as session:
        _assert_alert_identity(
            _alerts(session), AlertType.LOW, AlertAction.SUPPRESSED, "Low Crossing"
        )

    _set_clock(datetime(2026, 5, 10, 13, 30, tzinfo=UTC))
    with get_session() as session:
        _scan(session, ctx, "Low Crossing", OperationType.COUNT, 9, to_id=ctx.main_storage_id)
        session.commit()
    with get_session() as session:
        _assert_alert_identity(
            _alerts(session), AlertType.LOW, AlertAction.SUPPRESSED, "Low Crossing"
        )

    _set_clock(datetime(2026, 5, 10, 14, 0, tzinfo=UTC))
    with get_session() as session:
        _scan(session, ctx, "Low Crossing", OperationType.COUNT, 15, to_id=ctx.main_storage_id)
        session.commit()
    with get_session() as session:
        _assert_alert_identity(
            _alerts(session), AlertType.LOW, AlertAction.RESOLVED, "Low Crossing"
        )

    _set_clock(datetime(2026, 5, 10, 15, 0, tzinfo=UTC))
    with get_session() as session:
        _scan(session, ctx, "Low Crossing", OperationType.TAKEOUT, 6, from_id=ctx.main_storage_id)
        session.commit()
    with get_session() as session:
        _assert_alert_identity(_alerts(session), AlertType.LOW, AlertAction.PENDING, "Low Crossing")


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
    _check(bool(matches), f"at least one {alert_type.value} for {item_name}")
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
    logs_dir = Path("instance/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    return set(logs_dir.glob("*_alert.html"))


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
