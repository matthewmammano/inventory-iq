"""Admin UPC review routes."""

from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger

from app.inventory import admin_bp as bp
from app.inventory.constants import UnknownUpcStatus
from app.inventory.item_queries import list_items
from app.inventory.models import UnknownUpcScan, validate_upc_code
from app.inventory.upc_service import (
    ignore_unknown_upc,
    list_review_unknown_upcs,
    record_unknown_upc,
    remove_unknown_upc,
    resolve_unknown_upc,
    unignore_unknown_upc,
)
from app.shared.database import get_session
from app.shared.validators import parse_optional_int

SAVE_RETRY_MESSAGE = "Changes could not be saved. Review entries and try again."
PENDING_UPC_REVIEW_ACTIONS = {
    "ignore": (ignore_unknown_upc, "Pending UPC ignored", "UPC ignored."),
    "unignore": (unignore_unknown_upc, "Pending UPC restored", "UPC moved back to pending."),
    "remove": (remove_unknown_upc, "Pending UPC review removed", "UPC review canceled."),
}


@bp.route("/<squad>/admin-panel/pending-upcs", methods=["GET", "POST"])
def pending_upcs(squad: str) -> Any:
    if request.method == "POST":
        return _save_pending_upc_review(squad)
    with get_session() as s:
        review_upcs = list_review_unknown_upcs(s, current_user.id)
        items = list_items(current_user.id, session=s)
    focus_upc = request.args.get("focus_upc", "").strip()
    return render_template(
        "admin_pending_upcs.html",
        squad=squad,
        pending_upcs=_focused_upcs(review_upcs, UnknownUpcStatus.PENDING, focus_upc),
        ignored_upcs=_focused_upcs(review_upcs, UnknownUpcStatus.IGNORE, focus_upc),
        items=items,
        focus_upc=focus_upc,
        admin=True,
        user_timezone=current_user.timezone,
    )


def _save_pending_upc_review(squad: str) -> Any:
    if request.form.get("action") == "add":
        return _add_pending_upc(squad)

    unknown_upc_id = parse_optional_int(request.form.get("unknown_upc_id"))
    action = request.form.get("action", "")
    try:
        if unknown_upc_id is None:
            raise ValueError("Pending UPC not found.")
        with get_session() as s:
            if action == "resolve":
                item_id = parse_optional_int(request.form.get("item_id"))
                if item_id is None:
                    raise ValueError("Select an item.")
                resolve_unknown_upc(s, current_user.id, unknown_upc_id, item_id)
                logger.info("Pending UPC linked to item", extra={"unknown_upc_id": unknown_upc_id, "item_id": item_id})
                flash("UPC linked to item.", "success")
            elif action in PENDING_UPC_REVIEW_ACTIONS:
                save_action, log_message, flash_message = PENDING_UPC_REVIEW_ACTIONS[action]
                save_action(s, current_user.id, unknown_upc_id)
                logger.info(log_message, extra={"unknown_upc_id": unknown_upc_id})
                flash(flash_message, "success")
            else:
                raise ValueError("Choose a valid UPC review action.")
            s.commit()
    except ValueError as exc:
        logger.info("Pending UPC review rejected", extra={"action": action, "unknown_upc_id": unknown_upc_id, "error": str(exc)})
        flash(str(exc), "error")
    return redirect(url_for("admin.pending_upcs", squad=squad))


def _add_pending_upc(squad: str) -> Any:
    upc = request.form.get("upc", "").strip()
    if validation_message := _pending_upc_error(upc):
        flash(validation_message, "warning")
        return redirect(url_for("admin.pending_upcs", squad=squad))
    try:
        with get_session() as s:
            status = record_unknown_upc(s, current_user.id, upc)
            s.commit()
        is_pending = status == UnknownUpcStatus.PENDING
        logger.info("Pending UPC added from admin review", extra={"status": status.value, "upc": upc})
        flash("Barcode ready to link." if is_pending else status.message, "success" if is_pending else "warning")
        return redirect(url_for("admin.pending_upcs", squad=squad, focus_upc=upc))
    except ValueError as exc:
        logger.warning("Pending UPC validation reached backend", extra={"error": str(exc)})
        flash(_pending_upc_service_error(str(exc)), "warning")
        return redirect(url_for("admin.pending_upcs", squad=squad))


def _pending_upc_error(upc: str) -> str:
    if not upc:
        return "Enter a UPC."
    if not upc.isdigit():
        return "UPC must contain digits only."
    if len(upc) != 12:
        return "UPC must be 12 digits."
    try:
        validate_upc_code(upc)
    except ValueError:
        return "Invalid UPC code."
    return ""


def _pending_upc_service_error(error: str) -> str:
    if error == "Private UPCs must already be linked as primary item UPCs.":
        return "Private item UPCs are already linked."
    return SAVE_RETRY_MESSAGE


def _focused_upcs(scans: list[UnknownUpcScan], status: UnknownUpcStatus, focus_upc: str) -> list[UnknownUpcScan]:
    rows = [scan for scan in scans if scan.status == status]
    return sorted(rows, key=lambda scan: scan.upc != focus_upc)
