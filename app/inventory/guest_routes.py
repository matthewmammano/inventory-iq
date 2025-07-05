from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app import db
from app.auth.models import UserLocations, Users
from app.inventory import guest_bp as bp
from app.inventory.models import ActionLogs, Items


@bp.before_request
def check_authentication_and_squad():
    """
    Common checks for guest routes:
    1. Reset admin session for guest views
    2. Check if user is logged in for protected routes
    3. Validate squad parameter exists
    """
    # Skip for static assets
    if request.endpoint and "static" in request.endpoint:
        return

    # Reset admin session for all guest routes
    session.pop("admin", None)
    session.pop("admin_last_active", None)

    squad = request.view_args.get("squad")
    if not squad:
        flash("Invalid squad name. Please try again.", "error")
        return redirect(url_for("auth.login"))

    # For all other routes, check login and squad
    if not current_user.is_authenticated:
        flash("You must be logged in to access this page.", "warning")
        return redirect(url_for("auth.login"))

    # Verify the squad exists in the database
    user = Users.query.filter_by(display_name=squad).first()
    if user is None:
        flash("Invalid squad name. Please try again.", "error")
        return redirect(url_for("auth.login"))

    if user.active is False:
        flash("This squad is now inactive. Please contact support.", "warning")
        return redirect(url_for("auth.login"))


@bp.route("/<squad>/")
@login_required
def index(squad):
    """
    Display the inventory for the given squad to search or scan UPC.
    """
    # Get the list of items and order them by last_accessed
    items = (
        Items.query.filter_by(user_id=current_user.id)
        .order_by(Items.last_accessed.desc().nullslast())
        .all()
    )
    return render_template(
        "index.html", items=items, squad=squad, logo_img=current_user.image
    )


@bp.route("/<squad>/scan")
@login_required
def scan_start(squad):
    """Entry point for scanning - decides scan_selection vs scan"""
    item_id = request.args.get("item_id")
    item = Items.query.filter_by(id=item_id).first() if item_id else None

    if not item:
        flash("Item not found.", "error")
        return redirect(url_for("guest.index", squad=squad))

    locations = UserLocations.query.filter_by(user_id=current_user.id)
    from_location = locations.filter_by(user_access_from=True).all()
    to_location = locations.filter_by(user_access_to=True).all()

    if len(from_location) == len(to_location) == 1:
        return redirect(
            url_for(
                "guest.scan_item",
                squad=squad,
                item_id=item.id,
                from_location=from_location[0].id,
                to_location=to_location[0].id,
            )
        )
    elif len(from_location) == 0 or len(to_location) == 0:
        flash("No valid locations found. Please add more in the admin panel.", "error")
        return redirect(url_for("guest.index", squad=squad))

    else:
        return redirect(
            url_for(
                "guest.scan_locations",
                squad=squad,
                item_id=item.id,
            )
        )


@bp.route("/<squad>/scan/locations", methods=["GET", "POST"])
@login_required
def scan_locations(squad):
    """Select to and from locations for scanning"""
    if request.method == "POST":
        item_id = request.form.get("item_id")
        from_location_id = request.form.get("from_location_id")
        to_location_id = request.form.get("to_location_id")

        return redirect(
            url_for(
                "guest.scan_item",
                squad=squad,
                item_id=item_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
            )
        )
    else:
        item_id = request.args.get("item_id")
        item = Items.query.filter_by(id=item_id).first() if item_id else None

        if not item:
            flash("Item not found.", "error")
            return redirect(url_for("guest.index", squad=squad))

        locations = UserLocations.query.filter_by(user_id=current_user.id)
        from_locations = locations.filter_by(user_access_from=True).all()
        to_locations = locations.filter_by(user_access_to=True).all()

        return render_template(
            "scan_locations.html",
            squad=squad,
            item=item,
            from_locations=from_locations,
            to_locations=to_locations,
            logo_img=current_user.image,
        )


@bp.route("/<squad>/scan/item", methods=["GET", "POST"])
@login_required
def scan_item(squad):
    """Scan item with locations alerady selected (automatically if only one each)"""
    if request.method == "POST":
        item_id = request.form.get("item_id")
        counter_value = request.form.get(
            "counter_value",
        )
        from_location_id = request.form.get("from_location_id")
        to_location_id = request.form.get("to_location_id")

        item = Items.query.filter_by(id=item_id).first()

        if not item:
            flash("Item not found. Please check the UPC code.", "error")
            return redirect(url_for("guest.index", squad=squad))

        if not from_location_id or not to_location_id:
            flash("Both from and to locations must be selected.", "error")
            return redirect(url_for("guest.index", squad=squad, item_id=item_id))

        if not counter_value or not counter_value.isdigit():
            flash("Invalid counter value. Please enter a valid number.", "error")
            return redirect(url_for("guest.index", squad=squad, item_id=item_id))

        counter_value = int(counter_value)

        action_log = ActionLogs(
            item_id=item.id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity_delta=counter_value,
            admin_action=False,
            user_id=current_user.id,
        )
        db.session.add(action_log)
        db.session.commit()

        flash(f"Successfully moved {counter_value} {item.name}.", "success")
        return redirect(url_for("guest.index", squad=squad))
    else:
        item_id = request.args.get("item_id")
        from_location_id = request.args.get("from_location_id")
        to_location_id = request.args.get("to_location_id")

        item = Items.query.get(item_id)
        from_location = (
            -1 if from_location_id == -1 else UserLocations.query.get(from_location_id)
        )
        to_location = UserLocations.query.get(to_location_id)

        if not item or not from_location or not to_location:
            flash(
                f"Invalid item or locations. {item_id}, {from_location_id}, {to_location_id}",
                "error",
            )
            # flash("Invalid item or locations.", "error")
            return redirect(url_for("guest.index", squad=squad))

        return render_template(
            "scan_item.html",
            squad=squad,
            item=item,
            from_location=from_location,
            to_location=to_location,
            logo_img=current_user.image,
        )


# Admin login page using PIN from Users DB
@bp.route("/<squad>/admin", methods=["GET", "POST"])
def admin_login(squad):
    if request.method == "POST":
        password = request.form["password"]
        user = Users.query.filter_by(display_name=squad).first()
        correct_password = user.pin

        if user.pin and password == correct_password:
            session["admin"] = True
            session["admin_last_active"] = datetime.now(timezone.utc).timestamp()
            flash("Admin access granted.", "success")
            return redirect(url_for("admin.admin_panel", squad=squad))
        else:
            flash("Invalid PIN entered. Please try again.", "error")
            return render_template("admin_login.html", squad=squad, admin=True)

    return render_template("admin_login.html", squad=squad, admin=True)
