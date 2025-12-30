from dataclasses import dataclass

from flask import flash, redirect, render_template, url_for
from flask_login import current_user
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.auth.location_queries import list_locations
from app.auth.models import UserItemLocations, Users
from app.db import get_session
from app.inventory.constants import (
    VIRTUAL_LOCATION_COUNT,
    VIRTUAL_LOCATION_RESTOCK,
    VIRTUAL_LOCATION_TAKEOUT,
    OperationType,
)
from app.inventory.inventory_ops import InventoryError, inventory_operation
from app.inventory.item_queries import get_item
from app.inventory.models import Items


@dataclass
class ScanPermissions:
    """User permissions for scan operations."""

    count: bool
    restock: bool
    takeout: bool


def _determine_operation_type(
    from_location_id: int | None, to_location_id: int | None
) -> tuple[OperationType, int | None, int | None]:
    """Determine operation type and canonical location IDs from virtual locations.

    Args:
        from_location_id: Source location (-1=restock, -2=count, >0=real location)
        to_location_id: Destination location (-1=takeout, >0=real location)

    Returns:
        Tuple of (operation_type, from_location, to_location) for inventory_operation

    Raises:
        ValueError: If location combination is invalid
    """
    if from_location_id == -1:  # RESTOCK
        return OperationType.restock, None, to_location_id

    if from_location_id == -2:  # COUNT
        return OperationType.count, None, to_location_id

    if (from_location_id is not None and from_location_id > 0) and (
        to_location_id is not None and to_location_id > 0
    ):  # TRANSFER
        return OperationType.transfer, from_location_id, to_location_id

    if (
        from_location_id is not None and from_location_id > 0
    ) and to_location_id == -1:  # TAKEOUT
        return OperationType.takeout, from_location_id, None

    raise ValueError("Invalid operation parameters")


def _parse_location_id(v) -> int | None:
    """Parse location IDs including virtual locations.

    Shared validator for all Pydantic models needing location parsing.
    Handles VIRTUAL_LOCATION_RESTOCK, VIRTUAL_LOCATION_COUNT, VIRTUAL_LOCATION_TAKEOUT.
    """
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None


def _get_locations_by_access(
    user_id: int, direction: str, is_admin: bool, session
) -> list[UserItemLocations]:
    """Fetch locations user can access. Admin sees all, guests see filtered."""
    if is_admin:
        return list(list_locations(user_id, session=session))

    if direction == "from":
        return list(list_locations(user_id, user_access_from=True, session=session))
    return list(list_locations(user_id, user_access_to=True, session=session))


def _get_success_message(
    op_type: OperationType,
    item_name: str,
    quantity: int,
    from_location_name: str | None = None,
    to_location_name: str | None = None,
) -> str:
    """Generate operation-specific success message with location details."""
    messages = {
        OperationType.count: f"Successfully set {item_name} quantity to {quantity} at {to_location_name}.",
        OperationType.restock: f"Successfully restocked {quantity} {item_name} to {to_location_name}.",
        OperationType.takeout: f"Successfully removed {quantity} {item_name} from {from_location_name}.",
        OperationType.transfer: f"Successfully transferred {quantity} {item_name} from {from_location_name} to {to_location_name}.",
    }
    return messages.get(op_type, f"Operation completed for {item_name}.")


class ScanLocationsRequest(BaseModel):
    """Validation model for scan locations form submission."""

    item_id: int = Field(..., gt=0, description="Item ID must be positive")
    from_location_id: int | None = Field(
        None, description="From location ID or virtual location"
    )
    to_location_id: int | None = Field(
        None, description="To location ID or virtual location"
    )
    same_location_error: str | None = Field(
        None, description="Same location error flag"
    )

    @field_validator("from_location_id", "to_location_id", mode="before")
    @classmethod
    def parse_location_id(cls, v):
        """Parse location IDs including virtual locations (-1, -2)."""
        return _parse_location_id(v)


