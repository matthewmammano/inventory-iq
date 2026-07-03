"""Admin bulk inventory routes."""

from collections.abc import Mapping
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger

from app.auth.models import AgencyLocations
from app.auth.queries import list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.bulk_forms import BulkEditSubmission
from app.inventory.bulk_location_service import (
    LocationQuantityGrid,
    load_location_item_selection,
    load_location_item_summary,
    load_location_quantity_grid,
    required_count_storage_ids,
    save_bulk_location_count,
    save_bulk_location_restock,
)
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids


@bp.route("/<squad>/admin-panel/bulk-actions")
@bp.route("/<squad>/admin-panel/bulk-actions/<int:agency_location_id>")
def bulk_actions(squad: str, agency_location_id: int | None = None) -> Any:
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_location.html",
            squad=squad,
            locations=locations,
            endpoint="admin.bulk_actions",
            title="Bulk Action",
            admin=True,
        )

    with get_session() as s:
        summary = load_location_item_summary(s, current_user.id, agency_location_id)
    if summary is None:
        return _invalid_bulk_location_response(squad, agency_location_id)
    return render_template(
        "admin_bulk_mode.html",
        squad=squad,
        location=summary.location,
        item_count=summary.item_count,
        admin=True,
    )


@bp.route(
    "/<squad>/admin-panel/bulk-actions/<int:agency_location_id>/items",
    methods=["GET", "POST"],
)
def bulk_select_items(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        selection = load_location_item_selection(s, current_user.id, agency_location_id)
    if selection is None:
        return _invalid_bulk_location_response(squad, agency_location_id)

    if request.method == "POST":
        item_ids = _selected_item_ids(request.form.getlist("item_ids"), selection.items)
        if not item_ids:
            logger.info("Bulk item selection rejected: no items were selected", extra={"agency_location_id": agency_location_id})
            flash("Select at least one item.", "warning")
            return redirect(url_for("admin.bulk_select_items", squad=squad, agency_location_id=agency_location_id))
        return redirect(_bulk_edit_url(squad, agency_location_id, item_ids))

    return render_template(
        "admin_bulk_select_items.html",
        squad=squad,
        location=selection.location,
        items=selection.items,
        admin=True,
    )


@bp.route(
    "/<squad>/admin-panel/bulk-actions/<int:agency_location_id>/edit",
    methods=["GET", "POST"],
)
def bulk_edit(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            return _invalid_bulk_location_response(squad, agency_location_id)

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
                squad,
                grid,
                required,
                "Bulk action rejected: quantity values must be non-negative whole numbers",
                "Counts and restocks must be 0 or higher.",
                {
                    "invalid_count_cell_count": len(submission.invalid_count_cells),
                    "invalid_restock_cell_count": len(submission.invalid_restock_cells),
                },
                submission.raw_counts,
                submission.raw_restocks,
                submission.invalid_count_cells,
                submission.invalid_restock_cells,
            )
        if request.method == "POST" and submission.missing_required_count_cells:
            return _reject_bulk_edit(
                squad,
                grid,
                required,
                "Bulk action rejected: required count values are missing before restock",
                "Count required before restocking highlighted items.",
                {"missing_count_cell_count": len(submission.missing_required_count_cells)},
                submission.counts,
                submission.restocks,
                submission.missing_required_count_cells,
                set(),
            )
        if request.method == "POST":
            return _save_bulk_edit(s, squad, grid.location, submission.counts, submission.restocks, item_ids)

        return _render_bulk_edit(squad, grid, required)


def _invalid_bulk_location_response(squad: str, agency_location_id: int) -> Any:
    _log_bulk_location_missing(squad, agency_location_id)
    flash("Choose a valid location.", "error")
    return redirect(url_for("admin.bulk_actions", squad=squad))


def _reject_bulk_edit(
    squad: str,
    grid,
    required: dict[int, set[int]],
    log_message: str,
    flash_message: str,
    extra: Mapping[str, int],
    submitted_counts: Mapping[tuple[int, int], int | str],
    submitted_restocks: Mapping[tuple[int, int], int | str],
    invalid_cells: set[tuple[int, int]],
    invalid_restock_cells: set[tuple[int, int]],
) -> Any:
    logger.info(log_message, extra={"agency_location_id": grid.location.id, "item_count": len(grid.items), **extra})
    flash(flash_message, "warning")
    return _render_bulk_edit(squad, grid, required, submitted_counts, submitted_restocks, invalid_cells, invalid_restock_cells)


def _render_bulk_edit(
    squad: str,
    grid,
    required: dict[int, set[int]],
    submitted_counts: Mapping[tuple[int, int], int | str] | None = None,
    submitted_restocks: Mapping[tuple[int, int], int | str] | None = None,
    invalid_cells: set[tuple[int, int]] | None = None,
    invalid_restock_cells: set[tuple[int, int]] | None = None,
) -> Any:
    return render_template(
        "admin_bulk_actions.html",
        squad=squad,
        location=grid.location,
        rows=_bulk_rows(
            grid.items,
            grid.storages,
            grid.quantities,
            required,
            submitted_counts or {},
            submitted_restocks or {},
            invalid_cells or set(),
            invalid_restock_cells or set(),
        ),
        storages=grid.storages,
        item_ids=[item.id for item in grid.items],
        stale_count_days=current_user.count_last_days,
        admin=True,
    )


def _save_bulk_edit(
    session,
    squad: str,
    location: AgencyLocations,
    counts: dict[tuple[int, int], int],
    restocks: dict[tuple[int, int], int],
    item_ids: set[int],
) -> Any:
    if not counts and not any(quantity > 0 for quantity in restocks.values()):
        logger.info("Bulk action rejected: no count or restock entries submitted", extra={"agency_location_id": location.id})
        flash("No count or restock entries entered.", "info")
        return redirect(_bulk_edit_url(squad, location.id, item_ids))
    try:
        count_logs = save_bulk_location_count(session, current_user.id, location.id, counts) if counts else 0
        restock_logs = save_bulk_location_restock(session, current_user.id, location.id, restocks) if restocks else 0
        session.commit()
        logger.info(
            "Bulk inventory changes saved",
            extra={
                "agency_location_id": location.id,
                "item_count": len(item_ids) or None,
                "count_entry_count": count_logs,
                "restock_entry_count": restock_logs,
                "entry_count": count_logs + restock_logs,
            },
        )
        flash(f"Saved {count_logs} count and {restock_logs} restock entries for {location.name}.", "success")
        return redirect(url_for("admin.admin_panel", squad=squad))
    except Exception:
        session.rollback()
        logger.exception(
            "Bulk inventory changes could not be saved",
            extra={
                "agency_location_id": location.id,
                "item_count": len(item_ids) or None,
                "count_entry_count": len(counts),
                "restock_entry_count": sum(1 for quantity in restocks.values() if quantity > 0),
            },
        )
        flash("Bulk action could not be saved. Try again.", "error")
        return redirect(_bulk_edit_url(squad, location.id, item_ids))


def _bulk_rows(
    items,
    storages,
    counts: dict[tuple[int, int], int],
    required: dict[int, set[int]],
    submitted_counts: Mapping[tuple[int, int], int | str],
    submitted_restocks: Mapping[tuple[int, int], int | str],
    invalid_cells: set[tuple[int, int]],
    invalid_restock_cells: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        cells = []
        for storage in storages:
            key = (item.id, storage.id)
            cells.append(
                {
                    "storage": storage,
                    "count_value": submitted_counts.get(key, ""),
                    "count_original": "",
                    "restock_value": submitted_restocks.get(key, ""),
                    "count_required": storage.id in required.get(item.id, set()),
                    "invalid": key in invalid_cells,
                    "restock_invalid": key in invalid_restock_cells,
                }
            )
        rows.append({"item": item, "cells": cells})
    return rows


def _selected_item_ids(raw_ids: list[str], items) -> set[int]:
    return selected_int_ids(raw_ids, {item.id for item in items})


def _bulk_edit_url(squad: str, agency_location_id: int, item_ids: set[int]) -> str:
    if item_ids:
        return url_for(
            "admin.bulk_edit",
            squad=squad,
            agency_location_id=agency_location_id,
            item_ids=",".join(str(item_id) for item_id in sorted(item_ids)),
        )
    return url_for("admin.bulk_edit", squad=squad, agency_location_id=agency_location_id)


def _log_bulk_location_missing(squad: str, agency_location_id: int) -> None:
    logger.warning(
        "Bulk action rejected: requested location was not found",
        extra={"squad": squad, "agency_location_id": agency_location_id},
    )
