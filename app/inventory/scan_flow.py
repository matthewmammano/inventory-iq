"""Inventory scan-flow handlers."""

from dataclasses import dataclass

from flask import flash, redirect, render_template, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.shared.database import get_session
from app.shared.validators import parse_optional_int

from .constants import UNKNOWN_UPC_INVALID_MESSAGE, OperationType
from .errors import InventoryError
from .item_queries import get_agency_item, get_item_by_upc
from .models import Items
from .mutation_service import inventory_operation
from .quantity_service import has_item_count
from .scan_support import (
    ScanSurface,
    can_skip_storage_selection,
    format_scan_location_label,
    format_scan_route_label,
    get_scan_permissions,
    load_scan_storage_choices,
    operation_from_storage_ids,
    redirect_to_scan_item,
    resolve_scan_location,
    scan_success_message,
    single_scan_from_id,
    single_scan_to_id,
    storage_selection_subtitle,
    validate_scan_route,
)
from .schema import ScanItemRequest, ScanStoragesRequest
from .upc_service import record_unknown_upc


@dataclass(frozen=True)
class ScanSubmitContext:
    request_data: ScanItemRequest
    item: Items
    operation_type: OperationType
    from_storage_id: int | None
    to_storage_id: int | None
    from_location: AgencyStorages | int | None
    to_location: AgencyStorages | int | None


def handle_scan_start(
    squad: str,
    item_id: int | None,
    *,
    upc: str | None = None,
    is_admin: bool = False,
):
    """Redirect to quantity entry or storage selection for one item."""
    surface = ScanSurface.from_admin_flag(is_admin)

    with get_session() as db:
        item = _get_scan_item(db, item_id, upc, is_admin=is_admin)
        if not item:
            message = "Item not found for this squad."
            if upc:
                try:
                    message = record_unknown_upc(db, current_user.id, upc).message
                    db.commit()
                except ValueError as exc:
                    logger.info(
                        "Unknown UPC scan ignored because the code was invalid",
                        extra={"error": str(exc)},
                    )
                    message = UNKNOWN_UPC_INVALID_MESSAGE
            logger.info(
                "Scan start rejected: item was not found",
                extra={"item_id": item_id, "upc": upc},
            )
            flash(message, "warning")
            return redirect(surface.fallback_url(squad))
        storage_choices = load_scan_storage_choices(current_user.id, is_admin, db)

    permissions = get_scan_permissions(squad, is_admin=is_admin)
    from_storages = storage_choices.from_storages
    to_storages = storage_choices.to_storages

    if not from_storages:
        logger.error(
            "Scan start failed: no valid source storages are available",
            extra={"item_id": item.id, "item_name": item.name},
        )
        flash("No valid storages found. Please check this device location.", "error")
        return redirect(surface.fallback_url(squad))
    if can_skip_storage_selection(from_storages, to_storages, permissions):
        return redirect_to_scan_item(surface, squad, item.id, from_storages, to_storages, permissions)
    return redirect(
        url_for(
            surface.endpoint("scan_storages"),
            squad=squad,
            item_id=item.id,
            user_count_allow=permissions.count,
            user_restock_allow=permissions.restock,
        )
    )


def handle_scan_storages_get(
    squad: str,
    item_id: int | None,
    is_admin: bool = False,
):
    surface = ScanSurface.from_admin_flag(is_admin)
    permissions = get_scan_permissions(squad, is_admin=is_admin)

    with get_session() as db:
        item = _get_scan_item(db, item_id, None, is_admin=is_admin)
        if not item:
            logger.info(
                "Storage selection rejected: item was not found",
                extra={
                    "item_id": item_id,
                },
            )
            flash("Item not found for this squad.", "warning")
            return redirect(surface.fallback_url(squad))

        storage_choices = load_scan_storage_choices(current_user.id, is_admin, db)
        from_storages = storage_choices.from_storages
        to_storages = storage_choices.to_storages
        default_location_id = storage_choices.default_location_id

    if can_skip_storage_selection(from_storages, to_storages, permissions):
        return redirect_to_scan_item(surface, squad, item.id, from_storages, to_storages, permissions)

    auto_from_id = single_scan_from_id(from_storages, permissions)
    return render_template(
        "scan_storages.html",
        squad=squad,
        item=item,
        from_locations=from_storages,
        to_locations=to_storages,
        show_storage_only=default_location_id is not None,
        user_count_allow=permissions.count,
        user_restock_allow=permissions.restock,
        auto_from_id=auto_from_id,
        auto_to_id=single_scan_to_id(to_storages, auto_from_id),
        logo_img=current_user.image,
        page_subtitle=storage_selection_subtitle(item.name),
        admin=is_admin,
    )


