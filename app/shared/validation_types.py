"""Reusable Pydantic field aliases and frontend validation specs."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator

from app.shared.validators import (
    PASSWORD_MIN_LENGTH,
    PASSWORD_REQUIREMENTS_MESSAGE,
    normalize_hex_color,
    parse_optional_int,
    validate_email_format,
    validate_hhmm_time,
    validate_image_url,
    validate_non_negative_integer,
    validate_password_strength,
    validate_pin,
    validate_pin_length,
    validate_positive_integer,
    validate_string_length,
)


def _required_string(field_name: str, max_length: int):
    return AfterValidator(lambda value: validate_string_length(value, field_name, max_length, allow_none=False, allow_empty=False) or "")


def _optional_string(field_name: str, max_length: int):
    return AfterValidator(lambda value: validate_string_length(value, field_name, max_length, allow_none=True, allow_empty=True))


def _validated_email(max_length: int):
    return AfterValidator(lambda value: validate_email_format(value, max_length=max_length, allow_none=False) or "")


def _validated_time(field_name: str):
    return AfterValidator(lambda value: validate_hhmm_time(value, field_name))


def _required_positive_int(field_name: str):
    return AfterValidator(lambda value: validate_positive_integer(value, field_name, allow_none=False))


def _optional_positive_int(field_name: str):
    return AfterValidator(lambda value: validate_positive_integer(value, field_name, allow_none=True))


def _required_non_negative_int(field_name: str):
    return AfterValidator(lambda value: validate_non_negative_integer(value, field_name, allow_none=False))


def _required_non_negative_float(field_name: str):
    def validate(value: float | int) -> float:
        normalized = float(value)
        if normalized < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return normalized

    return AfterValidator(validate)


def _parsed_required_non_negative_int(field_name: str):
    def parse(value: int | str | None) -> int:
        if value is None or value == "":
            raise ValueError(f"{field_name} is required")
        if isinstance(value, int):
            normalized = validate_non_negative_integer(value, field_name, allow_none=False)
            if normalized is None:
                raise ValueError(f"{field_name} is required")
            return normalized
        if isinstance(value, str) and value.isdigit():
            return int(value)
        raise ValueError(f"{field_name} must be a valid number")

    return BeforeValidator(parse)


DisplayName = Annotated[str, _required_string("display_name", 50)]
EmailAddress128 = Annotated[str, _validated_email(128)]
ImageSource = Annotated[str | None, AfterValidator(validate_image_url)]
Increments = Annotated[str | None, _optional_string("increments", 50)]
ItemName = Annotated[str, _required_string("name", 100)]
LocationName = Annotated[str, _required_string("name", 50)]
OptionalPositiveInt = Annotated[int | None, _optional_positive_int("value")]
PositiveInt = Annotated[int, _required_positive_int("value")]
QuietTime = Annotated[str | None, _validated_time("quiet time")]
QuantityDelta = Annotated[int, _required_non_negative_int("quantity_delta")]
ResetPin = Annotated[str, AfterValidator(lambda value: validate_pin_length(value, 6))]
Password = Annotated[str, AfterValidator(validate_password_strength)]
StorageName = Annotated[str, _required_string("name", 50)]
TagName = Annotated[str, _required_string("tag_name", 50)]
OptionalParsedInt = Annotated[int | None, BeforeValidator(parse_optional_int)]
RequiredCountInput = Annotated[int, _parsed_required_non_negative_int("Quantity")]
AdminPin = Annotated[str, AfterValidator(validate_pin)]
TagColor = Annotated[str, AfterValidator(normalize_hex_color)]
NonNegativeFloat = Annotated[float, _required_non_negative_float("value")]


@dataclass(frozen=True)
class FieldSpec:
    label: str
    message: str
    schema_type: Any
    validators: tuple[str, ...] = ()
    input_type: str | None = None
    inputmode: str | None = None
    pattern: str | None = None
    maxlength: int | None = None
    min_value: int | float | None = None
    password_min_length: int | None = None
    step: str | None = None
    required: bool = False
    placeholder: str | None = None

    def with_options(self, **overrides: Any) -> "FieldSpec":
        values = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **values)


class FieldRuleName(StrEnum):
    EMAIL_128 = "email_128"
    HEX_COLOR = "hex_color"
    HHMM_TIME = "hhmm_time"
    IMAGE_SOURCE = "image_source"
    INCREMENTS = "increments"
    ITEM_NAME = "item_name"
    ISO_DATE = "iso_date"
    NON_NEGATIVE_NUMBER = "non_negative_number"
    NON_NEGATIVE_INT = "non_negative_int"
    PASSWORD = "password"  # nosec B105 - validation rule identifier, not a credential
    PIN4 = "pin4"
    PIN6 = "pin6"
    POSITIVE_INT = "positive_int"
    OPTIONAL_POSITIVE_INT = "optional_positive_int"
    REQUIRED_TEXT = "required_text"
    REQUIRED_CHOICE = "required_choice"
    TAG_NAME = "tag_name"
    UPC12 = "upc12"


FIELD_SPECS: Mapping[FieldRuleName, FieldSpec] = {
    FieldRuleName.EMAIL_128: FieldSpec("Email Address", "Enter a valid email address.", EmailAddress128, ("email",), maxlength=128),
    FieldRuleName.HEX_COLOR: FieldSpec("Color", "Choose a valid color.", TagColor, ("hex_color",), input_type="color"),
    FieldRuleName.HHMM_TIME: FieldSpec("Time", "Use HH:MM time.", QuietTime, ("hhmm_time",), input_type="time"),
    FieldRuleName.IMAGE_SOURCE: FieldSpec("Image", "Image must load from a valid URL.", ImageSource, ("image_source",), maxlength=1020),
    FieldRuleName.INCREMENTS: FieldSpec("Increments", "Increments cannot exceed 50 characters.", Increments, ("max_length",), maxlength=50),
    FieldRuleName.ITEM_NAME: FieldSpec("Item Name", "Item name is required.", ItemName, ("max_length",), maxlength=100, required=True),
    FieldRuleName.ISO_DATE: FieldSpec("Date", "Enter a valid date.", str, ("iso_date",), input_type="date"),
    FieldRuleName.NON_NEGATIVE_NUMBER: FieldSpec(
        "Number", "Enter 0 or higher.", float, ("non_negative_number",), input_type="number", min_value=0, step="any"
    ),
    FieldRuleName.NON_NEGATIVE_INT: FieldSpec(
        "Quantity", "Enter 0 or higher.", QuantityDelta, ("non_negative_int",), input_type="number", min_value=0
    ),
    FieldRuleName.PASSWORD: FieldSpec(
        "Password",
        PASSWORD_REQUIREMENTS_MESSAGE,
        Password,
        ("password",),
        password_min_length=PASSWORD_MIN_LENGTH,
        required=True,
    ),
    FieldRuleName.PIN4: FieldSpec(
        "Admin PIN", "PIN must be exactly 4 digits.", AdminPin, ("pin4",), inputmode="numeric", pattern="[0-9]{4}", maxlength=4, required=True
    ),
    FieldRuleName.PIN6: FieldSpec(
        "Reset PIN", "PIN must be exactly 6 digits.", ResetPin, ("pin6",), inputmode="numeric", pattern="[0-9]{6}", maxlength=6, required=True
    ),
    FieldRuleName.POSITIVE_INT: FieldSpec(
        "Number", "Enter a positive whole number.", PositiveInt, ("positive_int",), input_type="number", min_value=1, required=True
    ),
    FieldRuleName.OPTIONAL_POSITIVE_INT: FieldSpec(
        "Number", "Enter a positive whole number.", OptionalPositiveInt, ("positive_int",), input_type="number", min_value=1
    ),
    FieldRuleName.REQUIRED_TEXT: FieldSpec("Field", "This field is required.", str, required=True),
    FieldRuleName.REQUIRED_CHOICE: FieldSpec("Selection", "Select an option.", str, required=True),
    FieldRuleName.TAG_NAME: FieldSpec("Tag Name", "Tag name is required.", TagName, ("max_length",), maxlength=50, required=True),
    FieldRuleName.UPC12: FieldSpec("UPC", "UPC must be 12 digits.", str, ("upc12",), inputmode="numeric", pattern="[0-9]{12}", maxlength=12),
}
