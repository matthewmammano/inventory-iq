from flask import flash, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user

from app import db
from app.auth import bp
from app.auth.models import Users

# TODO GREEN 1: batch scan out

# TODO GREEN 2: add a rig-chick feature
# - store info about # of items in each place of ambulance (bag, shelf, back of stretcher, etc)
# - doing the form AUTOMATICALLY tells you how much of each item to take out... then you correct that number in end


# Root route serves login page directly
@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = Users.query.filter_by(email=email).first()

        # Check if the user exists
        if user is None:
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        # Check if password is set yet, ask them to set it if not
        if not user.password:
            flash("Please set your password first.", "info")
            return redirect(url_for("auth.set_password"))

        # Check if password is correct
        if user.check_password(password):
            login_user(user)
            flash("Logged in successfully!", "success")
            return redirect(url_for("guest.index", squad=user.display_name))

        # If the password is incorrect, show an error message
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    return render_template("login.html", logo_img="images/logos/me.svg")


# Set password route (for first-time users AND reset password)
@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    if request.method == "POST":
        email = request.form["email"]
        new_password = request.form["password"]

        # Find the user by email
        user = Users.query.filter_by(email=email).first()
        if user is None:
            flash("Invalid email", "error")
            return redirect(url_for("auth.set_password"))
        elif user.password:
            flash("Password already set. Please log in.", "info")
            return redirect(url_for("auth.login"))

        try:
            user.set_password(new_password)
            db.session.commit()
            flash("Password set successfully. Please log in now.", "success")
        except Exception:
            db.session.rollback()
            flash("An error occurred setting your password. Please try again.", "error")
        return redirect(url_for("auth.login"))

    return render_template("set_password.html")


@bp.route("/logout")
def logout():
    # Clear session variables related to admin mode
    session.pop("admin", None)
    session.pop("admin_last_active", None)

    # Log the user out completely
    logout_user()
    flash("Logged out successfully!", "success")
    return redirect(url_for("auth.login"))
