"""Auth routes: login, logout, set-password."""

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from loguru import logger

from app.shared.database import get_session

from . import bp
from .constants import PASSWORD_REQUIREMENTS_MESSAGE
from .models import validate_password_strength
from .password_reset_service import create_password_reset_pin, reset_password_with_pin
from .queries import get_agency_by_email


@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            logger.warning("Login rejected: missing email or password")
            flash("Email and password are required.", "error")
            return redirect(url_for("auth.login"))

        with get_session() as s:
            agency = get_agency_by_email(email, s)

        if agency is None or not agency.active:
            logger.warning("Login rejected: invalid or inactive agency")
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        if not agency.password:
            logger.warning("Login blocked: password has not been set yet", extra={"agency_id": agency.id})
            flash("Please use the emailed PIN flow to set your password.", "info")
            return redirect(url_for("auth.forgot_password", email=email))

        if agency.check_password(password):
            login_user(agency)
            logger.info("Login succeeded", extra={"agency_id": agency.id})
            return redirect(url_for("guest.index", squad=agency.display_name))

        logger.warning("Login rejected: password mismatch", extra={"agency_id": agency.id})
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    return render_template("login.html", logo_img="images/logos/me.svg")


@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    flash("Use the reset PIN flow to set your password.", "info")
    return redirect(url_for("auth.forgot_password"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            logger.warning("Password reset PIN rejected: missing email")
            flash("Email is required.", "error")
            return redirect(url_for("auth.forgot_password"))
        with get_session() as s:
            sent = create_password_reset_pin(s, email)
        if not sent:
            flash("Reset PIN email could not be sent. Please try again shortly.", "error")
            return redirect(url_for("auth.forgot_password", email=email))
        flash("If that agency email is active, enter the reset PIN sent to that email.", "info")
        return redirect(url_for("auth.reset_password", email=email))
    return render_template(
        "forgot_password.html",
        email_value=request.args.get("email", "").strip(),
    )


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pin = request.form.get("pin", "").strip()
        new_password = request.form.get("password", "").strip()
        try:
            validate_password_strength(new_password)
        except ValueError:
            logger.warning("Password reset rejected: weak password")
            flash(PASSWORD_REQUIREMENTS_MESSAGE, "error")
            return redirect(url_for("auth.reset_password", email=email))
        with get_session() as s:
            if reset_password_with_pin(s, email, pin, new_password):
                flash("Password reset successfully. Please log in.", "success")
                return redirect(url_for("auth.login"))
        flash("Reset PIN is invalid or expired.", "error")
        return redirect(url_for("auth.reset_password", email=email))
    return render_template(
        "reset_password.html",
        email_value=request.args.get("email", "").strip(),
    )


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    session.pop("admin_last_active", None)
    agency_id = current_user.id if current_user.is_authenticated else None
    logout_user()
    logger.info("User logged out", extra={"agency_id": agency_id})
    flash("Logged out successfully!", "success")
    return redirect(url_for("auth.login"))
