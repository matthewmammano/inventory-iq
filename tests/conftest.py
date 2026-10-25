"""Throwaway-database fixtures. No real database is read or written."""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import email_validator
import pytest

# Address validation does a live DNS lookup by default; tests must not need the network.
email_validator.CHECK_DELIVERABILITY = False

_SCRATCH = tempfile.TemporaryDirectory()
# app.shared.config reads DATABASE_URL at import, so the throwaway path has to be set first.
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_SCRATCH.name) / 'placeholder.db'}"

from flask import Flask  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import create_app  # noqa: E402
from app.shared.database import create_all, get_session, init_db  # noqa: E402
from app.shared.model_registry import import_model_modules  # noqa: E402
from tests.actions import Squad  # noqa: E402
from tests.factories import AgencyFixture, build_agency  # noqa: E402


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(autouse=True)
def database(database_url: str) -> None:
    """Point the app at an empty database of its own, so no test can see another's rows."""
    import_model_modules()  # create_all only sees tables whose model module has been imported
    init_db(database_url)
    create_all()


@pytest.fixture
def session() -> Iterator[Session]:
    with get_session() as open_session:
        yield open_session


@pytest.fixture
def agency(session: Session) -> AgencyFixture:
    """One agency with a location, two storages, and one item."""
    return build_agency(session)


@pytest.fixture
def squad(agency: AgencyFixture, session: Session) -> Squad:
    """The agency, ready to scan."""
    return Squad(agency, session)


@pytest.fixture
def tracked_squad(session: Session) -> Squad:
    """A squad whose item has expiration tracking switched on."""
    return Squad(build_agency(session, expiration_tracking=True), session)


@pytest.fixture
def request_context() -> Iterator[None]:
    """Guest scans read the device cookie off the request, so that path needs a request to exist."""
    with Flask(__name__).test_request_context():
        yield


@pytest.fixture
def app(database_url: str) -> Iterator[Flask]:
    """The real app, put back on the throwaway database that create_app's own init_db replaced."""
    flask_app = create_app()
    flask_app.config["RATELIMIT_ENABLED"] = False  # one shared in-memory limiter would otherwise count across the suite
    init_db(database_url)
    yield flask_app


@pytest.fixture
def client(app: Flask, agency: AgencyFixture) -> Iterator[FlaskClient]:
    """A browser already signed in as the agency, the way every API caller arrives."""
    with app.test_client() as test_client:
        with test_client.session_transaction() as flask_session:
            flask_session["_user_id"] = str(agency.id)
        yield test_client


@pytest.fixture
def anonymous_client(app: Flask) -> Iterator[FlaskClient]:
    with app.test_client() as test_client:
        yield test_client
