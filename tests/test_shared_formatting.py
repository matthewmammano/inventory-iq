"""The display helpers that turn stored values into what a screen or a JSON payload shows."""

from datetime import UTC, datetime
from typing import Final

import pytest
from flask import Flask

from app.shared.html_formatting import bold_item_name
from app.shared.image_paths import NOT_FOUND_IMAGE, static_image_url
from app.shared.security import generate_numeric_pin
from app.shared.timezone_utils import (
    DEFAULT_TIMEZONE,
    convert_utc_to_local,
    format_local_date,
    format_local_datetime,
    local_now,
    resolve_timezone,
    utc_isoformat,
)
from app.shared.utils import parse_bool

NEW_YORK: Final[str] = "America/New_York"
WINTER_NOON_UTC: Final[datetime] = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
SUMMER_NOON_UTC: Final[datetime] = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
NAIVE_WINTER_NOON: Final[datetime] = datetime(2026, 1, 15, 12, 0)


def test_an_agency_with_no_timezone_set_is_treated_as_utc() -> None:
    assert resolve_timezone(None) == DEFAULT_TIMEZONE
    assert resolve_timezone("") == DEFAULT_TIMEZONE
    assert resolve_timezone(NEW_YORK) == NEW_YORK


def test_a_stored_naive_datetime_is_read_as_utc_not_as_local() -> None:
    converted = convert_utc_to_local(NAIVE_WINTER_NOON, NEW_YORK)

    assert converted is not None
    assert converted.hour == 7


def test_daylight_saving_is_applied_from_the_zone_not_a_fixed_offset() -> None:
    winter = convert_utc_to_local(WINTER_NOON_UTC, NEW_YORK)
    summer = convert_utc_to_local(SUMMER_NOON_UTC, NEW_YORK)

    assert winter is not None
    assert summer is not None
    assert (winter.hour, summer.hour) == (7, 8)


def test_an_unknown_timezone_shows_the_utc_value_rather_than_failing() -> None:
    assert convert_utc_to_local(WINTER_NOON_UTC, "Mars/Olympus_Mons") == WINTER_NOON_UTC


def test_nothing_converts_to_nothing() -> None:
    assert convert_utc_to_local(None, NEW_YORK) is None


def test_now_in_the_agency_timezone_keeps_the_same_instant() -> None:
    assert local_now(NEW_YORK, WINTER_NOON_UTC).utcoffset() is not None
    assert local_now(NEW_YORK, NAIVE_WINTER_NOON).hour == 7
    assert local_now(None, NAIVE_WINTER_NOON).hour == 12


def test_a_datetime_sent_as_json_always_carries_its_offset() -> None:
    assert utc_isoformat(NAIVE_WINTER_NOON) == "2026-01-15T12:00:00+00:00"
    assert utc_isoformat(WINTER_NOON_UTC) == "2026-01-15T12:00:00+00:00"
    assert utc_isoformat(None) == ""


def test_a_server_rendered_stamp_is_local_and_minute_precise() -> None:
    assert format_local_datetime(NAIVE_WINTER_NOON, NEW_YORK) == "2026-01-15 07:00"
    assert format_local_date(NAIVE_WINTER_NOON, NEW_YORK) == "2026-01-15"


def test_a_local_date_can_fall_on_the_day_before_the_utc_one() -> None:
    just_after_utc_midnight = datetime(2026, 1, 15, 2, 0, tzinfo=UTC)

    assert format_local_date(just_after_utc_midnight, NEW_YORK) == "2026-01-14"


def test_a_missing_stamp_renders_the_caller_s_fallback() -> None:
    assert format_local_datetime(None, NEW_YORK) == ""
    assert format_local_date(None, NEW_YORK, fallback="never") == "never"


def test_an_item_name_is_bolded_with_its_html_escaped() -> None:
    assert str(bold_item_name('Gauze <4" x 4">')) == '<strong class="item-name">Gauze &lt;4&#34; x 4&#34;&gt;</strong>'


def test_a_missing_item_name_still_renders_an_empty_bold_tag() -> None:
    assert str(bold_item_name(None)) == '<strong class="item-name"></strong>'


@pytest.mark.parametrize("truthy", [True, "true", "True", "1", "yes", "on"])
def test_a_checkbox_value_reads_as_on(truthy: bool | str) -> None:
    assert parse_bool(truthy) is True


@pytest.mark.parametrize("falsy", [False, "false", "0", "no", "off", "", "maybe"])
def test_anything_that_is_not_a_known_yes_reads_as_off(falsy: bool | str) -> None:
    assert parse_bool(falsy) is False


def test_a_missing_value_takes_the_default_the_caller_named() -> None:
    assert parse_bool(None) is False
    assert parse_bool(None, default=True) is True


@pytest.mark.parametrize("digits", [4, 6])
def test_a_generated_pin_is_exactly_as_many_digits_as_asked(digits: int) -> None:
    drawn = [generate_numeric_pin(digits) for _ in range(200)]

    assert all(len(pin) == digits and pin.isdigit() for pin in drawn)
    assert len(set(drawn)) > 1


def test_an_image_with_no_stored_path_falls_back_to_the_placeholder(app: Flask) -> None:
    with app.test_request_context():
        assert static_image_url(None).endswith(NOT_FOUND_IMAGE)
        assert static_image_url("").endswith(NOT_FOUND_IMAGE)


def test_a_remote_image_url_is_handed_back_untouched(app: Flask) -> None:
    with app.test_request_context():
        assert static_image_url("https://example.com/logo.png") == "https://example.com/logo.png"


def test_a_stored_path_with_no_file_behind_it_falls_back(app: Flask) -> None:
    with app.test_request_context():
        assert static_image_url("images/does-not-exist.png").endswith(NOT_FOUND_IMAGE)


def test_a_stored_path_is_found_whichever_way_it_was_written(app: Flask) -> None:
    with app.test_request_context():
        expected = static_image_url(NOT_FOUND_IMAGE)

        assert static_image_url(f"/{NOT_FOUND_IMAGE}") == expected
        assert static_image_url(f"static/{NOT_FOUND_IMAGE}") == expected
        assert static_image_url(NOT_FOUND_IMAGE.replace("/", "\\")) == expected
