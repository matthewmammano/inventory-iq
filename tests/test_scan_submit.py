"""Saving one scan must move the right quantity and leave an audit row behind."""

from typing import Final

import pytest
from sqlalchemy.orm import Session

from app.inventory.constants import OperationType, VirtualLocation
from app.inventory.errors import InventoryError
from app.inventory.quantity_service import calculate_item_quantities
from app.inventory.scan_submit_service import ScanSubmitItemNotFoundError, ScanSubmitRouteError
from tests.actions import Squad
from tests.factories import build_agency

RESTOCK_QUANTITY: Final[int] = 8
TAKEOUT_QUANTITY: Final[int] = 3
TRANSFER_QUANTITY: Final[int] = 5
COUNTED_QUANTITY: Final[int] = 2


def _quantity_in(squad: Squad, storage_id: int) -> int:
    return calculate_item_quantities(squad.session, squad.id, squad.fixture.item.id).get(storage_id, 0)


def test_restock_is_refused_until_the_location_is_fully_counted(squad: Squad) -> None:
    with pytest.raises(InventoryError):
        squad.restock(RESTOCK_QUANTITY)


def test_restock_adds_to_the_destination(squad: Squad) -> None:
    squad.count_every_storage()

    result = squad.restock(RESTOCK_QUANTITY)

    assert result.operation_type == OperationType.RESTOCK
    assert _quantity_in(squad, squad.fixture.shelf.id) == RESTOCK_QUANTITY


def test_takeout_subtracts_from_the_source(squad: Squad) -> None:
    squad.count_every_storage()
    squad.restock(RESTOCK_QUANTITY)

    result = squad.take_out(TAKEOUT_QUANTITY)

    assert result.operation_type == OperationType.TAKEOUT
    assert _quantity_in(squad, squad.fixture.shelf.id) == RESTOCK_QUANTITY - TAKEOUT_QUANTITY


def test_transfer_moves_stock_without_changing_the_total(squad: Squad) -> None:
    squad.count_every_storage()
    squad.restock(RESTOCK_QUANTITY)

    result = squad.transfer(TRANSFER_QUANTITY, source=squad.fixture.shelf.id, destination=squad.fixture.truck.id)

    assert result.operation_type == OperationType.TRANSFER
    assert _quantity_in(squad, squad.fixture.shelf.id) == RESTOCK_QUANTITY - TRANSFER_QUANTITY
    assert _quantity_in(squad, squad.fixture.truck.id) == TRANSFER_QUANTITY


def test_count_replaces_the_quantity_instead_of_adjusting_it(squad: Squad) -> None:
    squad.count_every_storage()
    squad.restock(RESTOCK_QUANTITY)

    result = squad.count(COUNTED_QUANTITY)

    assert result.operation_type == OperationType.COUNT
    assert _quantity_in(squad, squad.fixture.shelf.id) == COUNTED_QUANTITY


def test_a_scan_records_who_did_it_and_how_much(squad: Squad) -> None:
    squad.count_every_storage()

    result = squad.restock(RESTOCK_QUANTITY)

    assert result.action.id
    assert result.action.agency_id == squad.id
    assert result.action.item_id == squad.fixture.item.id
    assert result.action.quantity == RESTOCK_QUANTITY
    assert result.action.admin_action is True
    assert result.action.to_storage_id == squad.fixture.shelf.id


@pytest.mark.usefixtures("request_context")
def test_a_guest_scan_is_not_recorded_as_an_admin_action(squad: Squad) -> None:
    squad.count_every_storage()

    result = squad.as_guest(permissions=squad.permissions).count(COUNTED_QUANTITY)

    assert result.action.admin_action is False


def test_another_agencys_item_is_not_reachable(squad: Squad, session: Session) -> None:
    other = build_agency(session)

    with pytest.raises(ScanSubmitItemNotFoundError):
        squad.count(COUNTED_QUANTITY, item_id=other.item.id)


@pytest.mark.usefixtures("request_context")
def test_restock_is_refused_without_the_restock_permission(squad: Squad) -> None:
    with pytest.raises(ScanSubmitRouteError):
        squad.as_guest().restock(RESTOCK_QUANTITY)


def test_a_storage_outside_the_agency_is_refused(squad: Squad, session: Session) -> None:
    other = build_agency(session)

    with pytest.raises(ScanSubmitRouteError):
        squad.restock(RESTOCK_QUANTITY, storage_id=other.shelf.id)


def test_a_scan_with_no_route_is_refused(squad: Squad) -> None:
    with pytest.raises(ScanSubmitRouteError):
        squad.scan(source=VirtualLocation.COUNT, destination=None, quantity=COUNTED_QUANTITY)
