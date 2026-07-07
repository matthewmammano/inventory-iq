"""Pydantic models for auth inputs/outputs."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.shared.validation_types import (
    AdminPin,
    DisplayName,
    EmailAddress128,
    ImageSource,
    LocationName,
    Password,
    ResetPin,
    StorageName,
    TagColor,
    TagName,
)

from .models import validate_timezone


class LoginRequest(BaseModel):
    """Login request payload."""

    email: EmailAddress128
    password: str = Field(min_length=1)


class ForgotPasswordRequest(BaseModel):
    """Forgot-password request payload."""

    email: EmailAddress128


class ResetPasswordRequest(BaseModel):
    """Password reset request payload."""

    email: EmailAddress128
    pin: ResetPin
    password: Password


class AgencyResponse(BaseModel):
    """Agency response payload."""

    id: int
    display_name: DisplayName
    email: EmailAddress128
    image: ImageSource = None
    timezone: str
    active: bool
    created_at: datetime

    @field_validator("timezone")
    @classmethod
    def validate_timezone_value(cls, value: str) -> str:
        return validate_timezone(value)


class AgencyTagResponse(BaseModel):
    """Agency item tag response payload."""

    id: int
    tag_name: TagName
    color: TagColor


class AgencyLocationResponse(BaseModel):
    """Agency location response payload."""

    id: int
    name: LocationName


class AgencyStorageResponse(BaseModel):
    """Agency storage response payload."""

    id: int
    location_id: int
    name: StorageName
    user_access_from: bool
    user_access_to: bool


class PinRequest(BaseModel):
    """PIN-only request payload."""

    pin: AdminPin
