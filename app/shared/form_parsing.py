"""Small helpers for parsing repeated form/query shapes."""

from collections.abc import Iterable

from app.shared.validators import parse_non_negative_int


def selected_int_ids(raw_values: Iterable[str], allowed_ids: set[int] | None = None) -> set[int]:
    values = (part.strip() for raw_value in raw_values for part in str(raw_value).split(","))
    parsed = {parsed_id for value in values if (parsed_id := parse_non_negative_int(value)) is not None}
    return parsed if allowed_ids is None else parsed & allowed_ids
