"""Expiration-dated stock must stay reconciled with the plain storage count."""

from datetime import date, timedelta
from typing import Final

import pytest
from sqlalchemy import select

from app.inventory.expiration_service import (
    ExpirationAllocation,
    effective_expiration_notice_days,
    expiration_count_needed,
    known_expiration_options,
    save_expiration_count_correction,
)
from app.inventory.models import InventoryExpirationBalance
from tests.actions import Squad

COUNTED_QUANTITY: Final[int] = 10
NEAR_LOT: Final[int] = 4
FAR_LOT: Final[int] = 6
AGENCY_DEFAULT_NOTICE_DAYS: Final[int] = 30
ITEM_NOTICE_OVERRIDE_DAYS: Final[int] = 7


def _near() -> date:
    return date.today() + timedelta(days=10)


def _far() -> date:
    return date.today() + timedelta(days=200)


def _balances(squad: Squad) -> list[InventoryExpirationBalance]:
    return list(
        squad.session.execute(
            select(InventoryExpirationBalance).where(InventoryExpirationBalance.agency_id == squad.id).order_by(InventoryExpirationBalance.expires_on)
        )
        .scalars()
        .all()
    )


def _correct(squad: Squad, allocations: list[ExpirationAllocation]) -> None:
    save_expiration_count_correction(squad.session, squad.id, squad.fixture.item.id, squad.fixture.shelf.id, allocations)


def _follow_up_needed(squad: Squad) -> bool:
    return expiration_count_needed(squad.session, squad.id, squad.fixture.item.id, squad.fixture.shelf.id)


def test_a_count_splits_stock_across_its_expiration_dates(tracked_squad: Squad) -> None:
    tracked_squad.count(
        COUNTED_QUANTITY,
        allocations=[ExpirationAllocation(_near(), NEAR_LOT), ExpirationAllocation(_far(), FAR_LOT)],
    )

    balances = _balances(tracked_squad)
    assert [balance.expires_on for balance in balances] == [_near(), _far()]
    assert [balance.quantity for balance in balances] == [NEAR_LOT, FAR_LOT]


def test_allocations_that_do_not_sum_to_the_count_are_refused(tracked_squad: Squad) -> None:
    with pytest.raises(ValueError, match="match the action quantity"):
        tracked_squad.count(COUNTED_QUANTITY, allocations=[ExpirationAllocation(_near(), NEAR_LOT)])


def test_a_negative_allocation_is_refused(tracked_squad: Squad) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        tracked_squad.count(
            COUNTED_QUANTITY,
            allocations=[ExpirationAllocation(_near(), -NEAR_LOT), ExpirationAllocation(_far(), COUNTED_QUANTITY + NEAR_LOT)],
        )


def test_a_tracked_count_must_allocate_every_unit(tracked_squad: Squad) -> None:
    with pytest.raises(ValueError, match="match the action quantity"):
        tracked_squad.count(COUNTED_QUANTITY)


def test_an_untracked_item_ignores_allocations(squad: Squad) -> None:
    squad.count(COUNTED_QUANTITY, allocations=[ExpirationAllocation(_near(), COUNTED_QUANTITY)])

    assert _balances(squad) == []


def test_stock_counted_before_tracking_was_enabled_needs_a_follow_up(squad: Squad) -> None:
    squad.count(COUNTED_QUANTITY)

    squad.fixture.item.expiration_tracking_enabled = True
    squad.session.flush()

    assert _follow_up_needed(squad) is True


def test_a_fully_allocated_count_needs_no_expiration_follow_up(tracked_squad: Squad) -> None:
    tracked_squad.count(COUNTED_QUANTITY, allocations=[ExpirationAllocation(_near(), COUNTED_QUANTITY)])

    assert _follow_up_needed(tracked_squad) is False


def test_a_correction_replaces_the_dates_without_touching_the_count(tracked_squad: Squad) -> None:
    tracked_squad.count(COUNTED_QUANTITY, allocations=[ExpirationAllocation(_near(), COUNTED_QUANTITY)])

    _correct(tracked_squad, [ExpirationAllocation(_far(), COUNTED_QUANTITY)])

    balances = _balances(tracked_squad)
    assert [balance.expires_on for balance in balances] == [_far()]
    assert [balance.quantity for balance in balances] == [COUNTED_QUANTITY]


def test_a_correction_must_match_the_current_count(tracked_squad: Squad) -> None:
    tracked_squad.count(COUNTED_QUANTITY, allocations=[ExpirationAllocation(_near(), COUNTED_QUANTITY)])

    with pytest.raises(ValueError, match="match the current item count"):
        _correct(tracked_squad, [ExpirationAllocation(_far(), NEAR_LOT)])


def test_a_correction_needs_an_existing_count(tracked_squad: Squad) -> None:
    with pytest.raises(ValueError, match="Item count not found"):
        _correct(tracked_squad, [ExpirationAllocation(_far(), COUNTED_QUANTITY)])


def test_only_positive_lots_are_offered_for_selection(tracked_squad: Squad) -> None:
    tracked_squad.count(
        COUNTED_QUANTITY,
        allocations=[ExpirationAllocation(_near(), 0), ExpirationAllocation(_far(), COUNTED_QUANTITY)],
    )

    options = known_expiration_options(tracked_squad.session, tracked_squad.id, tracked_squad.fixture.item.id, tracked_squad.fixture.shelf.id)
    assert [option.expires_on for option in options] == [_far()]


def test_an_item_override_beats_the_agency_notice_default(tracked_squad: Squad) -> None:
    item = tracked_squad.fixture.item
    assert effective_expiration_notice_days(item, AGENCY_DEFAULT_NOTICE_DAYS) == AGENCY_DEFAULT_NOTICE_DAYS

    item.expiration_notice_days_override = ITEM_NOTICE_OVERRIDE_DAYS
    tracked_squad.session.flush()

    assert effective_expiration_notice_days(item, AGENCY_DEFAULT_NOTICE_DAYS) == ITEM_NOTICE_OVERRIDE_DAYS
