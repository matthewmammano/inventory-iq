"""The shared validators every schema and ORM model leans on."""

from datetime import date
from typing import Final

import pytest
from pydantic import BaseModel, ValidationError

from app.shared.email_addresses import email_domain
from app.shared.text_formatting import pluralize
from app.shared.validation_types import AdminPin, AdminPinChange, EmailAddress128, RequiredCountInput, TagColor
from app.shared.validators import (
    MAX_SCAN_QUANTITY,
    PASSWORD_MIN_LENGTH,
    first_validation_error_message,
    normalize_hex_color,
    parse_non_negative_int,
    parse_optional_int,
    password_requirements_error,
    validate_hhmm_time,
    validate_image_url,
    validate_iso_date,
    validate_pin,
    validate_pin_length,
    validate_plausible_date,
    validate_quantity_bound,
    validate_string_length,
    validate_timezone,
)

GOOD_PASSWORD: Final[str] = "Squad-1234!"
DEFAULT_MESSAGE: Final[str] = "Could not save."
EARLIEST: Final[date] = date(2000, 1, 1)
LATEST: Final[date] = date(2100, 1, 1)


class _Pins(BaseModel):
    pin: AdminPin


class _PinChange(BaseModel):
    pin: AdminPinChange


class _Counted(BaseModel):
    quantity: RequiredCountInput


class _Colored(BaseModel):
    color: TagColor


class _Addressed(BaseModel):
    email: EmailAddress128


@pytest.mark.parametrize("digits", ["1234", "0000", "9999"])
def test_a_four_digit_pin_is_accepted(digits: str) -> None:
    assert validate_pin(digits) == digits


@pytest.mark.parametrize("rejected", ["123", "12345", "12a4", "", " 123", "12 4"])
def test_a_pin_that_is_not_four_digits_is_refused(rejected: str) -> None:
    with pytest.raises(ValueError, match="exactly 4 digits"):
        validate_pin(rejected)


def test_a_reset_pin_is_six_digits_not_four() -> None:
    assert validate_pin_length("123456", 6) == "123456"
    with pytest.raises(ValueError, match="exactly 6 digits"):
        validate_pin_length("1234", 6)


def test_a_pin_field_refuses_a_wrong_length_before_any_hashing() -> None:
    with pytest.raises(ValidationError):
        _Pins(pin="12")


def test_a_blank_pin_change_means_leave_it_alone() -> None:
    assert _PinChange(pin="   ").pin is None
    assert _PinChange(pin="4321").pin == "4321"


@pytest.mark.parametrize(
    ("given", "expected"),
    [("9:05", "09:05"), ("09:5", "09:05"), ("23:59", "23:59"), ("00:00", "00:00"), (" 7:30 ", "07:30")],
)
def test_a_clock_preference_is_normalized_to_hhmm(given: str, expected: str) -> None:
    assert validate_hhmm_time(given, "quiet time") == expected


