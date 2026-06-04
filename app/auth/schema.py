"""Pydantic models for auth inputs/outputs."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from .constants import PASSWORD_MIN_LENGTH
from .models import (
    validate_email_format,
    validate_image_url,
    validate_password_strength,
    validate_pin,
    validate_string_length,
    validate_timezone,
)


class LoginRequest(BaseModel):
    """Login request payload."""

    email: EmailStr
    password: str = Field(min_length=1)


class SetPasswordRequest(BaseModel):
    """Set password request payload."""

    password: str = Field(min_length=PASSWORD_MIN_LENGTH)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class AgencyResponse(BaseModel):
    """Agency response payload."""

    id: int
    display_name: str
    email: EmailStr
    image: str | None = None
    timezone: str
    active: bool
    created_at: datetime

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return validate_string_length(value, "display_name", 50, allow_none=False, allow_empty=False) or ""

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_format(value, max_length=128, allow_none=False) or ""

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str | None) -> str | None:
        return validate_image_url(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class AgencyTagResponse(BaseModel):
    """Agency item tag response payload."""

    id: int
    tag_name: str
    color: str

    @field_validator("tag_name")
    @classmethod
    def validate_tag_name(cls, value: str) -> str:
        return validate_string_length(value, "tag_name", 50, allow_none=False, allow_empty=False) or ""


class AgencyLocationResponse(BaseModel):
    """Agency location response payload."""

    id: int
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_string_length(value, "name", 50, allow_none=False, allow_empty=False) or ""


class AgencyStorageResponse(BaseModel):
    """Agency storage response payload."""

    id: int
    location_id: int
    name: str
    user_access_from: bool
    user_access_to: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_string_length(value, "name", 50, allow_none=False, allow_empty=False) or ""


class PinRequest(BaseModel):
    """PIN-only request payload."""

    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin_value(cls, value: str) -> str:
        return validate_pin(value)
