"""The JSON endpoints for notification recipients, driven over real HTTP."""

from http import HTTPStatus
from typing import Any, Final

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.models import NotificationRecipient
from app.auth.notification_preferences import NOTIFICATION_FIELDS
from tests.factories import AgencyFixture, build_agency

RECIPIENT_EMAIL: Final[str] = "alerts@example.com"
RECIPIENTS_PATH: Final[str] = "/notification-recipients"
V1_PAGE: Final[str] = "/inventory/{agency_id}/admin-panel/items-and-tags"


def _api(agency_id: int, path: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}/admin{RECIPIENTS_PATH}{path}"


def _recipient_body(agency: AgencyFixture, **extra: Any) -> dict[str, Any]:
    return {"email": RECIPIENT_EMAIL, "location_filter_ids": [agency.location.id]} | extra


def _build_recipient(session: Session, agency_id: int, location_id: int, email: str = RECIPIENT_EMAIL) -> NotificationRecipient:
    recipient = NotificationRecipient(agency_id=agency_id, email=email, active=True, location_filter_ids=[location_id])
    session.add(recipient)
    session.commit()
    return recipient


def test_the_list_carries_the_toggle_table_the_screen_labels_its_columns_with(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = admin_client.get(_api(agency.id)).get_json()

    assert [field["field"] for field in body["toggle_fields"]] == list(NOTIFICATION_FIELDS)
    assert {field["group"] for field in body["toggle_fields"]} == {"ALERT", "SUMMARY"}
    assert body["toggle_fields"][0]["label"] == "Stockout"


def test_a_recipient_carries_every_delivery_setting_and_toggle(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _build_recipient(session, agency.id, agency.location.id)

    response = admin_client.get(_api(agency.id))

    assert response.status_code == HTTPStatus.OK
    [recipient] = response.get_json()["recipients"]
    assert recipient["email"] == RECIPIENT_EMAIL
    assert recipient["location_filter_ids"] == [agency.location.id]
    assert recipient["location_names"] == [agency.location.name]
    assert recipient["quiet_hours_label"] == "None"
    assert recipient["alert_frequency"] == "HOURLY"
    assert recipient["alert_frequency_label"] == "Hourly"
    assert recipient["scan_alert_scope"] == "ALL"
    assert recipient["scan_alert_scope_label"] == "All items"
    assert set(recipient["toggles"]) == set(NOTIFICATION_FIELDS)
    assert recipient["toggles"]["alert_for_stockout"] is True
    assert recipient["toggles"]["alert_for_takeout"] is False
    assert recipient["toggles"]["daily_summary"] is False
    assert recipient["toggles"]["weekly_summary"] is True


def test_a_recipient_preview_reads_as_one_line(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _build_recipient(session, agency.id, agency.location.id)

    [recipient] = admin_client.get(_api(agency.id)).get_json()["recipients"]

    assert recipient["preview"] == f"{RECIPIENT_EMAIL} - {agency.location.name} - Hourly - 11 alerts - 3 summaries"


def test_a_preview_names_the_quiet_hours_when_the_recipient_has_them(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = _recipient_body(agency, quiet_start_time="22:00", quiet_end_time="06:00")

    created = admin_client.post(_api(agency.id), json=body).get_json()

    assert created["preview"].endswith("quiet 22:00-06:00")


def test_adding_a_recipient_saves_its_toggles(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json=_recipient_body(agency, alert_for_takeout=True))

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert body["email"] == RECIPIENT_EMAIL
    assert body["toggles"]["alert_for_takeout"] is True


def test_a_recipient_must_watch_at_least_one_location(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json=_recipient_body(agency, location_filter_ids=[]))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_a_recipient_may_not_watch_another_agencys_location(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)

    response = admin_client.post(_api(agency.id), json=_recipient_body(agency, location_filter_ids=[other.location.id]))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_quiet_hours_need_both_ends(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json=_recipient_body(agency, quiet_start_time="22:00"))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_unknown_field_on_a_recipient_is_refused_rather_than_ignored(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json=_recipient_body(agency, alert_for_everything=True))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_one_email_cannot_be_added_twice(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _build_recipient(session, agency.id, agency.location.id)

    response = admin_client.post(_api(agency.id), json=_recipient_body(agency))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_saving_a_recipient_replaces_its_row(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    recipient = _build_recipient(session, agency.id, agency.location.id)
    body = _recipient_body(agency, quiet_start_time="22:00", quiet_end_time="06:00", alert_for_stockout=False)

    response = admin_client.patch(_api(agency.id, f"/{recipient.id}"), json=body)

    assert response.status_code == HTTPStatus.OK
    saved = response.get_json()
    assert saved["quiet_hours_label"] == "22:00-06:00"
    assert saved["toggles"]["alert_for_stockout"] is False


def test_another_agencys_recipient_is_not_found(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)
    theirs = _build_recipient(session, other.id, other.location.id, email="theirs@example.com")

    response = admin_client.delete(_api(agency.id, f"/{theirs.id}"))

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_removing_a_recipient_drops_it_from_the_list(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    recipient = _build_recipient(session, agency.id, agency.location.id)

    response = admin_client.delete(_api(agency.id, f"/{recipient.id}"))

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert admin_client.get(_api(agency.id)).get_json()["recipients"] == []


def test_a_locked_browser_reaches_no_recipient_endpoint(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    recipient = _build_recipient(session, agency.id, agency.location.id)

    assert client.get(_api(agency.id)).status_code == HTTPStatus.FORBIDDEN
    assert client.post(_api(agency.id), json=_recipient_body(agency)).status_code == HTTPStatus.FORBIDDEN
    assert client.patch(_api(agency.id, f"/{recipient.id}"), json=_recipient_body(agency)).status_code == HTTPStatus.FORBIDDEN
    assert client.delete(_api(agency.id, f"/{recipient.id}")).status_code == HTTPStatus.FORBIDDEN


def test_the_v1_notifications_page_still_renders(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(V1_PAGE.format(agency_id=agency.id))

    assert response.status_code == HTTPStatus.OK
