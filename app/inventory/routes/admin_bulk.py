"""Admin bulk inventory routes."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger

from app.auth.queries import list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.bulk_edit_service import BulkEditData, BulkEditEmptyError, save_bulk_edit
from app.inventory.bulk_forms import BulkEditSubmission
from app.inventory.bulk_location_service import (
    LocationQuantityGrid,
    load_location_item_selection,
    load_location_item_summary,
    load_location_quantity_grid,
    required_count_storage_ids,
    suggested_restock_item_ids,
)
from app.inventory.expiration_ui_service import (
    build_expiration_entry_groups,
    bulk_expiration_specs,
    group_expiration_entries_by_item,
    hidden_form_fields,
    parse_expiration_allocations,
)
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids


@dataclass(frozen=True, slots=True)
class BulkEditCell:
    storage: Any
    count_value: int | str
    count_original: str
    restock_value: int | str
    count_required: bool
    invalid: bool
    restock_invalid: bool


@dataclass(frozen=True, slots=True)
class BulkEditRow:
    item: Any
    cells: list[BulkEditCell]
    expiration_tracking_enabled: bool
    stale: bool
    suggested_restock: bool


@dataclass(frozen=True, slots=True)
class BulkEditFormState:
    """Submitted cell values and validation-highlighted cells for one bulk-edit render."""

    counts: Mapping[tuple[int, int], int | str]
    restocks: Mapping[tuple[int, int], int | str]
    invalid_cells: set[tuple[int, int]]
    invalid_restock_cells: set[tuple[int, int]]

    @classmethod
    def empty(cls) -> "BulkEditFormState":
        return cls({}, {}, set(), set())


@dataclass(frozen=True, slots=True)
class BulkEditRejection:
    """Why a bulk-edit submission was rejected, and what to redisplay for it."""

    log_message: str
    flash_message: str
    extra: Mapping[str, int]
    form_state: BulkEditFormState


@bp.route("/<int:agency_id>/admin-panel/bulk-actions")
@bp.route("/<int:agency_id>/admin-panel/bulk-actions/<int:agency_location_id>")
def bulk_actions(agency_id: int, agency_location_id: int | None = None) -> Any:
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_location.html",
            agency_id=agency_id,
            locations=locations,
            endpoint="admin.bulk_actions",
            title="Bulk Action",
            admin=True,
        )

    with get_session() as s:
        summary = load_location_item_summary(s, current_user.id, agency_location_id)
    if summary is None:
        return _invalid_bulk_location_response(agency_id, agency_location_id)
    return render_template(
        "admin_bulk_mode.html",
        agency_id=agency_id,
        location=summary.location,
        item_count=summary.item_count,
        admin=True,
    )


@bp.route(
    "/<int:agency_id>/admin-panel/bulk-actions/<int:agency_location_id>/items",
    methods=["GET", "POST"],
)
def bulk_select_items(agency_id: int, agency_location_id: int) -> Any:
    with get_session() as s:
        selection = load_location_item_selection(s, current_user.id, agency_location_id)
    if selection is None:
        return _invalid_bulk_location_response(agency_id, agency_location_id)

    if request.method == "POST":
        item_ids = _selected_item_ids(request.form.getlist("item_ids"), selection.items)
        if not item_ids:
            logger.info("Bulk item selection rejected: no items were selected", extra={"agency_location_id": agency_location_id})
            flash("Select at least one item.", "warning")
            return redirect(url_for("admin.bulk_select_items", agency_id=agency_id, agency_location_id=agency_location_id))
        return redirect(_bulk_edit_url(agency_id, agency_location_id, item_ids))

    return render_template(
        "admin_bulk_select_items.html",
        agency_id=agency_id,
        location=selection.location,
        items=selection.items,
        admin=True,
    )


@bp.route(
    "/<int:agency_id>/admin-panel/bulk-actions/<int:agency_location_id>/edit",
    methods=["GET", "POST"],
)
def bulk_edit(agency_id: int, agency_location_id: int) -> Any:
    with get_session() as s:
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            return _invalid_bulk_location_response(agency_id, agency_location_id)

        submission = BulkEditSubmission.from_form(request.values, request.form, grid.items, {})
        item_ids = submission.item_ids
        if item_ids:
            grid = LocationQuantityGrid(
                grid.location,
                [item for item in grid.items if item.id in item_ids],
                grid.storages,
                grid.quantities,
            )

        required = required_count_storage_ids(s, current_user.id, agency_location_id, grid.items)
        submission = BulkEditSubmission.from_form(request.values, request.form, grid.items, required)
        if request.method == "POST" and submission.has_invalid_quantities:
            return _reject_bulk_edit(
                s,
                agency_id,
                grid,
                required,
                BulkEditRejection(
                    "Bulk action rejected: quantity values must be non-negative whole numbers",
                    "Counts and restocks must be 0 or higher.",
                    {
                        "invalid_count_cell_count": len(submission.invalid_count_cells),
                        "invalid_restock_cell_count": len(submission.invalid_restock_cells),
                    },
                    BulkEditFormState(
                        submission.raw_counts, submission.raw_restocks, submission.invalid_count_cells, submission.invalid_restock_cells
                    ),
                ),
            )
        if request.method == "POST" and submission.missing_required_count_cells:
            return _reject_bulk_edit(
                s,
                agency_id,
                grid,
                required,
                BulkEditRejection(
                    "Bulk action rejected: required count values are missing before restock",
                    "Count required before restocking highlighted items.",
                    {"missing_count_cell_count": len(submission.missing_required_count_cells)},
                    BulkEditFormState(submission.counts, submission.restocks, submission.missing_required_count_cells, set()),
                ),
            )
        if request.method == "POST":
            return _save_bulk_edit(s, agency_id, grid.location, submission, item_ids)

        return _render_bulk_edit(s, agency_id, grid, required)


def _invalid_bulk_location_response(agency_id: int, agency_location_id: int) -> Any:
    _log_bulk_location_missing(agency_id, agency_location_id)
    flash("Choose a valid location.", "error")
    return redirect(url_for("admin.bulk_actions", agency_id=agency_id))


def _reject_bulk_edit(session, agency_id: int, grid, required: dict[int, set[int]], rejection: BulkEditRejection) -> Any:
    logger.info(rejection.log_message, extra={"agency_location_id": grid.location.id, "item_count": len(grid.items), **rejection.extra})
    flash(rejection.flash_message, "warning")
    return _render_bulk_edit(session, agency_id, grid, required, rejection.form_state)


def _render_bulk_edit(
    session,
    agency_id: int,
    grid,
    required: dict[int, set[int]],
    form_state: BulkEditFormState | None = None,
) -> Any:
    state = form_state or BulkEditFormState.empty()
    suggested_restock = suggested_restock_item_ids(session, current_user.id, grid.location.id, grid.items)
    return render_template(
        "admin_bulk_actions.html",
        agency_id=agency_id,
        location=grid.location,
        rows=_bulk_rows(grid.items, grid.storages, required, suggested_restock, state),
        storages=grid.storages,
        item_ids=[item.id for item in grid.items],
        stale_count_days=current_user.count_last_days,
        admin=True,
    )


def _save_bulk_edit(session, agency_id: int, location, submission: BulkEditSubmission, item_ids: set[int]) -> Any:
    try:
        groups = build_expiration_entry_groups(
            session,
            current_user.id,
            bulk_expiration_specs(counts=submission.counts, restocks=submission.restocks),
        )
        if groups and request.form.get("expiration_confirmed") != "1":
            return _render_bulk_expiration_entry(agency_id, location, groups, item_ids)
        expiration_allocations_by_key = parse_expiration_allocations(request.form, groups) if groups else {}
    except ValueError as exc:
        logger.info("Bulk expiration entry rejected", extra={"agency_location_id": location.id, "error": str(exc)})
        flash(str(exc), "warning")
        return redirect(_bulk_edit_url(agency_id, location.id, item_ids))

    try:
        result = save_bulk_edit(
            session,
            agency_id=current_user.id,
            agency_location_id=location.id,
            data=BulkEditData(submission.counts, submission.restocks, expiration_allocations_by_key),
        )
    except BulkEditEmptyError:
        logger.info("Bulk action rejected: no count or restock entries submitted", extra={"agency_location_id": location.id})
        flash("No count or restock entries entered.", "info")
        return redirect(_bulk_edit_url(agency_id, location.id, item_ids))
    except Exception:
        session.rollback()
        logger.exception(
            "Bulk inventory changes could not be saved",
            extra={
                "agency_location_id": location.id,
                "item_count": len(item_ids) or None,
                "count_entry_count": len(submission.counts),
                "restock_entry_count": sum(1 for quantity in submission.restocks.values() if quantity > 0),
            },
        )
        flash("Bulk action could not be saved. Try again.", "error")
        return redirect(_bulk_edit_url(agency_id, location.id, item_ids))

    logger.info(
        "Bulk inventory changes saved",
        extra={
            "agency_location_id": location.id,
            "item_count": len(item_ids) or None,
            "count_entry_count": result.count_entry_count,
            "restock_entry_count": result.restock_entry_count,
            "entry_count": result.total_entry_count,
        },
    )
    if result.total_entry_count == 0:
        flash("No changes entered.", "info")
    else:
        flash(f"Saved {result.count_entry_count} count and {result.restock_entry_count} restock entries for {location.name}.", "success")
    return redirect(url_for("admin.admin_panel", agency_id=agency_id))


def _render_bulk_expiration_entry(agency_id: int, location, groups, item_ids: set[int]) -> Any:
    return render_template(
        "expiration_entry.html",
        agency_id=agency_id,
        groups=groups,
        item_groups=group_expiration_entries_by_item(groups),
        hidden_fields=hidden_form_fields(request.form),
        form_action=None,
        cancel_url=_bulk_edit_url(agency_id, location.id, item_ids),
        back_label="Back to Bulk Action",
        cancel_label="Cancel Bulk Update",
        submit_label="Save Bulk Updates",
        page_title="Expiration Dates",
        page_subtitle=f"Location: {location.name}",
        admin=True,
    )


def _bulk_rows(
    items,
    storages,
    required: dict[int, set[int]],
    suggested_restock_ids: set[int],
    state: BulkEditFormState,
) -> list[BulkEditRow]:
    rows = []
    for item in items:
        cells = []
        stale = False
        for storage in storages:
            key = (item.id, storage.id)
            count_required = storage.id in required.get(item.id, set())
            stale = stale or count_required
            cells.append(
                BulkEditCell(
                    storage=storage,
                    count_value=state.counts.get(key, ""),
                    count_original="",
                    restock_value=state.restocks.get(key, ""),
                    count_required=count_required,
                    invalid=key in state.invalid_cells,
                    restock_invalid=key in state.invalid_restock_cells,
                )
            )
        rows.append(BulkEditRow(item, cells, bool(item.expiration_tracking_enabled), stale, item.id in suggested_restock_ids))
    return rows


def _selected_item_ids(raw_ids: list[str], items) -> set[int]:
    return selected_int_ids(raw_ids, {item.id for item in items})


def _bulk_edit_url(agency_id: int, agency_location_id: int, item_ids: set[int]) -> str:
    if item_ids:
        return url_for(
            "admin.bulk_edit",
            agency_id=agency_id,
            agency_location_id=agency_location_id,
            item_ids=",".join(str(item_id) for item_id in sorted(item_ids)),
        )
    return url_for("admin.bulk_edit", agency_id=agency_id, agency_location_id=agency_location_id)


def _log_bulk_location_missing(agency_id: int, agency_location_id: int) -> None:
    logger.warning(
        "Bulk action rejected: requested location was not found",
        extra={"agency_id": agency_id, "agency_location_id": agency_location_id},
    )