@pytest.mark.parametrize("rejected", ["24:00", "12:60", "noon", "12", "-1:00"])
def test_an_impossible_clock_time_is_refused(rejected: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        validate_hhmm_time(rejected, "quiet time")


def test_a_clock_time_with_seconds_is_refused_by_width() -> None:
    with pytest.raises(ValueError, match="cannot exceed 5 characters"):
        validate_hhmm_time("12:34:56", "quiet time")


def test_a_blank_clock_time_clears_the_preference() -> None:
    assert validate_hhmm_time("", "quiet time") is None
    assert validate_hhmm_time(None, "quiet time") is None


@pytest.mark.parametrize(("given", "expected"), [("#aabbcc", "#AABBCC"), (" #FFEAB0 ", "#FFEAB0")])
def test_a_tag_color_is_normalized_to_upper_case_hex(given: str, expected: str) -> None:
    assert normalize_hex_color(given) == expected


@pytest.mark.parametrize("rejected", ["aabbcc", "#abc", "#gggggg", "", None, "#aabbccdd"])
def test_a_color_that_is_not_six_digit_hex_is_refused(rejected: str | None) -> None:
    with pytest.raises(ValueError, match="#rrggbb"):
        normalize_hex_color(rejected)


def test_a_tag_color_field_normalizes_through_the_schema() -> None:
    assert _Colored(color="#ffeab0").color == "#FFEAB0"


def test_a_password_names_every_requirement_it_is_missing() -> None:
    message = password_requirements_error("abc")

    assert f"{PASSWORD_MIN_LENGTH}+ characters" in message
    assert "a number" in message
    assert "a symbol" in message
    assert "a letter" not in message


def test_a_strong_password_has_nothing_missing() -> None:
    assert password_requirements_error(GOOD_PASSWORD) == ""


def test_a_long_password_still_needs_a_symbol() -> None:
    assert password_requirements_error("abcdefgh1234") == "Add a symbol."


@pytest.mark.parametrize(("given", "expected"), [("12", 12), (12, 12), ("  12  ", 12), ("", None), (None, None), ("x", None)])
def test_an_optional_int_parses_what_it_can_and_drops_the_rest(given: int | str | None, expected: int | None) -> None:
    assert parse_optional_int(given) == expected


@pytest.mark.parametrize(("given", "expected"), [("0", 0), ("12", 12), ("-1", None), ("1.5", None), ("", None), (None, None)])
def test_a_non_negative_int_refuses_a_sign_or_a_decimal(given: str | None, expected: int | None) -> None:
    assert parse_non_negative_int(given) == expected


def test_a_count_field_takes_a_digit_string_or_an_int() -> None:
    assert _Counted.model_validate({"quantity": "7"}).quantity == 7
    assert _Counted(quantity=0).quantity == 0


@pytest.mark.parametrize("rejected", ["", None, "-1", "seven", 1.5])
def test_a_count_field_refuses_anything_that_is_not_a_whole_count(rejected: object) -> None:
    with pytest.raises(ValidationError):
        _Counted.model_validate({"quantity": rejected})


def test_a_fat_fingered_quantity_is_refused_at_the_ceiling() -> None:
    assert validate_quantity_bound(MAX_SCAN_QUANTITY, "quantity") == MAX_SCAN_QUANTITY
    with pytest.raises(ValueError, match="or less"):
        validate_quantity_bound(MAX_SCAN_QUANTITY + 1, "quantity")


def test_a_count_field_refuses_a_quantity_past_the_ceiling() -> None:
    with pytest.raises(ValidationError):
        _Counted.model_validate({"quantity": str(MAX_SCAN_QUANTITY + 1)})


def test_an_iso_date_is_parsed_and_a_typo_is_refused() -> None:
    assert validate_iso_date("2026-03-04", "expires on") == date(2026, 3, 4)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        validate_iso_date("3/4/2026", "expires on")
    with pytest.raises(ValueError, match="valid date"):
        validate_iso_date("2026-02-30", "expires on")


def test_a_year_typo_is_caught_by_the_plausible_range() -> None:
    assert validate_plausible_date(date(2026, 1, 1), "expires on", min_date=EARLIEST, max_date=LATEST) == date(2026, 1, 1)
    with pytest.raises(ValueError, match="must be between"):
        validate_plausible_date(date(26, 1, 1), "expires on", min_date=EARLIEST, max_date=LATEST)


def test_an_email_is_normalized_and_a_malformed_one_is_refused() -> None:
    assert _Addressed(email="Squad@Example.COM").email == "Squad@example.com"
    with pytest.raises(ValidationError):
        _Addressed(email="squad-at-example.com")


def test_an_email_over_the_column_width_is_refused() -> None:
    with pytest.raises(ValidationError):
        _Addressed(email=f"{'a' * 130}@example.com")


def test_a_known_timezone_passes_and_an_invented_one_does_not() -> None:
    assert validate_timezone("America/New_York") == "America/New_York"
    with pytest.raises(ValueError, match="Invalid timezone"):
        validate_timezone("Mars/Olympus_Mons")


@pytest.mark.parametrize("accepted", ["https://example.com/logo.png", "uploads/logo.png", "", None])
def test_an_image_may_be_a_url_or_a_local_path(accepted: str | None) -> None:
    assert validate_image_url(accepted) == accepted


def test_an_image_from_an_unexpected_scheme_is_refused() -> None:
    with pytest.raises(ValueError, match="valid URL or local file path"):
        validate_image_url("javascript:alert(1)")


def test_a_string_over_its_column_width_is_refused() -> None:
    assert validate_string_length("Gauze", "name", 10) == "Gauze"
    with pytest.raises(ValueError, match="cannot exceed 10 characters"):
        validate_string_length("a" * 11, "name", 10)


def test_a_required_string_cannot_be_blank_or_missing() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_string_length("   ", "name", 10, allow_empty=False)
    with pytest.raises(ValueError, match="cannot be None"):
        validate_string_length(None, "name", 10, allow_none=False)


def test_one_flash_message_is_taken_from_a_validation_error() -> None:
    with pytest.raises(ValidationError) as caught:
        _Colored(color="nope")

    assert first_validation_error_message(caught.value, DEFAULT_MESSAGE) == "Color must be valid hex format: #rrggbb"


@pytest.mark.parametrize(("address", "expected"), [("squad@example.com", "example.com"), ("a@b@example.com", "example.com"), ("", "unknown")])
def test_only_the_domain_of_an_address_reaches_a_log(address: str, expected: str) -> None:
    assert email_domain(address) == expected


@pytest.mark.parametrize(("count", "expected"), [(1, "item"), (0, "items"), (2, "items")])
def test_a_word_is_pluralized_by_its_count(count: int, expected: str) -> None:
    assert pluralize("item", count) == expected
