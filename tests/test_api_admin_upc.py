"""The JSON endpoints behind the admin review of barcodes no item carries, driven over real HTTP."""

from http import HTTPStatus
from typing import Any, Final

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.inventory.constants import UnknownUpcStatus
from app.inventory.models import ItemSecondaryUpc, UnknownUpcScan
from tests.factories import AgencyFixture, build_agency, build_item

PENDING_UPC: Final[str] = "123456789012"
IGNORED_UPC: Final[str] = "200000000004"
ADDED_UPC: Final[str] = "999999999993"
WRONG_CHECK_DIGIT_UPC: Final[str] = "123456789019"
TOO_SHORT_UPC: Final[str] = "12345678998"
LOOKUP_TITLE: Final[str] = "Gauze Pads 4x4"
V1_REVIEW_PAGE: Final[str] = "/inventory/{agency_id}/admin-panel/unknown-barcodes"


def _api(agency_id: int, path: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}/admin/unknown-barcodes{path}"


def _review_row(session: Session, agency_id: int, upc: str, **fields: Any) -> UnknownUpcScan:
    """One barcode already waiting for review, written straight in so no external lookup runs."""
    scan = UnknownUpcScan(agency_id=agency_id, upc=upc, **fields)
    session.add(scan)
    session.commit()
    return scan