def handle_scan_storages_post(squad: str, form_data: dict, is_admin: bool = False):
    surface = ScanSurface.from_admin_flag(is_admin)
    permissions = get_scan_permissions(squad, is_admin=is_admin)

    try:
        request_data = ScanStoragesRequest(**form_data)
    except ValidationError as exc:
        logger.info(
            "Storage selection rejected: submitted form data was invalid",
            extra={
                "error": str(exc),
            },
        )
        flash("Invalid form data. Please try again.", "error")
        return redirect(surface.fallback_url(squad))

    with get_session() as db:
        route_error = validate_scan_route(
            current_user.id,
            request_data.from_location_id,
            request_data.to_location_id,
            permissions,
            is_admin=is_admin,
            session=db,
        )

    if request_data.same_location_error == "1" or route_error:
        logger.info(
            "Storage selection rejected: source and destination combination is not allowed",
            extra={
                "item_id": request_data.item_id,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
                "error": route_error,
            },
        )
        flash(route_error or "Invalid storage combination.", "error")
        return redirect(url_for(surface.endpoint("scan_storages"), squad=squad, item_id=request_data.item_id))

    scan_item_args = {
        "squad": squad,
        "item_id": request_data.item_id,
        "from_location_id": request_data.from_location_id,
        "to_location_id": request_data.to_location_id,
    }
    if request_data.show_scan_route:
        scan_item_args["show_scan_route"] = "1"

    return redirect(
        url_for(
            surface.endpoint("scan_item"),
            **scan_item_args,
        )
    )


def handle_scan_item_get(
    squad: str,
    item_id: int | None,
    from_location_id,
    to_location_id,
    is_admin: bool = False,
    show_scan_route: bool = False,
):
    surface = ScanSurface.from_admin_flag(is_admin)
    permissions = get_scan_permissions(squad, is_admin=is_admin)
    from_storage_id = parse_optional_int(from_location_id)
    to_storage_id = parse_optional_int(to_location_id)

    with get_session() as db:
        route_error = validate_scan_route(
            current_user.id,
            from_storage_id,
            to_storage_id,
            permissions,
            is_admin=is_admin,
            session=db,
        )
        item = _get_scan_item(db, item_id, None, is_admin=is_admin)
        from_location = resolve_scan_location(from_storage_id, current_user.id, session=db)
        to_location = resolve_scan_location(to_storage_id, current_user.id, takeout_allowed=True, session=db)
    if route_error:
        logger.info(
            "Scan quantity page rejected: selected route is not allowed",
            extra={
                "item_id": item_id,
                "from_storage_id": from_storage_id,
                "to_storage_id": to_storage_id,
                "error": route_error,
            },
        )
        flash(route_error, "error")
        return redirect(surface.fallback_url(squad))
    if not item:
        if is_admin:
            logger.info(
                "Admin scan quantity page redirected because the item was not found",
                extra={
                    "item_id": item_id,
                    "from_storage_id": from_location_id,
                    "to_storage_id": to_location_id,
                },
            )
            return redirect(
                surface.admin_scan_items_url(
                    squad,
                    from_location_id=from_location_id,
                    to_location_id=to_location_id,
                    scan_error="not_found",
                )
            )
        logger.info(
            "Scan quantity page rejected: item was not found",
            extra={
                "item_id": item_id,
                "from_storage_id": from_location_id,
                "to_storage_id": to_location_id,
            },
        )
        flash("Invalid item or storage for this squad.", "warning")
        return redirect(surface.fallback_url(squad))

    if not from_location:
        logger.info(
            "Scan quantity page rejected: selected route is invalid for this item",
            extra={
                "item_id": item_id,
                "from_storage_id": from_location_id,
                "to_storage_id": to_location_id,
            },
        )
        flash("Invalid item or storage for this squad.", "warning")
        return redirect(surface.fallback_url(squad))

    operation_type, _, _ = operation_from_storage_ids(from_storage_id, to_storage_id)
    return render_template(
        "scan_item.html",
        squad=squad,
        item=item,
        from_location=from_location,
        to_location=to_location,
        user_count_allow=permissions.count,
        user_restock_allow=permissions.restock,
        logo_img=current_user.image,
        admin=is_admin,
        page_subtitle=format_scan_route_label(from_location, to_location, is_admin=is_admin),
        minimum_scan_quantity=operation_type.minimum_scan_quantity,
        show_scan_route=show_scan_route and not is_admin,
        selected_from_location_label=format_scan_location_label(from_location, is_admin=is_admin),
        selected_to_location_label=format_scan_location_label(to_location, is_admin=is_admin, takeout_allowed=True),
        cancel_url=surface.scan_item_cancel_url(squad, from_location_id, to_location_id),
    )


