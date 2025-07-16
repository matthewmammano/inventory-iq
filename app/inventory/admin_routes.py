import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from app import db
from app.auth.models import UserItemTags, Users
from app.inventory import admin_bp as bp
from app.inventory.models import Items

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


@bp.before_request
def check_admin_authorization():
    """
    Secure all admin routes with the following checks:
    1. User must be logged in (Flask-Login)
    2. Admin session must be valid
    3. Squad parameter must be valid
    """
    # Skip if it's a static asset or similar
    if request.endpoint and "static" in request.endpoint:
        return

    # Check if user is logged in
    if not current_user.is_authenticated:
        flash("You must be logged in to access this page.", "warning")
        return redirect(url_for("auth.login"))

    # Get squad parameter
    squad = request.view_args.get("squad")
    if not squad:
        flash("Squad name is required.", "warning")
        return redirect(url_for("auth.login"))

    # Verify the squad exists in the database
    user = Users.query.filter_by(display_name=squad).first()
    if user is None:
        flash("Invalid squad name. Please try again.")
        return redirect(url_for("auth.login"))

    if user.active is False:
        flash("This squad is now inactive. Please contact support.")
        return redirect(url_for("auth.login"))

    # Check admin session validity
    if session.get("admin"):
        now = datetime.now(timezone.utc).timestamp()
        admin_last_active = session.get("admin_last_active")

        if not admin_last_active or now - admin_last_active > ADMIN_TIMEOUT_SECONDS:
            session.pop("admin", None)
            session.pop("admin_last_active", None)
            flash("Admin session expired. Please log in with your PIN again.", "warning")
            return redirect(url_for("guest.index", squad=squad))

        # Update last active timestamp
        session["admin_last_active"] = now
    else:
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        flash("Admin session not found. Please log in with PIN.", "warning")
        return redirect(url_for("guest.index", squad=squad))

    # Verify the current user belongs to the requested squad
    if current_user.display_name != squad:
        flash("You do not have permission to access this squad.", "warning")
        return redirect(url_for("auth.login"))


# Admin dashboard (protected)
@bp.route("/<squad>/admin-panel")
def admin_panel(squad):
    return render_template("admin_panel.html", squad=squad, admin=True)


# Admin item viewing page (protected)
@bp.route("/<squad>/admin-panel/view-items")
def admin_view_items(squad):
    items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
    categories = UserItemTags.query.filter_by(user_id=current_user.id).all()
    return render_template("admin_items_manager.html", squad=squad, items=items, categories=categories, admin=True)


# Admin help page (protected)
@bp.route("/<squad>/help")
def help_page(squad):
    developer_phone = os.getenv("CONTACT_PHONE", "UNAVAILABLE")
    return render_template("admin_help.html", squad=squad, contact_phone=developer_phone, admin=True)


# Admin move items page (protected)
@bp.route("/<squad>/admin-panel/move-items")
def move_items(squad):
    return render_template("admin_move_items.html", squad=squad, admin=True)


# Admin recount items page (protected)
@bp.route("/<squad>/admin-panel/recount-items")
def recount_items(squad):
    return render_template("admin_recount_items.html", squad=squad, admin=True)


# Admin edit items in table page (protected)
@bp.route("/<squad>/admin-panel/edit-items", methods=["GET", "POST"])
def save_items(squad):
    if request.method == "GET":
        items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
        return render_template(
            "admin_edit_items.html",
            squad=squad,
            items=items,
            tags=UserItemTags.query.filter_by(user_id=current_user.id).all(),
            admin=True,
        )

    # Process the JSON data from the form
    items_data = request.form.get("itemsData")
    if not items_data:
        flash("No item data received", "warning")
        return redirect(url_for("admin.admin_view_items", squad=squad))

    try:
        items_list = json.loads(items_data)
    except json.JSONDecodeError:
        flash("Invalid item data format", "warning")
        return redirect(url_for("admin.admin_view_items", squad=squad))

    # Keep track of existing items to detect deletions
    existing_ids = set(item.id for item in Items.query.filter_by(user_id=current_user.id).all())
    processed_ids = set()
    new_items = []
    error_items = []

    # Process each item
    for item_data in items_list:
        name = item_data.get("name", "").strip()
        if not name:
            error_items.append("Unnamed Item")
            continue

        # Get other fields
        item_id = item_data.get("id")
        active = item_data.get("active", True)  # Default to True if not provided
        tag_ids = item_data.get("tag_ids", [])
        if isinstance(tag_ids, str):
            tag_ids = [int(x.strip()) for x in tag_ids.split(",") if x.strip().isdigit()]
        increments = item_data.get("increments")
        image = item_data.get("image", "").strip()

        # Validate tag_ids if provided
        if tag_ids:
            try:
                valid_tags = UserItemTags.query.filter(
                    UserItemTags.id.in_(tag_ids), UserItemTags.user_id == current_user.id
                ).all()
                if len(valid_tags) != len(tag_ids):
                    error_items.append(name)
                    continue
            except (ValueError, TypeError):
                error_items.append(name)
                continue

        # Process existing items vs new items
        if item_id != "new" and item_id is not None:
            try:
                item_id = int(item_id)
                processed_ids.add(item_id)

                # Update existing item
                item = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
                if not item:
                    error_items.append(name)
                    continue

                item.name = name
                item.active = active
                item.tag_ids = tag_ids
                item.increments = increments if increments else None
                item.image = image if image else None
            except (ValueError, TypeError):
                error_items.append(name)
                continue
        else:
            # Create new item
            try:
                item = Items(
                    active=active,
                    tag_ids=tag_ids,
                    increments=increments if increments else None,
                    name=name,
                    image=image if image else None,
                    user_id=current_user.id,
                )
                db.session.add(item)
                new_items.append(item)
            except Exception:
                error_items.append(name)
                continue

    # Delete items that were removed from the form
    for item_id in existing_ids - processed_ids:
        item_to_delete = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
        if item_to_delete:
            db.session.delete(item_to_delete)

    # Commit all changes
    db.session.commit()

    if error_items:
        flash(
            f"Some items were not saved due to invalid data: {', '.join(error_items)}",
            "warning",
        )
    else:
        flash("All items saved successfully!", "success")

    return redirect(url_for("admin.admin_view_items", squad=squad))


@bp.route("/<squad>/admin-panel/view-locations")
def admin_view_locations(squad):
    pass  # TODO RED


@bp.route("/<squad>/admin-panel/view-sublocations")
def admin_view_sublocations(squad):
    pass  # TODO RED


@bp.route("/<squad>/admin-panel/view-tags")
def admin_view_tags(squad):
    pass  # TODO RED
