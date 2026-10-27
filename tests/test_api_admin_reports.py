"""The admin report JSON endpoints, driven over real HTTP.

Nothing here reaches the email provider; the batch delivery function is replaced for every email test.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any, Final

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.models import Location, NotificationRecipient, Storage
from app.inventory import report_email_service
from app.inventory.constants import TAKEOUT_LABEL, OperationType
from app.inventory.history_service import HISTORY_PAGE_SIZE
from app.inventory.models import ActionLog
from app.inventory.report_email_service import ReportEmailOutcome
from tests.actions import Squad
from tests.factories import AgencyFixture, build_agency, build_item

COUNTED_QUANTITY: Final[int] = 6
SECOND_LOCATION_NAME: Final[str] = "Annex"
SECOND_STORAGE_NAME: Final[str] = "Annex Shelf"
RECIPIENT_EMAIL: Final[str] = "reports@example.com"
UNKNOWN_RECIPIENT_ID: Final[int] = 987654
ALL_LOCATIONS_ID: Final[int] = 0
ALL_LOCATIONS_NAME: Final[str] = "All Locations"
OVERFLOW_LOG_COUNT: Final[int] = HISTORY_PAGE_SIZE + 1
FAR_PAST_PAGE: Final[int] = 99


def _api(agency_id: int, path: str) -> str:
    return f"/api/v1/agencies/{agency_id}{path}"


def _v1(agency_id: int, path: str) -> str:
    return f"/inventory/{agency_id}{path}"


def _add_location(session: Session, agency_id: int) -> tuple[Location, Storage]:
    location = Location(agency_id=agency_id, name=SECOND_LOCATION_NAME)
    session.add(location)
    session.flush()
    storage = Storage(
        agency_id=agency_id,
        location_id=location.id,
        name=SECOND_STORAGE_NAME,
        user_access_from=True,
        user_access_to=True,
    )
    session.add(storage)
    session.commit()
    return location, storage


def _add_recipient(session: Session, agency_id: int) -> NotificationRecipient:
    recipient = NotificationRecipient(agency_id=agency_id, email=RECIPIENT_EMAIL, active=True)
    session.add(recipient)
    session.commit()
    return recipient


def _add_action_logs(session: Session, agency: AgencyFixture, count: int) -> None:
    """Rows written straight to the table, so a pagination test does not pay for real scans."""
    start = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    session.add_all(
        ActionLog(
            agency_id=agency.id,
            item_id=agency.item.id,
            operation_type=OperationType.TAKEOUT,
            quantity=1,
            from_storage_id=agency.shelf.id,
            to_storage_id=None,
            admin_action=True,
            time_scanned=start + timedelta(minutes=offset),
        )
        for offset in range(count)
    )
    session.commit()


@pytest.fixture
def delivered_emails(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every report email stops here; no address ever reaches the provider."""
    recipients: list[str] = []

    def record_batch(batch: Any, **_unused: Any) -> bool:
        recipients.append(batch.agency_email)
        return True

    monkeypatch.setattr(report_email_service, "deliver_batch", record_batch)
    yield recipients


def test_the_stock_levels_report_counts_every_storage_of_the_location(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    squad: Squad,
) -> None:
    squad.count(COUNTED_QUANTITY, storage_id=agency.shelf.id)

    body = admin_client.get(_api(agency.id, "/reports/stock-levels")).get_json()

    assert body["location"] == {"id": agency.location.id, "name": agency.location.name}
    assert [storage["name"] for storage in body["storages"]] == [agency.shelf.name, agency.truck.name]
    [row] = body["rows"]
    assert row["item_name"] == agency.item.name
    assert row["total"] == COUNTED_QUANTITY
    assert {count["storage_id"]: count["quantity"] for count in row["storage_counts"]} == {
        agency.shelf.id: COUNTED_QUANTITY,
        agency.truck.id: 0,
    }


def test_the_location_filter_chooses_which_location_a_report_is_about(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    location, storage = _add_location(session, agency.id)

    body = admin_client.get(_api(agency.id, "/reports/stock-levels"), query_string={"location_id": location.id}).get_json()

    assert body["location"]["name"] == SECOND_LOCATION_NAME
    assert [column["name"] for column in body["storages"]] == [storage.name]


def test_the_stock_levels_report_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, "/reports/stock-levels")).status_code == HTTPStatus.FORBIDDEN


def test_another_agencys_stock_levels_are_refused(admin_client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert admin_client.get(_api(other.id, "/reports/stock-levels")).status_code == HTTPStatus.FORBIDDEN


def test_the_restock_report_lists_the_locations_items(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    squad.count_every_storage()

    response = admin_client.get(_api(agency.id, "/reports/restock"))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["location"]["id"] == agency.location.id
    [row] = body["rows"]
    assert row["item_name"] == agency.item.name
    assert row["minimum_quantity"] == agency.item.min_quantity


def test_the_restock_report_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, "/reports/restock")).status_code == HTTPStatus.FORBIDDEN


