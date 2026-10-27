"""The JSON endpoints behind the admin dashboard, settings, and pending expiration dates."""

from datetime import date, timedelta
from http import HTTPStatus
from typing import Any, Final

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.alerts.alert_service import sync_expiration_alerts
from app.alerts.constants import AlertType
from app.auth.models import Agency
from app.inventory.expiration_service import known_expiration_options
from tests.actions import Squad
from tests.factories import AgencyFixture, build_agency

COUNTED_QUANTITY: Final[int] = 10
NEAR_LOT: Final[int] = 4
FAR_LOT: Final[int] = 6
NEW_LEAD_TIME_DAYS: Final[int] = 14
NEW_PIN: Final[str] = "4321"
IMPLAUSIBLE_YEARS_AHEAD: Final[int] = 40
ATTENTION_TILE_COUNT: Final[int] = 10

DASHBOARD_PATH: Final[str] = "/admin/dashboard"
SETTINGS_PATH: Final[str] = "/admin/settings"
PENDING_PATH: Final[str] = "/admin/pending-expirations"


def _api(agency_id: int, path: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}{path}"


def _near() -> date:
    return date.today() + timedelta(days=10)


def _far() -> date:
    return date.today() + timedelta(days=200)


def _make_pending_pairs(squad: Squad, *storage_ids: int) -> None:
    """Count stock, then switch tracking on, which is exactly how a pair ends up with no dates."""
    for storage_id in storage_ids or (squad.fixture.shelf.id,):
        squad.count(COUNTED_QUANTITY, storage_id=storage_id)
    squad.fixture.item.expiration_tracking_enabled = True
    squad.session.commit()


def _saved_agency(session: Session, agency_id: int) -> Agency:
    """Each endpoint call closes the scoped session, so settings have to be read back fresh."""
    saved = session.get(Agency, agency_id)
    assert saved is not None
    return saved


def _settings_body(**overrides: Any) -> dict[str, Any]:
    return {
        "image": None,
        "pin": None,
        "user_count_allow": True,
        "user_restock_allow": False,
        "lead_time_days": NEW_LEAD_TIME_DAYS,
        "count_last_days": 90,
        "alert_rare_scan_days": 90,
        "expiration_notice_days": 30,
        **overrides,
    }


def _correction(agency: AgencyFixture, allocations: list[dict[str, Any]], *, storage_id: int | None = None) -> dict[str, Any]:
    return {
        "item_id": agency.item.id,
        "storage_id": storage_id if storage_id is not None else agency.shelf.id,
        "allocations": allocations,
    }


def test_the_dashboard_lists_every_attention_tile_with_its_alert_type(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, DASHBOARD_PATH))

    assert response.status_code == HTTPStatus.OK
    tiles = response.get_json()
    assert len(tiles) == ATTENTION_TILE_COUNT
    assert {tile["alert_type"] for tile in tiles} >= {AlertType.EXPIRATION_COUNT_NEEDED, AlertType.STOCKOUT}
    assert all(tile["count"] == 0 for tile in tiles)


def test_a_pair_missing_dates_shows_up_on_the_missing_dates_tile(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    sync_expiration_alerts(squad.session, agency_id=agency.id)
    squad.session.commit()

    tiles = admin_client.get(_api(agency.id, DASHBOARD_PATH)).get_json()

    [tile] = [tile for tile in tiles if tile["alert_type"] == AlertType.EXPIRATION_COUNT_NEEDED]
    assert tile["count"] == 1
    assert "1 shelf spot" in tile["detail"]
    assert tiles[0]["count"] > 0  # cleared tiles sort last


def test_the_dashboard_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, DASHBOARD_PATH))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "PIN" in response.get_json()["message"]


def test_another_agencys_dashboard_is_refused(admin_client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert admin_client.get(_api(other.id, DASHBOARD_PATH)).status_code == HTTPStatus.FORBIDDEN


def test_settings_answer_the_agencys_own_thresholds_and_never_the_pin(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, SETTINGS_PATH))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["lead_time_days"] == agency.agency.lead_time_days
    assert body["user_count_allow"] is False
    assert "pin" not in body


def test_reading_settings_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, SETTINGS_PATH)).status_code == HTTPStatus.FORBIDDEN


