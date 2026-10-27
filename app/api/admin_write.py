"""One admin write in its own transaction, shared by the admin editing endpoints."""

from collections.abc import Callable
from http import HTTPStatus
from typing import Final

from apiflask import HTTPError
from sqlalchemy.orm import Session

from app.inventory.admin_edit_service import AdminRowNotFoundError
from app.shared.database import get_session

NO_CONTENT: Final[tuple[str, int]] = ("", HTTPStatus.NO_CONTENT)


def save_admin_row[Row, Result](action: Callable[[Session], Row], build: Callable[[Row, Session], Result]) -> Result:
    """Run one admin write in its own transaction, turning the service's refusals into JSON status codes."""
    with get_session() as session:
        try:
            row = action(session)
            session.commit()
        except AdminRowNotFoundError as error:
            raise HTTPError(HTTPStatus.NOT_FOUND, str(error)) from error
        except ValueError as error:
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        return build(row, session)


def deleted(_row: object, _session: Session) -> tuple[str, int]:
    return NO_CONTENT
