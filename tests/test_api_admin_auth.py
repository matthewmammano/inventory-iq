"""The account sign-in and admin PIN endpoints, driven over real HTTP.

Nothing here reaches the temporary-PIN email path; the send function is mocked.
"""

from collections.abc import Iterator
from http import HTTPStatus
from typing import Final

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.admin_session import ADMIN_FLAG_KEY, ADMIN_LAST_ACTIVE_KEY
from app.auth.models import Agency
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.rate_limit import AUTH_ATTEMPT_LIMITS, limiter
from tests.factories import AGENCY_PASSWORD, AGENCY_PIN, AgencyFixture, build_agency

SESSION_ROUTE: Final[str] = "/api/v1/session"
ME_ROUTE: Final[str] = "/api/v1/me"
WRONG_PIN: Final[str] = "9999"
SHORT_PIN: Final[str] = "12"
WRONG_PASSWORD: Final[str] = "not-the-password"
ATTEMPTS_PER_MINUTE: Final[int] = int(AUTH_ATTEMPT_LIMITS[0].split()[0])


def _admin_session(agency_id: int, suffix: str = "") -> str:
    return f"/api/v1/agencies/{agency_id}/admin-session{suffix}"


def _credentials(agency: AgencyFixture, *, password: str = AGENCY_PASSWORD) -> dict[str, str]:
    return {"email": agency.agency.email, "password": password}


@pytest.fixture
def rate_limited_client(app: Flask) -> Iterator[FlaskClient]:
    """A signed-out browser with the real auth limits switched back on."""
    app.config["RATELIMIT_ENABLED"] = True
    limiter.reset()
    with app.test_client() as test_client:
        yield test_client
    limiter.reset()


def test_the_right_email_and_password_sign_in(anonymous_client: FlaskClient, agency: AgencyFixture) -> None:
    response = anonymous_client.post(SESSION_ROUTE, json=_credentials(agency))

    assert response.status_code == HTTPStatus.CREATED
    assert response.get_json()["id"] == agency.id
    assert anonymous_client.get(ME_ROUTE).status_code == HTTPStatus.OK


def test_a_wrong_password_is_refused(anonymous_client: FlaskClient, agency: AgencyFixture) -> None:
    response = anonymous_client.post(SESSION_ROUTE, json=_credentials(agency, password=WRONG_PASSWORD))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert anonymous_client.get(ME_ROUTE).status_code == HTTPStatus.UNAUTHORIZED


def test_an_unknown_email_is_refused_the_same_way_as_a_wrong_password(anonymous_client: FlaskClient, agency: AgencyFixture) -> None:
    unknown = anonymous_client.post(SESSION_ROUTE, json={"email": "nobody@example.com", "password": AGENCY_PASSWORD})
    wrong = anonymous_client.post(SESSION_ROUTE, json=_credentials(agency, password=WRONG_PASSWORD))

    assert unknown.status_code == wrong.status_code == HTTPStatus.UNAUTHORIZED
    assert unknown.get_json()["message"] == wrong.get_json()["message"]


def test_an_inactive_account_cannot_sign_in(anonymous_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    agency.agency.active = False
    session.commit()

    assert anonymous_client.post(SESSION_ROUTE, json=_credentials(agency)).status_code == HTTPStatus.UNAUTHORIZED


def test_an_account_with_no_password_is_sent_to_the_pin_flow(anonymous_client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    agency.agency.password = None
    session.commit()

    response = anonymous_client.post(SESSION_ROUTE, json=_credentials(agency))

    assert response.status_code == HTTPStatus.CONFLICT


def test_a_malformed_email_never_reaches_the_password_check(anonymous_client: FlaskClient) -> None:
    response = anonymous_client.post(SESSION_ROUTE, json={"email": "not-an-email", "password": AGENCY_PASSWORD})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_an_unexpected_field_is_refused(anonymous_client: FlaskClient, agency: AgencyFixture) -> None:
    response = anonymous_client.post(SESSION_ROUTE, json={**_credentials(agency), "admin": True})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_signing_out_ends_the_session_and_the_admin_unlock(client: FlaskClient, agency: AgencyFixture) -> None:
    client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN})

    assert client.delete(SESSION_ROUTE).status_code == HTTPStatus.NO_CONTENT
    assert client.get(ME_ROUTE).status_code == HTTPStatus.UNAUTHORIZED
    with client.session_transaction() as flask_session:
        assert ADMIN_FLAG_KEY not in flask_session


def test_the_right_pin_unlocks_admin(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN})

    assert response.status_code == HTTPStatus.CREATED
    assert response.get_json() == {"unlocked": True}
    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": True}


def test_a_wrong_pin_leaves_admin_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    response = client.post(_admin_session(agency.id), json={"pin": WRONG_PIN})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": False}