def test_saving_settings_changes_permissions_and_thresholds(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.put(_api(agency.id, SETTINGS_PATH), json=_settings_body())

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()["lead_time_days"] == NEW_LEAD_TIME_DAYS
    saved = _saved_agency(session, agency.id)
    assert (saved.user_count_allow, saved.lead_time_days) == (True, NEW_LEAD_TIME_DAYS)


def test_saving_settings_sets_a_new_admin_pin(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    admin_client.put(_api(agency.id, SETTINGS_PATH), json=_settings_body(pin=NEW_PIN))

    assert _saved_agency(session, agency.id).check_pin(NEW_PIN) is True


def test_a_threshold_below_one_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.put(_api(agency.id, SETTINGS_PATH), json=_settings_body(lead_time_days=0))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_a_pin_that_is_not_four_digits_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    assert admin_client.put(_api(agency.id, SETTINGS_PATH), json=_settings_body(pin="12")).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_unexpected_settings_field_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = _settings_body(device_location_id=1)

    assert admin_client.put(_api(agency.id, SETTINGS_PATH), json=body).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_saving_settings_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.put(_api(agency.id, SETTINGS_PATH), json=_settings_body()).status_code == HTTPStatus.FORBIDDEN


def test_pending_expirations_list_the_pair_waiting_on_dates(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)

    response = admin_client.get(_api(agency.id, PENDING_PATH))

    assert response.status_code == HTTPStatus.OK
    [group] = response.get_json()
    assert (group["item_id"], group["storage_id"]) == (agency.item.id, agency.shelf.id)
    assert group["target_quantity"] == COUNTED_QUANTITY
    assert (group["allows_new_dates"], group["allows_other"]) == (True, False)


def test_pending_expirations_are_empty_when_every_count_is_dated(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(_api(agency.id, PENDING_PATH))

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == []


def test_pending_expirations_are_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, PENDING_PATH)).status_code == HTTPStatus.FORBIDDEN


def test_another_agencys_pending_expirations_are_refused(admin_client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert admin_client.get(_api(other.id, PENDING_PATH)).status_code == HTTPStatus.FORBIDDEN


def test_a_correction_writes_the_dates_the_counted_stock_carries(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": _near().isoformat(), "quantity": NEAR_LOT}, {"expires_on": _far().isoformat(), "quantity": FAR_LOT}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()["corrected_pair_count"] == 1
    squad.session.expire_all()
    options = known_expiration_options(squad.session, agency.id, agency.item.id, agency.shelf.id)
    assert [(option.expires_on, option.quantity) for option in options] == [(_near(), NEAR_LOT), (_far(), FAR_LOT)]


def test_a_corrected_pair_stops_being_pending(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": _near().isoformat(), "quantity": COUNTED_QUANTITY}]

    admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert admin_client.get(_api(agency.id, PENDING_PATH)).get_json() == []


def test_a_correction_that_does_not_cover_every_unit_is_refused(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": _near().isoformat(), "quantity": NEAR_LOT}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert f"all {COUNTED_QUANTITY}" in response.get_json()["message"]


def test_an_undated_correction_is_refused_because_a_count_may_not_be_undated(
    admin_client: FlaskClient,
    agency: AgencyFixture,
    squad: Squad,
) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": None, "quantity": COUNTED_QUANTITY}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "needs an expiration date" in response.get_json()["message"]


def test_an_implausible_expiration_date_is_refused(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    far_future = date(date.today().year + IMPLAUSIBLE_YEARS_AHEAD, 1, 1).isoformat()
    allocations = [{"expires_on": far_future, "quantity": COUNTED_QUANTITY}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_leaving_one_pending_pair_unanswered_is_refused(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad, agency.shelf.id, agency.truck.id)
    allocations = [{"expires_on": _near().isoformat(), "quantity": COUNTED_QUANTITY}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "every item and storage" in response.get_json()["message"]


def test_a_correction_for_a_pair_that_is_not_pending_is_refused(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": _near().isoformat(), "quantity": COUNTED_QUANTITY}]
    corrections = [_correction(agency, allocations), _correction(agency, allocations, storage_id=agency.truck.id)]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": corrections})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "not waiting on dates" in response.get_json()["message"]


def test_a_correction_with_nothing_pending_is_not_found(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    allocations = [{"expires_on": _near().isoformat(), "quantity": COUNTED_QUANTITY}]

    response = admin_client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_a_correction_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)
    allocations = [{"expires_on": _near().isoformat(), "quantity": COUNTED_QUANTITY}]

    response = client.post(_api(agency.id, PENDING_PATH), json={"corrections": [_correction(agency, allocations)]})

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_the_v1_dashboard_and_settings_pages_still_render(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    assert admin_client.get(f"/inventory/{agency.id}/admin-panel").status_code == HTTPStatus.OK
    assert admin_client.get(f"/inventory/{agency.id}/settings").status_code == HTTPStatus.OK


def test_the_v1_pending_expiration_page_still_renders_its_pending_pair(admin_client: FlaskClient, agency: AgencyFixture, squad: Squad) -> None:
    _make_pending_pairs(squad)

    response = admin_client.get(f"/inventory/{agency.id}/admin-panel/expiration-dates")

    assert response.status_code == HTTPStatus.OK
    assert agency.item.name.encode() in response.data


def test_the_v1_pending_expiration_page_redirects_when_nothing_is_pending(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.get(f"/inventory/{agency.id}/admin-panel/expiration-dates")

    assert response.status_code == HTTPStatus.FOUND
