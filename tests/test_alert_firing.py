"""Alerts must open when stock goes wrong, and close once it is put right.

Nothing here touches the email path; only alert rows are read and written.
"""

from datetime import date, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.alert_service import generate_scheduled_alerts, sync_expiration_alerts
from app.alerts.constants import AlertStatus, AlertType
from app.alerts.models import Alert
from app.inventory.expiration_service import ExpirationAllocation
from tests.actions import Squad
from tests.factories import ITEM_MIN_QUANTITY, build_agency

HEALTHY_QUANTITY: Final[int] = 9
BELOW_MINIMUM_QUANTITY: Final[int] = 1
EXPIRED_QUANTITY: Final[int] = 5


def _alerts(squad: Squad, *, status: AlertStatus = AlertStatus.OPEN) -> list[Alert]:
    return list(squad.session.execute(select(Alert).where(Alert.agency_id == squad.id, Alert.status == status).order_by(Alert.id)).scalars().all())


def _alert_types(squad: Squad, *, status: AlertStatus = AlertStatus.OPEN) -> set[AlertType]:
    return {alert.alert_type for alert in _alerts(squad, status=status)}


def test_a_scan_opens_an_alert_recording_the_action(squad: Squad) -> None:
    squad.count(HEALTHY_QUANTITY)

    assert AlertType.COUNT_ACTION in _alert_types(squad)


def test_each_operation_opens_its_own_kind_of_action_alert(squad: Squad) -> None:
    squad.count_every_storage()
    squad.restock(HEALTHY_QUANTITY)
    squad.take_out(BELOW_MINIMUM_QUANTITY)
    squad.transfer(BELOW_MINIMUM_QUANTITY, source=squad.fixture.shelf.id, destination=squad.fixture.truck.id)

    opened = _alert_types(squad)
    assert {AlertType.COUNT_ACTION, AlertType.RESTOCK_ACTION, AlertType.TAKEOUT_ACTION, AlertType.TRANSFER_ACTION} <= opened


def test_counting_to_zero_opens_a_stockout_alert(squad: Squad) -> None:
    squad.count(0)

    assert AlertType.STOCKOUT in _alert_types(squad)


def test_counting_below_the_minimum_opens_a_low_stock_alert(squad: Squad) -> None:
    assert BELOW_MINIMUM_QUANTITY < ITEM_MIN_QUANTITY
    squad.count(BELOW_MINIMUM_QUANTITY)

    assert AlertType.LOW_STOCK in _alert_types(squad)


def test_healthy_stock_opens_no_stock_alert(squad: Squad) -> None:
    squad.count(HEALTHY_QUANTITY)

    assert AlertType.STOCKOUT not in _alert_types(squad)
    assert AlertType.LOW_STOCK not in _alert_types(squad)


def test_restocking_closes_the_stockout_alert(squad: Squad) -> None:
    squad.count_every_storage()
    assert AlertType.STOCKOUT in _alert_types(squad)

    squad.restock(HEALTHY_QUANTITY)

    assert AlertType.STOCKOUT not in _alert_types(squad)
    assert AlertType.STOCKOUT in _alert_types(squad, status=AlertStatus.CLOSED)


def test_the_same_problem_does_not_open_a_second_alert(squad: Squad) -> None:
    squad.count(0)
    first = [alert.id for alert in _alerts(squad) if alert.alert_type == AlertType.STOCKOUT]

    generate_scheduled_alerts(squad.session, agency_id=squad.id)

    second = [alert.id for alert in _alerts(squad) if alert.alert_type == AlertType.STOCKOUT]
    assert first == second


def test_expired_stock_opens_an_expiration_alert(tracked_squad: Squad) -> None:
    yesterday = date.today() - timedelta(days=1)
    tracked_squad.count(EXPIRED_QUANTITY, allocations=[ExpirationAllocation(yesterday, EXPIRED_QUANTITY)])

    sync_expiration_alerts(tracked_squad.session, agency_id=tracked_squad.id)

    assert AlertType.EXPIRED_STOCK in _alert_types(tracked_squad)


def test_stock_expiring_inside_the_notice_window_opens_a_warning(tracked_squad: Squad) -> None:
    soon = date.today() + timedelta(days=3)
    tracked_squad.count(EXPIRED_QUANTITY, allocations=[ExpirationAllocation(soon, EXPIRED_QUANTITY)])

    sync_expiration_alerts(tracked_squad.session, agency_id=tracked_squad.id)

    assert AlertType.EXPIRING_SOON in _alert_types(tracked_squad)


def test_stock_expiring_far_out_opens_no_expiration_alert(tracked_squad: Squad) -> None:
    far = date.today() + timedelta(days=365)
    tracked_squad.count(EXPIRED_QUANTITY, allocations=[ExpirationAllocation(far, EXPIRED_QUANTITY)])

    sync_expiration_alerts(tracked_squad.session, agency_id=tracked_squad.id)

    opened = _alert_types(tracked_squad)
    assert AlertType.EXPIRED_STOCK not in opened
    assert AlertType.EXPIRING_SOON not in opened


def test_one_agencys_alerts_stay_out_of_anothers(squad: Squad, session: Session) -> None:
    other = Squad(build_agency(session), session)
    squad.count(0)

    assert _alerts(other) == []