def test_the_history_report_fills_one_page_and_reports_the_window(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    _add_action_logs(session, agency, OVERFLOW_LOG_COUNT)

    body = admin_client.get(_api(agency.id, "/reports/history")).get_json()

    assert body["total_rows"] == OVERFLOW_LOG_COUNT
    assert body["total_pages"] == 2
    assert body["page"] == 1
    assert body["page_size"] == HISTORY_PAGE_SIZE
    assert len(body["rows"]) == HISTORY_PAGE_SIZE
    assert body["rows"][0]["item_name"] == agency.item.name
    assert body["rows"][0]["to_label"] == TAKEOUT_LABEL


def test_a_page_past_the_end_of_the_history_lands_on_the_last_one(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    _add_action_logs(session, agency, OVERFLOW_LOG_COUNT)

    body = admin_client.get(_api(agency.id, "/reports/history"), query_string={"page": FAR_PAST_PAGE}).get_json()

    assert body["page"] == 2
    assert len(body["rows"]) == OVERFLOW_LOG_COUNT - HISTORY_PAGE_SIZE


def test_the_history_report_spans_every_location_when_the_filter_is_zero(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    _add_action_logs(session, agency, 1)

    body = admin_client.get(_api(agency.id, "/reports/history"), query_string={"location_id": ALL_LOCATIONS_ID}).get_json()

    assert body["location"] == {"id": None, "name": ALL_LOCATIONS_NAME}
    assert len(body["rows"]) == 1


def test_an_unknown_history_sort_key_falls_back_to_time(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = admin_client.get(_api(agency.id, "/reports/history"), query_string={"sort": "nonsense"}).get_json()

    assert body["sort_key"] == "time"
    assert body["descending"] is True


def test_the_history_report_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, "/reports/history")).status_code == HTTPStatus.FORBIDDEN


def test_another_agencys_history_is_not_listed(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    other = build_agency(session)
    _add_action_logs(session, other, 2)
    _add_action_logs(session, agency, 1)

    body = admin_client.get(_api(agency.id, "/reports/history")).get_json()

    assert body["total_rows"] == 1


def test_emailing_the_stock_levels_report_reaches_the_selected_recipient(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
    delivered_emails: list[str],
) -> None:
    recipient = _add_recipient(session, agency.id)

    response = admin_client.post(
        _api(agency.id, "/reports/stock-levels/email"),
        json={"notification_recipient_ids": [recipient.id]},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == {"outcome": ReportEmailOutcome.SENT.value, "sent": 1, "total": 1}
    assert delivered_emails == [RECIPIENT_EMAIL]


def test_emailing_the_restock_report_reaches_the_selected_recipient(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
    delivered_emails: list[str],
) -> None:
    recipient = _add_recipient(session, agency.id)

    response = admin_client.post(
        _api(agency.id, "/reports/restock/email"),
        json={"notification_recipient_ids": [recipient.id], "location_id": agency.location.id},
    )

    assert response.status_code == HTTPStatus.OK
    assert delivered_emails == [RECIPIENT_EMAIL]


def test_emailing_the_history_report_reaches_the_selected_recipient(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
    delivered_emails: list[str],
) -> None:
    recipient = _add_recipient(session, agency.id)
    _add_action_logs(session, agency, 1)

    response = admin_client.post(
        _api(agency.id, "/reports/history/email"),
        json={"notification_recipient_ids": [recipient.id], "start_date": "2026-01-01"},
    )

    assert response.status_code == HTTPStatus.OK
    assert delivered_emails == [RECIPIENT_EMAIL]


def test_a_report_email_to_nobody_known_is_refused(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    delivered_emails: list[str],
) -> None:
    response = admin_client.post(
        _api(agency.id, "/reports/stock-levels/email"),
        json={"notification_recipient_ids": [UNKNOWN_RECIPIENT_ID]},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert delivered_emails == []


def test_a_report_email_with_no_recipients_is_refused_at_the_schema(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    delivered_emails: list[str],
) -> None:
    response = admin_client.post(_api(agency.id, "/reports/stock-levels/email"), json={"notification_recipient_ids": []})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert delivered_emails == []


def test_a_history_report_email_refuses_a_date_in_the_future(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
    delivered_emails: list[str],
) -> None:
    recipient = _add_recipient(session, agency.id)
    tomorrow = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()

    response = admin_client.post(
        _api(agency.id, "/reports/history/email"),
        json={"notification_recipient_ids": [recipient.id], "start_date": tomorrow},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert delivered_emails == []


def test_a_report_email_is_refused_while_admin_is_locked(
    client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
    delivered_emails: list[str],
) -> None:
    recipient = _add_recipient(session, agency.id)

    response = client.post(
        _api(agency.id, "/reports/stock-levels/email"),
        json={"notification_recipient_ids": [recipient.id]},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert delivered_emails == []


def test_the_item_trend_chart_returns_one_items_series(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    squad.count(COUNTED_QUANTITY, storage_id=agency.shelf.id)
    squad.count(COUNTED_QUANTITY, storage_id=agency.truck.id)

    response = admin_client.get(_api(agency.id, f"/items/{agency.item.id}/locations/{agency.location.id}/trend"))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["item_name"] == agency.item.name
    assert body["location_name"] == agency.location.name
    assert [point["quantity"] for point in body["count_points"]] == [COUNTED_QUANTITY * 2]


def test_a_location_counted_only_in_part_anchors_no_point(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    squad.count(COUNTED_QUANTITY, storage_id=agency.shelf.id)

    body = admin_client.get(_api(agency.id, f"/items/{agency.item.id}/locations/{agency.location.id}/trend")).get_json()

    assert body["count_points"] == []


def test_the_item_trend_chart_refuses_another_agencys_item(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    session: Session,
) -> None:
    other_item = build_item(session, build_agency(session).id, name="Someone Elses Splint")
    session.commit()

    response = admin_client.get(_api(agency.id, f"/items/{other_item.id}/locations/{agency.location.id}/trend"))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_the_item_trend_chart_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    path = f"/items/{agency.item.id}/locations/{agency.location.id}/trend"

    assert client.get(_api(agency.id, path)).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("page", ["/admin-panel/stock-levels", "/admin-panel/restock", "/admin-panel/history"])
def test_the_v1_report_pages_still_render_after_the_extraction(admin_client: FlaskClient, agency: AgencyFixture, page: str) -> None:
    assert admin_client.get(_v1(agency.id, page)).status_code == HTTPStatus.OK