@pytest.fixture
def no_upc_title_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The record path asks an external service for a product title; tests never reach the network."""
    monkeypatch.setattr("app.inventory.upc_service.lookup_upc_title", lambda _upc: None)


def _review_status(session: Session, scan_id: int) -> UnknownUpcStatus:
    scan = session.get(UnknownUpcScan, scan_id)
    assert scan is not None
    return scan.status


def test_the_review_list_groups_pending_and_ignored_barcodes(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _review_row(session, agency.id, PENDING_UPC)
    _review_row(session, agency.id, IGNORED_UPC, status=UnknownUpcStatus.IGNORE)

    response = admin_client.get(_api(agency.id))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert [row["upc"] for row in body["pending"]] == [PENDING_UPC]
    assert [row["upc"] for row in body["ignored"]] == [IGNORED_UPC]


def test_a_review_row_carries_its_online_guess_and_suggested_item(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _review_row(session, agency.id, PENDING_UPC, lookup_title=LOOKUP_TITLE, suggested_item_id=agency.item.id)

    [row] = admin_client.get(_api(agency.id)).get_json()["pending"]

    assert row["lookup_title"] == LOOKUP_TITLE
    assert (row["suggested_item_id"], row["suggested_item_name"]) == (agency.item.id, agency.item.name)
    assert row["first_scanned_at"].endswith("+00:00")
    assert row["last_scanned_at"].endswith("+00:00")


def test_a_resolved_barcode_is_not_in_the_review_list(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _review_row(session, agency.id, PENDING_UPC, status=UnknownUpcStatus.RESOLVED)

    body = admin_client.get(_api(agency.id)).get_json()

    assert (body["pending"], body["ignored"]) == ([], [])


def test_a_barcode_is_linked_to_an_existing_item(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)

    response = admin_client.post(_api(agency.id, f"/{scan.id}/item"), json={"item_id": agency.item.id})

    assert response.status_code == HTTPStatus.NO_CONTENT
    session.expire_all()
    linked = session.query(ItemSecondaryUpc).filter_by(agency_id=agency.id, upc=PENDING_UPC).one()
    assert linked.item_id == agency.item.id
    assert _review_status(session, scan.id) == UnknownUpcStatus.RESOLVED


def test_a_barcode_an_item_already_carries_cannot_be_linked_again(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)
    session.add(ItemSecondaryUpc(agency_id=agency.id, item_id=agency.item.id, upc=PENDING_UPC))
    session.commit()

    response = admin_client.post(_api(agency.id, f"/{scan.id}/item"), json={"item_id": agency.item.id})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "already linked" in response.get_json()["message"]


def test_a_barcode_cannot_be_linked_to_another_agencys_item(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)
    other_item = build_item(session, build_agency(session).id, name="Someone Elses Splint")
    session.commit()

    response = admin_client.post(_api(agency.id, f"/{scan.id}/item"), json={"item_id": other_item.id})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    session.expire_all()
    assert _review_status(session, scan.id) == UnknownUpcStatus.PENDING


def test_a_link_without_an_item_is_refused(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)

    assert admin_client.post(_api(agency.id, f"/{scan.id}/item"), json={}).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_ignoring_a_barcode_moves_it_out_of_the_pending_list(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)

    assert admin_client.post(_api(agency.id, f"/{scan.id}/ignore")).status_code == HTTPStatus.NO_CONTENT

    body = admin_client.get(_api(agency.id)).get_json()
    assert (body["pending"], [row["upc"] for row in body["ignored"]]) == ([], [PENDING_UPC])


def test_an_ignored_barcode_moves_back_to_pending(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, IGNORED_UPC, status=UnknownUpcStatus.IGNORE)

    assert admin_client.post(_api(agency.id, f"/{scan.id}/pending")).status_code == HTTPStatus.NO_CONTENT

    body = admin_client.get(_api(agency.id)).get_json()
    assert ([row["upc"] for row in body["pending"]], body["ignored"]) == ([IGNORED_UPC], [])


def test_only_an_ignored_barcode_can_be_moved_back_to_pending(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)

    response = admin_client.post(_api(agency.id, f"/{scan.id}/pending"))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "Ignored UPC not found." in response.get_json()["message"]


def test_deleting_a_barcode_removes_its_review_row(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    scan = _review_row(session, agency.id, PENDING_UPC)

    assert admin_client.delete(_api(agency.id, f"/{scan.id}")).status_code == HTTPStatus.NO_CONTENT

    session.expire_all()
    assert session.get(UnknownUpcScan, scan.id) is None


def test_a_review_row_that_does_not_exist_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id, "/4321/ignore"))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "not found" in response.get_json()["message"]


def test_another_agencys_review_row_cannot_be_resolved(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)
    other_scan = _review_row(session, other.id, PENDING_UPC)

    response = admin_client.post(_api(agency.id, f"/{other_scan.id}/ignore"))

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    session.expire_all()
    assert _review_status(session, other_scan.id) == UnknownUpcStatus.PENDING


def test_another_agencys_review_list_is_refused(admin_client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert admin_client.get(_api(other.id)).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures("no_upc_title_lookup")
def test_a_barcode_added_by_hand_joins_the_pending_list(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json={"upc": ADDED_UPC})

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert (body["upc"], body["status"]) == (ADDED_UPC, UnknownUpcStatus.PENDING)
    assert body["message"] == "Barcode ready to link."
    assert [row["upc"] for row in admin_client.get(_api(agency.id)).get_json()["pending"]] == [ADDED_UPC]


@pytest.mark.usefixtures("no_upc_title_lookup")
def test_a_barcode_an_item_already_carries_is_reported_as_linked(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json={"upc": agency.item.upc})

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert body["status"] == UnknownUpcStatus.RESOLVED
    assert "already linked" in body["message"]


@pytest.mark.parametrize("upc", [WRONG_CHECK_DIGIT_UPC, TOO_SHORT_UPC, "not-a-barcode"])
@pytest.mark.usefixtures("no_upc_title_lookup")
def test_a_malformed_barcode_is_refused_and_never_recorded(admin_client: FlaskClient, agency: AgencyFixture, session: Session, upc: str) -> None:
    response = admin_client.post(_api(agency.id), json={"upc": upc})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert session.query(UnknownUpcScan).count() == 0


@pytest.mark.usefixtures("no_upc_title_lookup")
def test_a_twelve_digit_barcode_with_a_bad_check_digit_says_so(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json={"upc": WRONG_CHECK_DIGIT_UPC})

    assert "check digit" in response.get_json()["message"]


def test_an_unexpected_field_in_an_added_barcode_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_api(agency.id), json={"upc": ADDED_UPC, "status": "RESOLVED"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", ""),
        ("post", "/1/item"),
        ("post", "/1/ignore"),
        ("post", "/1/pending"),
        ("delete", "/1"),
    ],
)
def test_every_review_endpoint_refuses_a_browser_that_has_not_unlocked_admin(
    client: FlaskClient, agency: AgencyFixture, method: str, path: str
) -> None:
    response = getattr(client, method)(_api(agency.id, path), json={})

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_the_v1_unknown_barcodes_page_still_answers(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _review_row(session, agency.id, PENDING_UPC)
    _review_row(session, agency.id, IGNORED_UPC, status=UnknownUpcStatus.IGNORE)

    response = admin_client.get(V1_REVIEW_PAGE.format(agency_id=agency.id))

    assert response.status_code == HTTPStatus.OK
    assert PENDING_UPC in response.get_data(as_text=True)
    assert IGNORED_UPC in response.get_data(as_text=True)
