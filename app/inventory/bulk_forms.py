"""Bulk inventory form parsing."""

from dataclasses import dataclass
from typing import Any

from app.shared.form_parsing import selected_int_ids


@dataclass(frozen=True, slots=True)
class BulkEditSubmission:
    item_ids: set[int]
    raw_counts: dict[tuple[int, int], str]
    raw_restocks: dict[tuple[int, int], str]
    invalid_count_cells: set[tuple[int, int]]
    invalid_restock_cells: set[tuple[int, int]]
    counts: dict[tuple[int, int], int]
    restocks: dict[tuple[int, int], int]
    missing_required_count_cells: set[tuple[int, int]]

    @classmethod
    def from_form(
        cls,
        values: Any,
        form: Any,
        items: list[Any],
        required: dict[int, set[int]],
    ) -> "BulkEditSubmission":
        item_ids = selected_int_ids(values.getlist("item_ids"), {item.id for item in items})
        raw_counts = _quantity_values(form, "count_")
        raw_restocks = _quantity_values(form, "restock_")
        counts = _non_negative_quantities(raw_counts)
        restocks = _non_negative_quantities(raw_restocks)
        return cls(
            item_ids=item_ids,
            raw_counts=raw_counts,
            raw_restocks=raw_restocks,
            invalid_count_cells=_invalid_quantity_cells(raw_counts),
            invalid_restock_cells=_invalid_quantity_cells(raw_restocks),
            counts=counts,
            restocks=restocks,
            missing_required_count_cells=_missing_required_count_cells(required, counts, restocks),
        )

    @property
    def has_invalid_quantities(self) -> bool:
        return bool(self.invalid_count_cells or self.invalid_restock_cells)


def _quantity_values(form: Any, prefix: str) -> dict[tuple[int, int], str]:
    values = {}
    for key, value in form.items():
        if not key.startswith(prefix) or value == "":
            continue
        try:
            item_id, storage_id = key.removeprefix(prefix).split("_", maxsplit=1)
            values[(int(item_id), int(storage_id))] = value
        except ValueError:
            continue
    return values


def _invalid_quantity_cells(values: dict[tuple[int, int], str]) -> set[tuple[int, int]]:
    return {key for key, value in values.items() if not value.isdigit()}


def _non_negative_quantities(values: dict[tuple[int, int], str]) -> dict[tuple[int, int], int]:
    return {key: int(value) for key, value in values.items() if value.isdigit()}


def _missing_required_count_cells(
    required: dict[int, set[int]],
    counts: dict[tuple[int, int], int],
    restocks: dict[tuple[int, int], int],
) -> set[tuple[int, int]]:
    restocked_item_ids = {item_id for (item_id, _), quantity in restocks.items() if quantity > 0}
    return {
        (item_id, storage_id) for item_id in restocked_item_ids for storage_id in required.get(item_id, set()) if (item_id, storage_id) not in counts
    }