def handle_scan_item_post(squad: str, form_data: dict, is_admin: bool = False):
    surface = ScanSurface.from_admin_flag(is_admin)
    permissions = get_scan_permissions(squad, is_admin=is_admin)

    request_data = _parse_scan_item_request(form_data, squad, is_admin)
    if request_data is None:
        return redirect(surface.scan_item_error_url(squad))

    try:
        with get_session() as db:
            prepared = _prepare_scan_submit(
                db,
                squad,
                surface,
                permissions,
                request_data,
                is_admin,
            )
            if not isinstance(prepared, ScanSubmitContext):
                return prepared

            action = inventory_operation(
                agency_id=current_user.id,
                item_id=prepared.item.id,
                quantity=request_data.counter_value,
                operation_type=prepared.operation_type,
                from_location=prepared.from_storage_id,
                to_location=prepared.to_storage_id,
                admin_action=is_admin,
                session=db,
            )
            initial_count_required = not prepared.operation_type.is_count and not has_item_count(db, current_user.id, prepared.item.id)
            db.commit()
    except (InventoryError, ValueError) as exc:
        logger.info(
            "Inventory update rejected by validation rules",
            extra={
                "item_id": request_data.item_id,
                "quantity": request_data.counter_value,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
                "error": str(exc),
            },
        )
        flash(str(exc), "warning")
        return redirect(surface.scan_item_error_url(squad))
    except Exception:
        logger.exception(
            "Inventory update crashed unexpectedly",
            extra={
                "item_id": request_data.item_id,
                "quantity": request_data.counter_value,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
            },
        )
        flash("Inventory could not be saved. Try again.", "error")
        return redirect(surface.scan_item_error_url(squad))

    message = scan_success_message(
        prepared.operation_type,
        prepared.item.name,
        request_data.counter_value,
        prepared.from_storage_id,
        prepared.to_storage_id,
        is_admin=is_admin,
        from_storage=prepared.from_location if isinstance(prepared.from_location, AgencyStorages) else None,
        to_storage=prepared.to_location if isinstance(prepared.to_location, AgencyStorages) else None,
    )
    logger.info(
        "Inventory scan completed",
        extra={
            "action_log_id": action.id,
            "item_id": prepared.item.id,
            "item_name": prepared.item.name,
            "operation_type": prepared.operation_type.value,
            "quantity": request_data.counter_value,
            "from_storage_id": prepared.from_storage_id,
            "to_storage_id": prepared.to_storage_id,
        },
    )
    flash(message, "success")
    if initial_count_required:
        logger.info(
            "Scan completed for item without an initial count",
            extra={
                "action_log_id": action.id,
                "item_id": prepared.item.id,
                "operation_type": prepared.operation_type.value,
            },
        )
        flash("Ask an admin to enter an initial COUNT for this item so inventory totals stay accurate.", "warning")
    if is_admin:
        return redirect(
            surface.admin_scan_items_url(
                squad,
                from_location_id=request_data.from_location_id,
                to_location_id=request_data.to_location_id,
            )
        )
    return redirect(surface.fallback_url(squad))


def _parse_scan_item_request(
    form_data: dict,
    squad: str,
    is_admin: bool,
) -> ScanItemRequest | None:
    try:
        return ScanItemRequest(**form_data)
    except ValidationError as exc:
        logger.info(
            "Scan submit rejected: submitted quantity form data was invalid",
            extra={
                "error": str(exc),
            },
        )
        flash("Invalid form data. Please try again.", "error")
        return None


def _prepare_scan_submit(
    db: Session,
    squad: str,
    surface: ScanSurface,
    permissions,
    request_data: ScanItemRequest,
    is_admin: bool,
):
    route_error = validate_scan_route(
        current_user.id,
        request_data.from_location_id,
        request_data.to_location_id,
        permissions,
        is_admin=is_admin,
        session=db,
    )
    item = _get_scan_item(db, request_data.item_id, None, is_admin=is_admin)
    from_location = resolve_scan_location(request_data.from_location_id, current_user.id, session=db)
    to_location = resolve_scan_location(
        request_data.to_location_id,
        current_user.id,
        takeout_allowed=True,
        session=db,
    )
    if route_error:
        logger.info(
            "Scan submit rejected: selected route is not allowed",
            extra={
                "item_id": request_data.item_id,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
                "error": route_error,
            },
        )
        flash(route_error, "error")
        return redirect(surface.scan_item_error_url(squad))

    if not item:
        return _scan_item_not_found_response(squad, surface, request_data)

    operation_type, from_storage_id, to_storage_id = operation_from_storage_ids(
        request_data.from_location_id,
        request_data.to_location_id,
    )
    return ScanSubmitContext(
        request_data=request_data,
        item=item,
        operation_type=operation_type,
        from_storage_id=from_storage_id,
        to_storage_id=to_storage_id,
        from_location=from_location,
        to_location=to_location,
    )


def _scan_item_not_found_response(
    squad: str,
    surface: ScanSurface,
    request_data: ScanItemRequest,
):
    if surface == ScanSurface.ADMIN:
        logger.info(
            "Admin scan submit redirected because the item was not found",
            extra={
                "item_id": request_data.item_id,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
            },
        )
        return redirect(
            surface.admin_scan_items_url(
                squad,
                from_location_id=request_data.from_location_id,
                to_location_id=request_data.to_location_id,
                scan_error="not_found",
            )
        )
    logger.info(
        "Scan submit rejected: item was not found",
        extra={"item_id": request_data.item_id},
    )
    flash("Item not found for this squad.", "warning")
    return redirect(surface.fallback_url(squad))


def _get_scan_item(db, item_id: int | None, upc: str | None, *, is_admin: bool):
    if upc:
        return get_item_by_upc(current_user.id, upc.strip(), session=db)
    if item_id is None:
        return None
    return get_agency_item(current_user.id, item_id, session=db)
