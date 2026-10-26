"""Deciding whether an email and password may sign in as an agency."""

from dataclasses import dataclass
from enum import StrEnum, auto

from sqlalchemy.orm import Session

from .models import Agency
from .queries import get_agency_by_email


class SignInOutcome(StrEnum):
    """Why a sign-in attempt was accepted or refused."""

    GRANTED = auto()
    REJECTED = auto()
    PASSWORD_NOT_SET = auto()


@dataclass(frozen=True, slots=True)
class SignInResult:
    outcome: SignInOutcome
    agency: Agency | None = None

    @property
    def agency_id(self) -> int | None:
        return self.agency.id if self.agency else None


def authenticate_agency(session: Session, email: str, password: str) -> SignInResult:
    """An unknown email, an inactive account, and a wrong password are one indistinguishable refusal."""
    agency = get_agency_by_email(email, session)
    if agency is None or not agency.active:
        return SignInResult(SignInOutcome.REJECTED)
    if not agency.password:
        return SignInResult(SignInOutcome.PASSWORD_NOT_SET, agency)
    if not agency.check_password(password):
        return SignInResult(SignInOutcome.REJECTED, agency)
    return SignInResult(SignInOutcome.GRANTED, agency)
