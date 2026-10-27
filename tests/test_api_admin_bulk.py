"""The JSON bulk-edit endpoints, driven over real HTTP as a signed-in, PIN-unlocked admin."""

from datetime import date, timedelta
from http import HTTPStatus
from typing import Any, Final

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin_access import ADMIN_LOCKED_MESSAGE
from app.api.admin_bulk import DATING_REQUIRED_MESSAGE, UNKNOWN_LOCATION_MESSAGE
from app.inventory.bulk_edit_service import EMPTY_SUBMISSION_MESSAGE, REQUIRED_COUNT_MESSAGE, UNKNOWN_CELL_MESSAGE
from app.inventory.constants import OperationType
from app.inventory.models import InventoryExpirationBalance, Item
from app.inventory.quantity_service import calculate_item_quantities
from tests.factories import AgencyFixture, build_agency, build_item

COUNTED_QUANTITY: Final[int] = 7
RESTOCK_QUANTITY: Final[int] = 3
NEAR_LOT: Final[int] = 4
FAR_LOT: Final[int] = 3
TRACKED_ITEM_NAME: Final[str] = "Saline Bags"


@pytest.fixture(autouse=True)
def no_email_leaves_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bulk save opens stock alert rows; nothing in this file may reach the real email client."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("A bulk-edit test tried to send email.")

    monkeypatch.setattr("app.shared.email_client.send_email", refuse)


def _bulk_url(agency_id: int, agency_location_id: int) -> str:
    return f"/api/v1/agencies/{agency_id}/locations/{agency_location_id}/bulk-edit"


def _cell(item_id: int, storage_id: int, quantity: int, **extra: Any) -> dict[str, Any]:
    return {"item_id": item_id, "storage_id": storage_id, "quantity": quantity, **extra}


def _tracked_item(session: Session, agency: AgencyFixture) -> Item:
    item = build_item(session, agency.id, name=TRACKED_ITEM_NAME, expiration_tracking=True)
    session.commit()
    return item


def _near() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


def _far() -> str:
    return (date.today() + timedelta(days=300)).isoformat()


def _expiration_balances(session: Session, agency_id: int) -> list[InventoryExpirationBalance]:
    return list(
        session.execute(
            select(InventoryExpirationBalance)
            .where(InventoryExpirationBalance.agency_id == agency_id)
            .order_by(InventoryExpirationBalance.expires_on)
        )
        .scalars()
        .all()
    )


