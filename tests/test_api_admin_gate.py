"""The admin_only gate every admin JSON endpoint sits behind, driven over real HTTP."""

from collections.abc import Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Final

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import BaseModel

from app.api.admin_access import ADMIN_LOCKED_MESSAGE, admin_only
from app.api.blueprint import api_bp
from app.api.constants import API_URL_PREFIX
from app.api.schema import LOCKED_INPUT
from app.auth.admin_session import ADMIN_FLAG_KEY, ADMIN_LAST_ACTIVE_KEY
from app.shared.constants import ADMIN_TIMEOUT
from tests.factories import AgencyFixture

PROBE_PATH: Final[str] = "/test-only/admin-gated"
GATED_ROUTE: Final[str] = f"{API_URL_PREFIX}{PROBE_PATH}"


class _ProbeRequest(BaseModel):
    """A body the probe route requires, so refusal order against validation is observable."""

    model_config = LOCKED_INPUT

    needed: int


@api_bp.get(PROBE_PATH)
@api_bp.doc(hide=True)
@admin_only
def admin_gated_probe() -> dict[str, bool]:
    """A throwaway route carrying nothing but the gate, registered before any app is built."""
    return {"reached": True}


@api_bp.post(PROBE_PATH)
@api_bp.input(_ProbeRequest)
@api_bp.doc(hide=True)
@admin_only
def admin_gated_probe_with_body(json_data: _ProbeRequest) -> dict[str, int]:
    """The same gate on a route that also parses a body."""
    return {"needed": json_data.needed}


def _client(app: Flask, agency_id: int | None, *, unlocked_at: float | None) -> FlaskClient:
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        if agency_id is not None:
            flask_session["_user_id"] = str(agency_id)
        if unlocked_at is not None:
            flask_session[ADMIN_FLAG_KEY] = True
            flask_session[ADMIN_LAST_ACTIVE_KEY] = unlocked_at
    return test_client


@pytest.fixture
def unlocked(app: Flask, agency: AgencyFixture) -> Iterator[FlaskClient]:
    yield _client(app, agency.id, unlocked_at=datetime.now(UTC).timestamp())


@pytest.fixture
def locked(app: Flask, agency: AgencyFixture) -> Iterator[FlaskClient]:
    yield _client(app, agency.id, unlocked_at=None)


def test_an_unlocked_browser_reaches_an_admin_endpoint(unlocked: FlaskClient) -> None:
    response = unlocked.get(GATED_ROUTE)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == {"reached": True}


def test_a_signed_in_browser_that_never_unlocked_is_refused(locked: FlaskClient) -> None:
    response = locked.get(GATED_ROUTE)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()["message"] == ADMIN_LOCKED_MESSAGE


def test_the_lock_is_checked_before_the_body_is_validated(locked: FlaskClient, unlocked: FlaskClient) -> None:
    assert locked.post(GATED_ROUTE, json={}).status_code == HTTPStatus.FORBIDDEN
    assert unlocked.post(GATED_ROUTE, json={}).status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert unlocked.post(GATED_ROUTE, json={"needed": 2}).get_json() == {"needed": 2}


def test_an_idle_unlock_past_the_timeout_is_refused(app: Flask, agency: AgencyFixture) -> None:
    stale = datetime.now(UTC).timestamp() - ADMIN_TIMEOUT - 1
    response = _client(app, agency.id, unlocked_at=stale).get(GATED_ROUTE)

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_an_unlock_with_no_last_active_stamp_is_refused(app: Flask, agency: AgencyFixture) -> None:
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(agency.id)
        flask_session[ADMIN_FLAG_KEY] = True

    assert test_client.get(GATED_ROUTE).status_code == HTTPStatus.FORBIDDEN


def test_every_admin_call_pushes_the_idle_clock_forward(app: Flask, agency: AgencyFixture) -> None:
    nearly_stale = datetime.now(UTC).timestamp() - ADMIN_TIMEOUT + 5
    test_client = _client(app, agency.id, unlocked_at=nearly_stale)

    assert test_client.get(GATED_ROUTE).status_code == HTTPStatus.OK
    with test_client.session_transaction() as flask_session:
        assert flask_session[ADMIN_LAST_ACTIVE_KEY] > nearly_stale


def test_a_refused_call_clears_the_stale_unlock(app: Flask, agency: AgencyFixture) -> None:
    stale = datetime.now(UTC).timestamp() - ADMIN_TIMEOUT - 1
    test_client = _client(app, agency.id, unlocked_at=stale)

    test_client.get(GATED_ROUTE)

    with test_client.session_transaction() as flask_session:
        assert ADMIN_FLAG_KEY not in flask_session