class ScanItemRequest(BaseModel):
    """Validation model for scan item form submission."""

    item_id: int = Field(..., gt=0, description="Item ID must be positive")
    from_location_id: int | None = Field(
        None, description="From location ID or virtual location"
    )
    to_location_id: int | None = Field(
        None, description="To location ID or virtual location"
    )
    counter_value: int = Field(..., gt=0, description="Quantity must be positive")

    @field_validator("from_location_id", "to_location_id", mode="before")
    @classmethod
    def parse_location_id(cls, v):
        """Parse location IDs including virtual locations."""
        return _parse_location_id(v)

    @field_validator("counter_value", mode="before")
    @classmethod
    def parse_counter_value(cls, v):
        """Parse counter value from string or int."""
        if v is None or v == "":
            raise ValueError("Quantity is required")
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
        raise ValueError("Quantity must be a valid number")


def _parse_loc_id(val: str | int | None) -> int | None:
    """Safely parse location id from strings or numeric strings.

    Returns None if input is None or not parseable. Accepts ints as well.
    """
    if val is None:
        return None
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def get_scan_permissions(squad: str, is_admin: bool = False) -> ScanPermissions:
    """Get user permissions for scan operations.

    Args:
        squad: Squad name to fetch permissions for
        is_admin: If True, grant all permissions

    Returns:
        ScanPermissions with count, restock, and takeout flags
    """
    if is_admin:
        return ScanPermissions(count=True, restock=True, takeout=True)

    try:
        with get_session() as session:
            stmt = select(
                Users.user_count_allow, Users.user_restock_allow, Users.user_take_allow
            ).where(Users.display_name == squad)
            row = session.execute(stmt).first()

        if not row:
            return ScanPermissions(count=False, restock=False, takeout=False)
        return ScanPermissions(
            count=bool(row[0]), restock=bool(row[1]), takeout=bool(row[2])
        )
    except Exception:
        logger.exception("Error fetching scan permissions")
        return ScanPermissions(count=False, restock=False, takeout=False)


def handle_scan_start(squad: str, item_id: int | None, is_admin: bool = False):
    """Decide whether to go directly to item scan or ask for locations."""
    with get_session() as db_session:
        item = get_item(item_id, db_session) if item_id else None

    if not item:
        logger.warning(f"Scan attempted with invalid item_id: {item_id}")
        flash("Item not found.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    perms = get_scan_permissions(squad, is_admin)

    with get_session() as db_session:
        from_location = _get_locations_by_access(
            current_user.id, "from", is_admin, db_session
        )
        to_location = _get_locations_by_access(
            current_user.id, "to", is_admin, db_session
        )

    # Adjust counts based on permissions
    from_count = (
        len(from_location) + (1 if perms.count else 0) + (1 if perms.restock else 0)
    )
    to_count = len(to_location) + (1 if perms.takeout else 0)

    if from_count == to_count == 1:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_item",
                squad=squad,
                item_id=item.id,
                from_location_id=from_location[0].id if from_location else None,
                to_location_id=to_location[0].id if to_location else None,
                user_count_allow=perms.count,
                user_restock_allow=perms.restock,
                user_take_allow=perms.takeout,
            )
        )

    if len(from_location) == 0:
        flash(
            "No valid locations found to access items. Please add more in the admin panel.",
            "error",
        )
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    route_prefix = "admin" if is_admin else "guest"
    return redirect(
        url_for(
            f"{route_prefix}.scan_locations",
            squad=squad,
            item_id=item.id,
            user_count_allow=perms.count,
            user_restock_allow=perms.restock,
            user_take_allow=perms.takeout,
        )
    )


def handle_scan_locations_get(
    squad: str,
    item_id: int | None,
    user_count_allow: bool,
    user_restock_allow: bool,
    user_take_allow: bool,
    is_admin: bool = False,
):
    """Render the locations selection page for scanning."""
    with get_session() as db_session:
        item = get_item(item_id, db_session) if item_id else None
        if not item:
            flash("Item not found.", "error")
            endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
            return redirect(url_for(endpoint, squad=squad))

        from_locations = _get_locations_by_access(
            current_user.id, "from", is_admin, db_session
        )
        to_locations = _get_locations_by_access(
            current_user.id, "to", is_admin, db_session
        )

    return render_template(
        "scan_locations.html",
        squad=squad,
        item=item,
        from_locations=from_locations,
        to_locations=to_locations,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        user_take_allow=user_take_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_locations_post(squad: str, form_data: dict, is_admin: bool = False):
    """Handle location selection form submission with validation."""
    try:
        validated = ScanLocationsRequest(**form_data)
    except ValidationError as e:
        logger.warning(f"Invalid scan locations form data: {e}")
        flash("Invalid form data. Please try again.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    if validated.same_location_error == "1":
        flash("Invalid location combination selected, please try again.", "error")
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_locations", squad=squad, item_id=validated.item_id
            )
        )

    route_prefix = "admin" if is_admin else "guest"
    return redirect(
        url_for(
            f"{route_prefix}.scan_item",
            squad=squad,
            item_id=validated.item_id,
            from_location_id=validated.from_location_id,
            to_location_id=validated.to_location_id,
        )
    )


