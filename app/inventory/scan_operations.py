from flask import flash, redirect, render_template, url_for
from flask_login import current_user
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.auth.location_queries import list_locations
from app.auth.models import UserItemLocations, Users
from app.db import get_session
from app.inventory.inventory_ops import InventoryError, inventory_operation
from app.inventory.item_queries import get_item
from app.inventory.models import Items, OperationType


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
        """Parse location IDs including virtual locations (-1, -2)."""
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
    """Safely parse location id from strings like '-1', '-2' or numeric strings.

    Returns None if input is None or not parseable. Accepts ints as well.
    """
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if val in ("-1", "-2"):
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def get_scan_permissions(squad: str, is_admin: bool = False) -> tuple[bool, bool, bool]:
    """Return (user_count_allow, user_restock_allow, user_take_allow).

    If is_admin is True, grant all permissions. Otherwise read from the Users table
    for the squad's user record.
    """
    if is_admin:
        return True, True, True

    try:
        with get_session() as session:
            stmt = select(
                Users.user_count_allow, Users.user_restock_allow, Users.user_take_allow
            ).where(Users.display_name == squad)
            row = session.execute(stmt).first()

        if not row:
            return False, False, False
        return bool(row[0]), bool(row[1]), bool(row[2])
    except Exception:
        logger.exception("Error fetching scan permissions")
        return False, False, False


def handle_scan_start(squad: str, item_id: int | None, is_admin: bool = False):
    """Decide whether to go directly to item scan or ask for locations."""
    with get_session() as db_session:
        item = get_item(item_id, db_session) if item_id else None

    if not item:
        logger.warning(f"Scan attempted with invalid item_id: {item_id}")
        flash("Item not found.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    user_count_allow, user_restock_allow, user_take_allow = get_scan_permissions(
        squad, is_admin
    )

    with get_session() as db_session:
        from_location = list(
            list_locations(current_user.id, user_access_from=True, session=db_session)
        )
        to_location = list(
            list_locations(current_user.id, user_access_to=True, session=db_session)
        )

    # Adjust counts based on permissions
    from_count = (
        len(from_location)
        + (1 if user_count_allow else 0)
        + (1 if user_restock_allow else 0)
    )
    to_count = len(to_location) + (1 if user_take_allow else 0)

    if from_count == to_count == 1:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_item",
                squad=squad,
                item_id=item.id,
                from_location_id=from_location[0].id if from_location else None,
                to_location_id=to_location[0].id if to_location else None,
                user_count_allow=user_count_allow,
                user_restock_allow=user_restock_allow,
                user_take_allow=user_take_allow,
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
            user_count_allow=user_count_allow,
            user_restock_allow=user_restock_allow,
            user_take_allow=user_take_allow,
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

        if is_admin:
            from_locations = list(list_locations(current_user.id, session=db_session))
            to_locations = list(list_locations(current_user.id, session=db_session))
        else:
            from_locations = list(
                list_locations(
                    current_user.id, user_access_from=True, session=db_session
                )
            )
            to_locations = list(
                list_locations(current_user.id, user_access_to=True, session=db_session)
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
    """Render scan item page; supports virtual location ids (-1 restock, -2 count)."""
    # reuse module-level _parse_loc_id

    with get_session() as session:
        parsed_item_id = _parse_loc_id(item_id) if item_id is not None else None
        item = (
            session.get(Items, parsed_item_id) if parsed_item_id is not None else None
        )

        parsed_from = _parse_loc_id(from_location_id)
        if parsed_from in (-1, -2):
            from_location = parsed_from
        elif parsed_from is not None:
            from_location = session.get(UserItemLocations, parsed_from)
        else:
            from_location = None

        parsed_to = _parse_loc_id(to_location_id)
        if parsed_to == -1:
            to_location = -1
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
    if (validated.from_location_id is None or validated.from_location_id == -1) and (
        validated.to_location_id is None or validated.to_location_id == -1
    ):
        flash("Please select a location for this operation.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=validated.item_id))

    # Convert parsed location ids into canonical values used by inventory_operation
    from_loc_val: int | None = (
        validated.from_location_id
        if validated.from_location_id not in (-1, -2)
        else validated.from_location_id
    )
    to_loc_val: int | None = (
        validated.to_location_id if validated.to_location_id != -1 else -1
    )

    # Determine operation type based on virtual location IDs
    if from_loc_val == -1:  # RESTOCK
        op_type = OperationType.restock
        from_loc_for_op = None
    elif from_loc_val == -2:  # COUNT
        op_type = OperationType.count
        from_loc_for_op = None
    elif (from_loc_val is not None and from_loc_val > 0) and (
        to_loc_val is not None and to_loc_val > 0
    ):  # TRANSFER
        op_type = OperationType.transfer
        from_loc_for_op = from_loc_val
    elif (
        from_loc_val is not None and from_loc_val > 0
    ) and to_loc_val == -1:  # TAKEOUT
        op_type = OperationType.takeout
        from_loc_for_op = from_loc_val
        to_loc_val = None
    else:
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

    # Create operation-specific success message
    if op_type == OperationType.count:
        flash(
            f"Successfully set {item.name} quantity to {validated.counter_value}.",
            "success",
        )
    elif op_type == OperationType.restock:
        flash(
            f"Successfully restocked {validated.counter_value} {item.name} from supplier.",
            "success",
        )
    elif op_type == OperationType.takeout:
        flash(
            f"Successfully removed {validated.counter_value} {item.name} from inventory.",
            "success",
        )
    else:
        flash(
            f"Successfully transferred {validated.counter_value} {item.name}.",
            "success",
        )

    endpoint = "admin.admin_panel" if is_admin else "guest.index"
    return redirect(url_for(endpoint, squad=squad))