def test_the_grid_lists_every_storage_and_every_active_item(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tracked = _tracked_item(session, agency)

    response = admin_client.get(_bulk_url(agency.id, agency.location.id))

    assert response.status_code == HTTPStatus.OK
    body = response.get_json()
    assert body["location_name"] == agency.location.name
    assert {storage["id"] for storage in body["storages"]} == {agency.shelf.id, agency.truck.id}
    assert {row["item_id"] for row in body["rows"]} == {agency.item.id, tracked.id}
    assert {row["item_name"]: row["expiration_tracking"] for row in body["rows"]}[TRACKED_ITEM_NAME] is True


def test_an_item_never_counted_here_reads_as_stale_in_every_storage(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    body = admin_client.get(_bulk_url(agency.id, agency.location.id)).get_json()

    [row] = [row for row in body["rows"] if row["item_id"] == agency.item.id]
    assert row["stale"] is True
    assert [cell["count_required"] for cell in row["cells"]] == [True, True]
    assert [cell["quantity"] for cell in row["cells"]] == [0, 0]
    assert body["stale_count_days"] >= 1


def test_another_agencys_location_is_not_found(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_location = build_agency(session).location

    response = admin_client.get(_bulk_url(agency.id, other_location.id))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.get_json()["message"] == UNKNOWN_LOCATION_MESSAGE


def test_a_count_submission_is_saved_and_reports_what_it_wrote(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(agency.item.id, agency.shelf.id, COUNTED_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.get_json()
    assert (body["count_entry_count"], body["restock_entry_count"], body["entry_count"]) == (1, 0, 1)
    assert calculate_item_quantities(session, agency.id, agency.item.id).get(agency.shelf.id) == COUNTED_QUANTITY


def test_a_restock_is_saved_once_the_same_submission_counts_the_storage(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={
            "counts": [
                _cell(agency.item.id, agency.shelf.id, COUNTED_QUANTITY),
                _cell(agency.item.id, agency.truck.id, COUNTED_QUANTITY),
            ],
            "restocks": [_cell(agency.item.id, agency.shelf.id, RESTOCK_QUANTITY)],
        },
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.get_json()["entry_count"] == 3
    assert calculate_item_quantities(session, agency.id, agency.item.id).get(agency.shelf.id) == COUNTED_QUANTITY + RESTOCK_QUANTITY


def test_restocking_a_storage_whose_count_has_gone_stale_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"restocks": [_cell(agency.item.id, agency.shelf.id, RESTOCK_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.get_json()["message"] == REQUIRED_COUNT_MESSAGE


def test_a_submission_with_no_entries_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(_bulk_url(agency.id, agency.location.id), json={})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.get_json()["message"] == EMPTY_SUBMISSION_MESSAGE


def test_a_tracked_item_answers_with_what_still_needs_dating(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tracked = _tracked_item(session, agency)

    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(tracked.id, agency.shelf.id, COUNTED_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.CONFLICT
    body = response.get_json()
    assert body["message"] == DATING_REQUIRED_MESSAGE
    [group] = body["needs_dating"]
    assert (group["item_id"], group["storage_id"]) == (tracked.id, agency.shelf.id)
    assert group["operation"] == OperationType.COUNT
    assert group["entry"]["target_quantity"] == COUNTED_QUANTITY
    assert group["entry"]["allows_new_dates"] is True
    assert group["entry"]["requires_exact_total"] is True
    assert not _expiration_balances(session, agency.id)


def test_an_untracked_cell_in_the_same_submission_does_not_hold_up_dating(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tracked = _tracked_item(session, agency)

    body = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={
            "counts": [
                _cell(agency.item.id, agency.shelf.id, COUNTED_QUANTITY),
                _cell(tracked.id, agency.shelf.id, COUNTED_QUANTITY),
            ]
        },
    ).get_json()

    assert [group["item_id"] for group in body["needs_dating"]] == [tracked.id]


def test_the_same_draft_saves_once_the_dates_come_back(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tracked = _tracked_item(session, agency)
    allocations = [{"expires_on": _near(), "quantity": NEAR_LOT}, {"expires_on": _far(), "quantity": FAR_LOT}]

    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(tracked.id, agency.shelf.id, COUNTED_QUANTITY, expiration_allocations=allocations)]},
    )

    assert response.status_code == HTTPStatus.CREATED
    assert calculate_item_quantities(session, agency.id, tracked.id).get(agency.shelf.id) == COUNTED_QUANTITY
    assert [balance.quantity for balance in _expiration_balances(session, agency.id)] == [NEAR_LOT, FAR_LOT]


def test_dates_that_do_not_add_up_to_the_counted_quantity_are_refused(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    tracked = _tracked_item(session, agency)
    allocations = [{"expires_on": _near(), "quantity": NEAR_LOT}]

    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(tracked.id, agency.shelf.id, COUNTED_QUANTITY, expiration_allocations=allocations)]},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "match the action quantity" in response.get_json()["message"]
    assert not _expiration_balances(session, agency.id)


def test_another_agencys_item_cannot_be_edited_through_this_location(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_item = build_item(session, build_agency(session).id, name="Someone Elses Splint")
    session.commit()

    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(other_item.id, agency.shelf.id, COUNTED_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.get_json()["message"] == UNKNOWN_CELL_MESSAGE


def test_another_agencys_storage_cannot_be_edited_through_this_location(admin_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    other_storage = build_agency(session).shelf

    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(agency.item.id, other_storage.id, COUNTED_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.get_json()["message"] == UNKNOWN_CELL_MESSAGE


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"counts": [{"item_id": 1, "storage_id": 1, "quantity": -1}]}, id="negative quantity"),
        pytest.param({"counts": [{"item_id": 1, "storage_id": 1}]}, id="missing quantity"),
        pytest.param({"counts": [{"item_id": 1, "storage_id": 1, "quantity": 1, "admin": True}]}, id="unexpected field"),
        pytest.param({"takeouts": [{"item_id": 1, "storage_id": 1, "quantity": 1}]}, id="unexpected operation"),
    ],
)
def test_a_malformed_submission_is_refused_at_the_schema(admin_client: FlaskClient, agency: AgencyFixture, body: dict[str, Any]) -> None:
    response = admin_client.post(_bulk_url(agency.id, agency.location.id), json=body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_the_same_cell_twice_in_one_operation_is_refused(admin_client: FlaskClient, agency: AgencyFixture) -> None:
    response = admin_client.post(
        _bulk_url(agency.id, agency.location.id),
        json={
            "counts": [
                _cell(agency.item.id, agency.shelf.id, COUNTED_QUANTITY),
                _cell(agency.item.id, agency.shelf.id, RESTOCK_QUANTITY),
            ]
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_the_grid_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.get(_bulk_url(agency.id, agency.location.id))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()["message"] == ADMIN_LOCKED_MESSAGE


def test_a_submission_is_refused_while_admin_is_locked(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    response = client.post(
        _bulk_url(agency.id, agency.location.id),
        json={"counts": [_cell(agency.item.id, agency.shelf.id, COUNTED_QUANTITY)]},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert calculate_item_quantities(session, agency.id, agency.item.id).get(agency.shelf.id) in (None, 0)


@pytest.mark.parametrize("suffix", ["", "/{location_id}", "/{location_id}/items", "/{location_id}/edit"])
def test_the_v1_bulk_edit_pages_still_render(admin_client: FlaskClient, agency: AgencyFixture, suffix: str) -> None:
    path = f"/inventory/{agency.id}/admin-panel/bulk-edit{suffix.format(location_id=agency.location.id)}"

    assert admin_client.get(path).status_code == HTTPStatus.OK