def handle_scan_item_get(
    squad: str,
    item_id: int | None,
    from_location_id,
    to_location_id,
    user_count_allow: bool = False,
    user_restock_allow: bool = False,
    user_take_allow: bool = False,
    is_admin: bool = False,
):
    """Render scan item page; supports virtual location IDs for special operations."""
    with get_session() as session:
        parsed_item_id = _parse_loc_id(item_id) if item_id is not None else None
        item = (
            session.get(Items, parsed_item_id) if parsed_item_id is not None else None
        )

        parsed_from = _parse_loc_id(from_location_id)
        if parsed_from in (VIRTUAL_LOCATION_RESTOCK, VIRTUAL_LOCATION_COUNT):
            from_location = parsed_from
        elif parsed_from is not None:
            from_location = session.get(UserItemLocations, parsed_from)
        else:
            from_location = None

        parsed_to = _parse_loc_id(to_location_id)
        if parsed_to == VIRTUAL_LOCATION_TAKEOUT:
            to_location = VIRTUAL_LOCATION_TAKEOUT
        elif parsed_to is not None:
            to_location = session.get(UserItemLocations, parsed_to)
        else:
            to_location = None

    if not item or not from_location:
        flash("Invalid item or locations.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    return render_template(
        "scan_item.html",
        squad=squad,
        item=item,
        from_location=from_location,
        to_location=to_location,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        user_take_allow=user_take_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_item_post(squad: str, form_data: dict, is_admin: bool = False):
    """Handle scan item form submission with Pydantic validation."""
    # Validate and parse form data
    try:
        validated = ScanItemRequest(**form_data)
    except ValidationError as e:
        logger.warning(f"Invalid scan item form data: {e}")
        flash("Invalid form data. Please check your input and try again.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    # Fetch item from database
    with get_session() as session:
        item = session.get(Items, validated.item_id)

    if not item:
        flash("Item not found. Please verify the UPC code and try again.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    # Check that at least one location is specified
    if (
        validated.from_location_id is None
        or validated.from_location_id == VIRTUAL_LOCATION_TAKEOUT
    ) and (
        validated.to_location_id is None
        or validated.to_location_id == VIRTUAL_LOCATION_TAKEOUT
    ):
        flash("Please select a location for this operation.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=validated.item_id))

    # Determine operation type and canonical location values
    try:
        op_type, from_loc_for_op, to_loc_val = _determine_operation_type(
            validated.from_location_id, validated.to_location_id
        )
    except ValueError as e:
        logger.error(f"Invalid operation parameters: {e}")
        flash("Invalid operation parameters.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=validated.item_id))

    # Execute inventory operation
    try:
        updated_quantities, alerts = inventory_operation(
            user_id=current_user.id,
            item_id=item.id,
            quantity=validated.counter_value,
            operation_type=op_type,
            from_location=from_loc_for_op,
            to_location=to_loc_val,
            admin_action=is_admin,
        )
        logger.info(f"Inventory operation completed with {len(alerts)} alerts")
    except InventoryError as e:
        flash(str(e), "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=validated.item_id))
    except Exception as e:
        logger.exception(f"Unexpected error during inventory operation: {e}")
        flash("System error - please try again", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=validated.item_id))

    # Fetch location names for success message
    with get_session() as session:
        from_loc_name = None
        to_loc_name = None
        if from_loc_for_op:
            from_loc = session.get(UserItemLocations, from_loc_for_op)
            from_loc_name = from_loc.name if from_loc else None
        if to_loc_val:
            to_loc = session.get(UserItemLocations, to_loc_val)
            to_loc_name = to_loc.name if to_loc else None

    # Create operation-specific success message
    message = _get_success_message(
        op_type, item.name, validated.counter_value, from_loc_name, to_loc_name
    )
    flash(message, "success")

    endpoint = "admin.admin_panel" if is_admin else "guest.index"
    return redirect(url_for(endpoint, squad=squad))
