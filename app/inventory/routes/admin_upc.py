"""Admin UPC review routes."""

from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError

from app.inventory import admin_bp as bp
from app.inventory.constants import UnknownUpcStatus
from app.inventory.item_queries import list_items
from app.inventory.models import UnknownUpcScan, validate_upc_code
from app.inventory.upc_review_schema import PendingUpcReviewAction, PendingUpcReviewRequest
from app.inventory.upc_service import (
    ignore_unknown_upc,
    list_review_unknown_upcs,
    record_unknown_upc,
    remove_unknown_upc,
    resolve_unknown_upc,
    unignore_unknown_upc,
)
from app.shared.constants import SAVE_RETRY_MESSAGE
from app.shared.database import get_session

PENDING_UPC_REVIEW_ACTIONS = {
    PendingUpcReviewAction.IGNORE: (ignore_unknown_upc, "Pending UPC ignored", "UPC ignored."),
    PendingUpcReviewAction.UNIGNORE: (unignore_unknown_upc, "Pending UPC restored", "UPC moved back to pending."),
    PendingUpcReviewAction.REMOVE: (remove_unknown_upc, "Pending UPC review removed", "UPC review canceled."),
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
        pending_upcs=_upcs_by_status(review_upcs, UnknownUpcStatus.PENDING),
        ignored_upcs=_upcs_by_status(review_upcs, UnknownUpcStatus.IGNORE),
        items=items,
        focus_upc=focus_upc,
        admin=True,
        user_timezone=current_user.timezone,
    )


def _save_pending_upc_review(squad: str) -> Any:
    try:
        review_request = PendingUpcReviewRequest.model_validate(request.form.to_dict())
    except ValidationError as exc:
        flash(_request_validation_message(exc), "error")
        return redirect(_pending_upc_redirect(squad))

    if review_request.action == PendingUpcReviewAction.ADD:
        return _add_pending_upc(squad)

    unknown_upc_id = review_request.unknown_upc_id
    if unknown_upc_id is None:
        flash("Pending UPC not found.", "error")
        return redirect(_pending_upc_redirect(squad))

    try:
        with get_session() as s:
            if review_request.action == PendingUpcReviewAction.RESOLVE:
                item_id = review_request.item_id
                if item_id is None:
                    raise ValueError("Select an item.")
                resolve_unknown_upc(s, current_user.id, unknown_upc_id, item_id)
                logger.info("Pending UPC linked to item", extra={"unknown_upc_id": unknown_upc_id, "item_id": item_id})
                flash("UPC linked to item.", "success")
            elif review_request.action in PENDING_UPC_REVIEW_ACTIONS:
                save_action, log_message, flash_message = PENDING_UPC_REVIEW_ACTIONS[review_request.action]
                save_action(s, current_user.id, unknown_upc_id)
                logger.info(log_message, extra={"unknown_upc_id": unknown_upc_id})
                flash(flash_message, "success")
            else:
                raise ValueError("Choose a valid UPC review action.")
            s.commit()
    except ValueError as exc:
        logger.info(
            "Pending UPC review rejected",
            extra={"action": review_request.action.value, "unknown_upc_id": unknown_upc_id, "error": str(exc)},
        )
        flash(str(exc), "error")
    return redirect(_pending_upc_redirect(squad))


def _add_pending_upc(squad: str) -> Any:
    upc = request.form.get("upc", "").strip()
    try:
        upc = validate_upc_code(upc)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(_pending_upc_redirect(squad))
    try:
        with get_session() as s:
            status = record_unknown_upc(s, current_user.id, upc)
            s.commit()
        is_pending = status == UnknownUpcStatus.PENDING
        logger.info("Pending UPC added from admin review", extra={"status": status.value, "upc": upc})
        flash("Barcode ready to link." if is_pending else status.message, "success" if is_pending else "warning")
        return redirect(_pending_upc_redirect(squad, focus_upc=upc))
    except ValueError as exc:
        logger.warning("Pending UPC validation reached backend", extra={"error": str(exc)})
        flash(_pending_upc_service_error(str(exc)), "warning")
        return redirect(_pending_upc_redirect(squad))


def _pending_upc_service_error(error: str) -> str:
    if error == "Private UPCs must already be linked as primary item UPCs.":
        return "Private item UPCs are already linked."
    return SAVE_RETRY_MESSAGE


def _request_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Choose a valid UPC review action."
    context = errors[0].get("ctx") or {}
    if "error" in context:
        return str(context["error"])
    return str(errors[0]["msg"])


def _upcs_by_status(scans: list[UnknownUpcScan], status: UnknownUpcStatus) -> list[UnknownUpcScan]:
    return [scan for scan in scans if scan.status == status]


def _pending_upc_redirect(squad: str, *, focus_upc: str | None = None):
    if focus_upc:
        return url_for("admin.pending_upcs", squad=squad, focus_upc=focus_upc)
    return url_for("admin.pending_upcs", squad=squad)
