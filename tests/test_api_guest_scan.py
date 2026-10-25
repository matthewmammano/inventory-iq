"""The five JSON endpoints behind the guest scan screen, driven over real HTTP."""

from http import HTTPStatus
from typing import Any, Final

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.inventory.constants import OperationType, VirtualLocation
from app.inventory.quantity_service import calculate_item_quantities
from tests.actions import Squad
from tests.factories import AgencyFixture, build_agency, build_item

COUNTED_QUANTITY: Final[int] = 6
RESTOCK_QUANTITY: Final[int] = 4


def _api(agency_id: int, path: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}{path}"


def _allow_scanning(agency: AgencyFixture, session: Session, *, count: bool = True, restock: bool = True) -> None:
    agency.agency.user_count_allow = count
    agency.agency.user_restock_allow = restock
    session.commit()


def _scan_body(agency: AgencyFixture, *, source: int, destination: int, quantity: int, **extra: Any) -> dict[str, Any]:
    return {
        "item_id": agency.item.id,
        "from_storage_id": source,
        "to_storage_id": destination,
        "counter_value": quantity,
        **extra,
    }


def test_the_locations_endpoint_lists_the_agencys_own_locations(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, "/locations"))

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == [{"id": agency.location.id, "name": agency.location.name}]


def test_the_items_endpoint_lists_name_and_tags_without_a_quantity(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, "/items"))

    assert response.status_code == HTTPStatus.OK
    [item] = response.get_json()
    assert item["name"] == agency.item.name
    assert item["tags"] == []
    assert "quantity" not in item


def test_the_items_endpoint_stops_at_the_agency_boundary(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    build_item(session, build_agency(session).id, name="Someone Elses Splint")
    session.commit()

    names = {item["name"] for item in client.get(_api(agency.id, "/items")).get_json()}

    assert names == {agency.item.name}


def test_a_scanned_barcode_finds_its_item(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, "/items/lookup"), query_string={"upc": agency.item.upc})

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()["id"] == agency.item.id


def test_an_unknown_barcode_is_a_miss_not_an_error(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_api(agency.id, "/items/lookup"), query_string={"upc": "000000000000"})

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "barcode" in response.get_json()["message"]


def test_a_lookup_with_no_barcode_is_refused(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_api(agency.id, "/items/lookup")).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_another_agencys_barcode_is_not_found(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_item = build_item(session, build_agency(session).id, name="Someone Elses Gauze")
    session.commit()

    response = client.get(_api(agency.id, "/items/lookup"), query_string={"upc": other_item.upc})

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_the_storages_endpoint_reports_what_this_scanner_may_do(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session, count=True, restock=False)

    body = client.get(_api(agency.id, "/storages")).get_json()

    assert (body["can_count"], body["can_restock"]) == (True, False)
    assert {storage["id"] for storage in body["from_storages"]} == {agency.shelf.id, agency.truck.id}
    assert body["from_storages"][0]["location_name"] == agency.location.name


def test_guest_scanning_is_reported_as_off_until_the_agency_turns_it_on(client: FlaskClient, agency: AgencyFixture) -> None:
    body = client.get(_api(agency.id, "/storages")).get_json()

    assert (body["can_count"], body["can_restock"]) == (False, False)


def test_the_storages_endpoint_narrows_to_one_location(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_location = build_agency(session).location

    body = client.get(_api(agency.id, "/storages"), query_string={"location_id": agency.location.id}).get_json()

    assert body["default_location_id"] == agency.location.id
    assert {storage["id"] for storage in body["to_storages"]} == {agency.shelf.id, agency.truck.id}
    assert other_location.id != agency.location.id


def test_a_count_scan_is_saved_and_reports_what_it_did(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session)

    response = client.post(
        _api(agency.id, "/scans"),
        json=_scan_body(agency, source=VirtualLocation.COUNT, destination=agency.shelf.id, quantity=COUNTED_QUANTITY),
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert body["operation"] == OperationType.COUNT
    assert body["quantity"] == COUNTED_QUANTITY
    assert body["item_name"] == agency.item.name
    assert body["to_storage"]["id"] == agency.shelf.id
    assert body["from_storage"] is None


def test_a_saved_scan_changes_the_quantity_on_hand(client: FlaskClient, agency: AgencyFixture, session: Session, squad: Squad) -> None:
    _allow_scanning(agency, session)

    client.post(
        _api(agency.id, "/scans"),
        json=_scan_body(agency, source=VirtualLocation.COUNT, destination=agency.shelf.id, quantity=COUNTED_QUANTITY),
    )

    assert calculate_item_quantities(squad.session, agency.id, agency.item.id).get(agency.shelf.id) == COUNTED_QUANTITY


def test_a_restock_without_permission_is_refused(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session, count=True, restock=False)

    response = client.post(
        _api(agency.id, "/scans"),
        json=_scan_body(agency, source=VirtualLocation.RESTOCK, destination=agency.shelf.id, quantity=RESTOCK_QUANTITY),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "RESTOCK" in response.get_json()["message"]


def test_a_scan_of_another_agencys_item_is_not_found(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session)
    other_item = build_item(session, build_agency(session).id, name="Someone Elses Tape")
    session.commit()

    response = client.post(
        _api(agency.id, "/scans"),
        json={
            "item_id": other_item.id,
            "from_storage_id": VirtualLocation.COUNT,
            "to_storage_id": agency.shelf.id,
            "counter_value": COUNTED_QUANTITY,
        },
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_a_scan_into_another_agencys_storage_is_refused(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session)
    other_storage = build_agency(session).shelf

    response = client.post(
        _api(agency.id, "/scans"),
        json=_scan_body(agency, source=VirtualLocation.COUNT, destination=other_storage.id, quantity=COUNTED_QUANTITY),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_a_scan_missing_its_quantity_is_refused(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session)

    response = client.post(
        _api(agency.id, "/scans"),
        json={"item_id": agency.item.id, "from_storage_id": VirtualLocation.COUNT, "to_storage_id": agency.shelf.id},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_unexpected_field_in_a_scan_is_refused(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    _allow_scanning(agency, session)

    response = client.post(
        _api(agency.id, "/scans"),
        json=_scan_body(agency, source=VirtualLocation.COUNT, destination=agency.shelf.id, quantity=COUNTED_QUANTITY, admin_action=True),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.parametrize(
    "path",
    ["/locations", "/items", "/storages", "/scans"],
)
def test_every_endpoint_refuses_a_caller_who_is_not_signed_in(anonymous_client: FlaskClient, agency: AgencyFixture, path: str) -> None:
    response = anonymous_client.get(_api(agency.id, path))

    assert response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.METHOD_NOT_ALLOWED)


def test_a_signed_in_agency_cannot_read_another_agencys_data(client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    response = client.get(_api(other.id, "/items"))

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_an_inactive_agency_is_locked_out(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    agency.agency.active = False
    session.commit()

    assert client.get(_api(agency.id, "/items")).status_code == HTTPStatus.FORBIDDEN
