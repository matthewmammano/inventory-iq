from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from loguru import logger
from sqlalchemy import select

from app.auth import bp
from app.auth.models import Users
from app.db import get_session

# TODO-1: batch scan out

# TODO-1: add a rig-check feature
# - store info about # of items in each place of ambulance (bag, shelf, back of stretcher, etc)
# - doing the form AUTOMATICALLY tells you how much of each item to take out... then you correct that number in end


# Root route serves login page directly
@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "").strip()

            if not email or not password:
                logger.warning(
                    f"Login attempt with missing fields - email: {bool(email)}, password: {bool(password)}"
                )
                flash("Email and password are required.", "error")
                return redirect(url_for("auth.login"))

            with get_session() as session:
                stmt = select(Users).where(Users.email == email)
                user = session.execute(stmt).scalars().first()

            # Check if the user exists
            if user is None:
                logger.warning(f"Failed login attempt - user not found: {email}")
                flash("Invalid email or password.", "error")
                return redirect(url_for("auth.login"))

            # Check if password is set yet, ask them to set it if not
            if not user.password:
                logger.info(f"User {email} needs to set password")
                flash("Please set your password first.", "info")
                return redirect(url_for("auth.set_password"))

            # Check if password is correct
            if user.check_password(password):
                login_user(user)
                logger.info(f"Successful login: {user.email} ({user.display_name})")
                flash("Logged in successfully!", "success")
                return redirect(url_for("guest.index", squad=user.display_name))

            # If the password is incorrect, show an error message
            logger.warning(f"Failed login attempt - incorrect password: {email}")
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))
        except Exception as e:
            logger.error(f"Exception in login route: {e}")
            flash("An error occurred during login. Please try again.", "error")
            return redirect(url_for("auth.login"))

    return render_template("login.html", logo_img="images/logos/me.svg")


# Set password route (for first-time users AND reset password)
@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    if request.method == "POST":
        email = request.form["email"]
        new_password = request.form["password"]

        # Find the user by email
        with get_session() as session:
            stmt = select(Users).where(Users.email == email)
            user = session.execute(stmt).scalars().first()
        if user is None:
            logger.warning(f"Password set attempt for invalid email: {email}")
            flash("Invalid email", "error")
            return redirect(url_for("auth.set_password"))
        elif user.password:
            logger.warning(
                f"Password set attempt for user with existing password: {email}"
            )
            flash("Password already set. Please log in.", "info")
            return redirect(url_for("auth.login"))

        try:
            user.set_password(new_password)
            with get_session() as session:
                session.add(user)
                session.commit()
            logger.info(f"Password set successfully for user: {email}")
            flash("Password set successfully. Please log in now.", "success")
        except Exception as e:
            logger.error(f"Error setting password for user {email}: {e}")
            flash("An error occurred setting your password. Please try again.", "error")
        return redirect(url_for("auth.login"))

    return render_template("set_password.html")


@bp.route("/logout")
def logout():
    # Clear session variables related to admin mode
    session.pop("admin", None)
    session.pop("admin_last_active", None)

    # Log the user out completely
    user_email = current_user.email if current_user.is_authenticated else "unknown"
    logout_user()
    logger.info(f"User logged out: {user_email}")
    flash("Logged out successfully!", "success")
    return redirect(url_for("auth.login"))