def test_a_pin_that_is_not_four_digits_is_refused_at_the_boundary(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.post(_admin_session(agency.id), json={"pin": SHORT_PIN}).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_admin_starts_locked(client: FlaskClient, agency: AgencyFixture) -> None:
    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": False}


def test_an_anonymous_browser_cannot_reach_the_pin_gate(anonymous_client: FlaskClient, agency: AgencyFixture) -> None:
    assert anonymous_client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN}).status_code == HTTPStatus.UNAUTHORIZED
    assert anonymous_client.get(_admin_session(agency.id)).status_code == HTTPStatus.UNAUTHORIZED


def test_another_agencys_pin_gate_is_out_of_reach(client: FlaskClient, session: Session) -> None:
    other = build_agency(session)

    assert client.post(_admin_session(other.id), json={"pin": AGENCY_PIN}).status_code == HTTPStatus.FORBIDDEN
    assert client.get(_admin_session(other.id)).status_code == HTTPStatus.FORBIDDEN


def test_an_inactive_account_cannot_unlock_admin(client: FlaskClient, agency: AgencyFixture, session: Session) -> None:
    agency.agency.active = False
    session.commit()

    assert client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN}).status_code == HTTPStatus.FORBIDDEN


def test_an_idle_admin_unlock_expires(client: FlaskClient, agency: AgencyFixture) -> None:
    client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN})
    with client.session_transaction() as flask_session:
        flask_session[ADMIN_LAST_ACTIVE_KEY] = flask_session[ADMIN_LAST_ACTIVE_KEY] - ADMIN_TIMEOUT - 1

    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": False}
    with client.session_transaction() as flask_session:
        assert ADMIN_FLAG_KEY not in flask_session


def test_an_unlock_with_no_last_active_stamp_is_refused(client: FlaskClient, agency: AgencyFixture) -> None:
    with client.session_transaction() as flask_session:
        flask_session[ADMIN_FLAG_KEY] = True

    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": False}


def test_reading_the_admin_session_keeps_it_alive(client: FlaskClient, agency: AgencyFixture) -> None:
    client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN})
    with client.session_transaction() as flask_session:
        stale = flask_session[ADMIN_LAST_ACTIVE_KEY] - ADMIN_TIMEOUT + 1
        flask_session[ADMIN_LAST_ACTIVE_KEY] = stale

    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": True}
    with client.session_transaction() as flask_session:
        assert flask_session[ADMIN_LAST_ACTIVE_KEY] > stale


def test_locking_admin_drops_the_unlock(client: FlaskClient, agency: AgencyFixture) -> None:
    client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN})

    assert client.delete(_admin_session(agency.id)).status_code == HTTPStatus.NO_CONTENT
    assert client.get(_admin_session(agency.id)).get_json() == {"unlocked": False}


def test_wrong_pins_run_out_of_attempts(rate_limited_client: FlaskClient, agency: AgencyFixture) -> None:
    with rate_limited_client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(agency.id)
    for _ in range(ATTEMPTS_PER_MINUTE):
        rate_limited_client.post(_admin_session(agency.id), json={"pin": WRONG_PIN})

    assert rate_limited_client.post(_admin_session(agency.id), json={"pin": AGENCY_PIN}).status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_a_correct_sign_in_is_never_charged_an_attempt(rate_limited_client: FlaskClient, agency: AgencyFixture) -> None:
    for _ in range(ATTEMPTS_PER_MINUTE + 1):
        response = rate_limited_client.post(SESSION_ROUTE, json=_credentials(agency))

    assert response.status_code == HTTPStatus.CREATED


def test_wrong_passwords_run_out_of_attempts(rate_limited_client: FlaskClient, agency: AgencyFixture) -> None:
    for _ in range(ATTEMPTS_PER_MINUTE):
        rate_limited_client.post(SESSION_ROUTE, json=_credentials(agency, password=WRONG_PASSWORD))

    assert rate_limited_client.post(SESSION_ROUTE, json=_credentials(agency)).status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_the_temporary_pin_endpoint_never_sends_without_the_mail_provider(
    client: FlaskClient, agency: AgencyFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent_to: list[int] = []

    def record(target: Agency) -> bool:
        sent_to.append(target.id)
        return True

    monkeypatch.setattr("app.api.admin_gate.send_temporary_admin_pin", record)

    response = client.post(_admin_session(agency.id, "/temporary-pin"))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert sent_to == [agency.id]


def test_a_temporary_pin_that_cannot_be_emailed_is_reported(client: FlaskClient, agency: AgencyFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin_gate.send_temporary_admin_pin", lambda _agency: False)

    assert client.post(_admin_session(agency.id, "/temporary-pin")).status_code == HTTPStatus.BAD_GATEWAY


def test_another_agency_cannot_ask_for_a_temporary_pin(client: FlaskClient, session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    other = build_agency(session)
    monkeypatch.setattr("app.api.admin_gate.send_temporary_admin_pin", lambda _agency: True)

    assert client.post(_admin_session(other.id, "/temporary-pin")).status_code == HTTPStatus.FORBIDDEN
