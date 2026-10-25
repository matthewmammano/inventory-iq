"""Admin PIN, password reset, cross-agency isolation, and device location binding.

Nothing here touches the reset-email path; PIN rows are written directly.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Final

import pytest
from flask import Flask
from sqlalchemy.orm import Session

from app.auth.constants import RESET_PIN_MAX_ATTEMPTS, RESET_PIN_TTL_MINUTES
from app.auth.device_locations import DEVICE_COOKIE, get_device_location_id, save_device_location
from app.auth.models import PasswordResetPins
from app.auth.password_reset_service import reset_password_with_pin
from app.auth.queries import get_agency, get_agency_by_email, get_agency_permissions, get_storage, list_locations
from app.shared.clock import utc_now_naive
from tests.factories import AGENCY_PASSWORD, AGENCY_PIN, AgencyFixture, build_agency

WRONG_PIN: Final[str] = "9999"
RESET_PIN: Final[str] = "654321"
WRONG_RESET_PIN: Final[str] = "111111"
NEW_PASSWORD: Final[str] = "Rescue-9876"
DEVICE_TOKEN: Final[str] = "device-token-for-the-kiosk"
OTHER_DEVICE_TOKEN: Final[str] = "device-token-for-the-phone"


@contextmanager
def _device(token: str | None) -> Iterator[None]:
    """Device lookups read the cookie off the request, so that path needs one to exist."""
    cookies = {DEVICE_COOKIE: token} if token else {}
    with Flask(__name__).test_request_context(headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}):
        yield


def _open_pin(session: Session, agency_id: int, *, pin: str = RESET_PIN, minutes_left: int = RESET_PIN_TTL_MINUTES) -> PasswordResetPins:
    now = utc_now_naive()
    reset_pin = PasswordResetPins(agency_id=agency_id, expires_at=now + timedelta(minutes=minutes_left), created_at=now)
    reset_pin.set_pin(pin)
    session.add(reset_pin)
    session.commit()
    return reset_pin


def test_the_admin_pin_unlocks_only_with_the_right_digits(agency: AgencyFixture) -> None:
    assert agency.agency.check_pin(AGENCY_PIN) is True
    assert agency.agency.check_pin(WRONG_PIN) is False


def test_the_account_password_is_stored_hashed(agency: AgencyFixture) -> None:
    assert agency.agency.password != AGENCY_PASSWORD
    assert agency.agency.check_password(AGENCY_PASSWORD) is True
    assert agency.agency.check_password("not the password") is False


def test_an_account_with_no_password_rejects_every_attempt(agency: AgencyFixture) -> None:
    agency.agency.password = None
    assert agency.agency.check_password(AGENCY_PASSWORD) is False


def test_an_agency_is_found_by_its_own_email_only(agency: AgencyFixture, session: Session) -> None:
    found = get_agency_by_email(agency.agency.email, session)
    assert found is not None
    assert found.id == agency.id
    assert get_agency_by_email("nobody@example.com", session) is None


def test_guest_scanning_is_switched_off_until_an_agency_turns_it_on(agency: AgencyFixture, session: Session) -> None:
    permissions = get_agency_permissions(agency.id, session)
    assert permissions is not None
    assert (permissions.count, permissions.restock) == (False, False)


def test_permissions_for_an_agency_that_does_not_exist_are_none(session: Session) -> None:
    assert get_agency_permissions(agency_id=0, session=session) is None


def test_another_agencys_storage_is_not_reachable(agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)
    assert get_storage(other.shelf.id, other.id, session) is not None
    assert get_storage(other.shelf.id, agency.id, session) is None


def test_a_storage_list_stops_at_the_agency_boundary(agency: AgencyFixture, session: Session) -> None:
    build_agency(session)
    storages = list_locations(agency.id, session=session)
    assert {storage.id for storage in storages} == {agency.shelf.id, agency.truck.id}


def test_the_right_reset_pin_changes_the_password(agency: AgencyFixture, session: Session) -> None:
    _open_pin(session, agency.id)

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is True
    assert agency.agency.check_password(NEW_PASSWORD) is True
    assert agency.agency.check_password(AGENCY_PASSWORD) is False


def test_a_reset_pin_cannot_be_used_twice(agency: AgencyFixture, session: Session) -> None:
    _open_pin(session, agency.id)
    reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD)

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, "Second-5678") is False
    assert agency.agency.check_password(NEW_PASSWORD) is True


def test_a_wrong_reset_pin_is_counted_and_refused(agency: AgencyFixture, session: Session) -> None:
    reset_pin = _open_pin(session, agency.id)

    assert reset_password_with_pin(session, agency.agency.email, WRONG_RESET_PIN, NEW_PASSWORD) is False
    assert reset_pin.attempt_count == 1
    assert agency.agency.check_password(AGENCY_PASSWORD) is True


def test_guessing_runs_out_of_attempts(agency: AgencyFixture, session: Session) -> None:
    reset_pin = _open_pin(session, agency.id)
    for _ in range(RESET_PIN_MAX_ATTEMPTS):
        reset_password_with_pin(session, agency.agency.email, WRONG_RESET_PIN, NEW_PASSWORD)

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is False
    assert reset_pin.used_at is not None
    assert agency.agency.check_password(AGENCY_PASSWORD) is True


def test_an_expired_reset_pin_is_refused(agency: AgencyFixture, session: Session) -> None:
    _open_pin(session, agency.id, minutes_left=-1)

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is False
    assert agency.agency.check_password(AGENCY_PASSWORD) is True


def test_a_reset_with_no_pin_on_file_is_refused(agency: AgencyFixture, session: Session) -> None:
    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is False


def test_a_reset_for_an_unknown_email_is_refused(session: Session) -> None:
    assert reset_password_with_pin(session, "nobody@example.com", RESET_PIN, NEW_PASSWORD) is False


def test_a_deactivated_account_cannot_be_reset(agency: AgencyFixture, session: Session) -> None:
    _open_pin(session, agency.id)
    agency.agency.active = False
    session.commit()

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is False


def test_another_agencys_reset_pin_does_not_work(agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)
    _open_pin(session, other.id)

    assert reset_password_with_pin(session, agency.agency.email, RESET_PIN, NEW_PASSWORD) is False


def test_a_device_remembers_the_location_it_was_set_to(agency: AgencyFixture, session: Session) -> None:
    save_device_location(agency.id, DEVICE_TOKEN, agency.location.id, session)
    session.commit()

    with _device(DEVICE_TOKEN):
        assert get_device_location_id(agency.id, session) == agency.location.id


def test_a_different_device_gets_no_remembered_location(agency: AgencyFixture, session: Session) -> None:
    save_device_location(agency.id, DEVICE_TOKEN, agency.location.id, session)
    session.commit()

    with _device(OTHER_DEVICE_TOKEN):
        assert get_device_location_id(agency.id, session) is None


def test_a_device_with_no_cookie_gets_no_remembered_location(agency: AgencyFixture, session: Session) -> None:
    save_device_location(agency.id, DEVICE_TOKEN, agency.location.id, session)
    session.commit()

    with _device(None):
        assert get_device_location_id(agency.id, session) is None


def test_one_agencys_device_binding_is_invisible_to_another(agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)
    save_device_location(agency.id, DEVICE_TOKEN, agency.location.id, session)
    session.commit()

    with _device(DEVICE_TOKEN):
        assert get_device_location_id(other.id, session) is None


def test_a_device_cannot_be_bound_to_another_agencys_location(agency: AgencyFixture, session: Session) -> None:
    other = build_agency(session)

    with pytest.raises(ValueError, match="Location not found"):
        save_device_location(agency.id, DEVICE_TOKEN, other.location.id, session)


def test_clearing_a_devices_location_is_allowed(agency: AgencyFixture, session: Session) -> None:
    save_device_location(agency.id, DEVICE_TOKEN, agency.location.id, session)
    save_device_location(agency.id, DEVICE_TOKEN, None, session)
    session.commit()

    with _device(DEVICE_TOKEN):
        assert get_device_location_id(agency.id, session) is None


def test_an_agency_is_loaded_by_id_for_the_login_session(agency: AgencyFixture, session: Session) -> None:
    loaded = get_agency(agency.id, session)
    assert loaded is not None
    assert loaded.display_name == agency.agency.display_name
    assert get_agency(0, session) is None
