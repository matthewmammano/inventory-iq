"""Inventory scan-flow handlers."""

from flask import flash, redirect, render_template, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError

from app.auth.device_locations import get_device_location_id
from app.shared.database import get_session

from .errors import InventoryError
from .item_queries import get_item
from .mutation_service import inventory_operation
from .scan_support import (
    can_skip_storage_selection,
    get_scan_permissions,
    operation_from_storage_ids,
    redirect_to_scan_item,
    resolve_scan_location,
    scan_fallback_endpoint,
    scan_success_message,
    storages_for_scan,
)
from .schema import ScanItemRequest, ScanStoragesRequest


def handle_scan_start(squad: str, item_id: int | None, *, is_admin: bool = False):
    """Redirect to quantity entry or storage selection for one item."""
    route = "admin" if is_admin else "guest"
    fallback = scan_fallback_endpoint(route)

    with get_session() as db:
        item = get_item(item_id, db) if item_id else None
    if not item:
        logger.error(
            "Scan start rejected: item not found",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": item_id,
                "admin": is_admin,
            },
        )
        flash("Item not found.", "error")
        return redirect(url_for(fallback, squad=squad))

    permissions = get_scan_permissions(squad, is_admin=is_admin)
    with get_session() as db:
        from_storages = storages_for_scan(current_user.id, "from", is_admin, db)
        to_storages = storages_for_scan(current_user.id, "to", is_admin, db)

    if not from_storages:
        logger.error(
            "Scan start rejected: no valid source storages",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": item.id,
                "admin": is_admin,
            },
        )
        flash("No valid storages found. Please check this device location.", "error")
        return redirect(url_for(fallback, squad=squad))
    if can_skip_storage_selection(from_storages, to_storages, permissions):
        return redirect_to_scan_item(route, squad, item.id, from_storages, to_storages, permissions)
    return redirect(
        url_for(
            f"{route}.scan_storages",
            squad=squad,
            item_id=item.id,
            user_count_allow=permissions.count,
            user_restock_allow=permissions.restock,
        )
    )


def handle_scan_storages_get(
    squad: str,
    item_id: int | None,
    user_count_allow: bool,
    user_restock_allow: bool,
    is_admin: bool = False,
):
    route = "admin" if is_admin else "guest"
    fallback = scan_fallback_endpoint(route)

    with get_session() as db:
        item = get_item(item_id, db) if item_id else None
        if not item:
            logger.error(
                "Storage selection rejected: item not found",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "item_id": item_id,
                    "admin": is_admin,
                },
            )
            flash("Item not found.", "error")
            return redirect(url_for(fallback, squad=squad))

        from_storages = storages_for_scan(current_user.id, "from", is_admin, db)
        to_storages = storages_for_scan(current_user.id, "to", is_admin, db)
        default_location_id = None if is_admin else get_device_location_id(current_user.id, db)

    return render_template(
        "scan_storages.html",
        squad=squad,
        item=item,
        from_locations=from_storages,
        to_locations=to_storages,
        show_storage_only=default_location_id is not None,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_storages_post(squad: str, form_data: dict, is_admin: bool = False):
    route = "admin" if is_admin else "guest"
    fallback = scan_fallback_endpoint(route)

    try:
        request_data = ScanStoragesRequest(**form_data)
    except ValidationError as exc:
        logger.error(
            "Storage selection rejected: invalid form data",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "admin": is_admin,
                "error": str(exc),
            },
        )
        flash("Invalid form data. Please try again.", "error")
        return redirect(url_for(fallback, squad=squad))

    if request_data.same_location_error == "1":
        logger.error(
            "Storage selection rejected: invalid storage combination",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": request_data.item_id,
                "from_storage_id": request_data.from_location_id,
                "to_storage_id": request_data.to_location_id,
                "admin": is_admin,
            },
        )
        flash("Invalid storage combination.", "error")
        return redirect(
            url_for(f"{route}.scan_storages", squad=squad, item_id=request_data.item_id)
        )

    return redirect(
        url_for(
            f"{route}.scan_item",
            squad=squad,
            item_id=request_data.item_id,
            from_location_id=request_data.from_location_id,
            to_location_id=request_data.to_location_id,
        )
    )


def handle_scan_item_get(
    squad: str,
    item_id: int | None,
    from_location_id,
    to_location_id,
    user_count_allow: bool = False,
    user_restock_allow: bool = False,
    is_admin: bool = False,
):
    route = "admin" if is_admin else "guest"
    fallback = scan_fallback_endpoint(route)
    from_location = resolve_scan_location(from_location_id, current_user.id)
    to_location = resolve_scan_location(to_location_id, current_user.id, takeout_allowed=True)

    item = get_item(item_id) if item_id else None
    if not item or not from_location:
        logger.error(
            "Scan item page rejected: invalid item or storage",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": item_id,
                "from_storage_id": from_location_id,
                "to_storage_id": to_location_id,
                "admin": is_admin,
            },
        )
        flash("Invalid item or storage.", "error")
        return redirect(url_for(fallback, squad=squad))

    return render_template(
        "scan_item.html",
        squad=squad,
        item=item,
        from_location=from_location,
        to_location=to_location,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_item_post(squad: str, form_data: dict, is_admin: bool = False):
    route = "admin" if is_admin else "guest"
    fallback = scan_fallback_endpoint(route)

    try:
        request_data = ScanItemRequest(**form_data)
    except ValidationError as exc:
        logger.error(
            "Scan item rejected: invalid form data",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "admin": is_admin,
                "error": str(exc),
            },
        )
        flash("Invalid form data.", "error")
        return redirect(url_for(fallback, squad=squad))

    item = get_item(request_data.item_id)
    if not item:
        logger.error(
            "Scan item rejected: item not found",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": request_data.item_id,
                "admin": is_admin,
            },
        )
        flash("Item not found.", "error")
        return redirect(url_for(fallback, squad=squad))

    try:
        operation_type, from_storage_id, to_storage_id = operation_from_storage_ids(
            request_data.from_location_id,
            request_data.to_location_id,
        )
        inventory_operation(
            agency_id=current_user.id,
            item_id=item.id,
            quantity=request_data.counter_value,
            operation_type=operation_type,
            from_location=from_storage_id,
            to_location=to_storage_id,
            admin_action=is_admin,
        )
    except (InventoryError, ValueError) as exc:
        logger.error(
            "Inventory operation rejected",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": request_data.item_id,
                "admin": is_admin,
                "error": str(exc),
            },
        )
        flash(str(exc), "error")
        return redirect(url_for(fallback, squad=squad, item_id=request_data.item_id))
    except Exception:
        logger.exception(
            "Unexpected error during inventory operation",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": request_data.item_id,
                "admin": is_admin,
            },
        )
        flash("System error - please try again.", "error")
        return redirect(url_for(fallback, squad=squad, item_id=request_data.item_id))

    message = scan_success_message(
        operation_type,
        item.name,
        request_data.counter_value,
        from_storage_id,
        to_storage_id,
        is_admin=is_admin,
    )
    logger.info(
        "Inventory operation completed",
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "item_id": item.id,
            "operation_type": operation_type.value,
            "quantity": request_data.counter_value,
            "from_storage_id": from_storage_id,
            "to_storage_id": to_storage_id,
            "admin": is_admin,
        },
    )
    flash(message, "success")
    return redirect(url_for(f"{route}.{'admin_panel' if is_admin else 'index'}", squad=squad))
