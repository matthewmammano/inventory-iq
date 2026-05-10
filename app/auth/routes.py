"""Auth routes: login, logout, set-password."""

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from loguru import logger

from app.shared.database import get_session

from . import bp
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
            logger.info("Login requires password setup", extra={"agency_id": agency.id})
            flash("Please set your password first.", "info")
            return redirect(url_for("auth.set_password"))

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
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        new_password = request.form.get("password", "").strip()
        if len(new_password) < 8:
            logger.warning("Password setup rejected: password too short")
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("auth.set_password"))

        with get_session() as s:
            agency = get_agency_by_email(email, s)

        if agency is None or not agency.active:
            logger.warning("Password setup rejected: invalid or inactive agency")
            flash("Invalid email.", "error")
            return redirect(url_for("auth.set_password"))

        if agency.password:
            logger.info(
                "Password setup skipped: password already set",
                extra={"agency_id": agency.id},
            )
            flash("Password already set. Please log in.", "info")
            return redirect(url_for("auth.login"))

        with get_session() as s:
            s.add(agency)
            agency.set_password(new_password)
            s.commit()

        logger.info("Password set", extra={"agency_id": agency.id})
        flash("Password set successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("set_password.html")


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        with get_session() as s:
            sent = create_password_reset_pin(s, email)
        if not sent:
            flash("Reset PIN email could not be sent. Please try again shortly.", "error")
            return redirect(url_for("auth.forgot_password"))
        flash("If that agency email is active, enter the reset PIN sent to that email.", "info")
        return redirect(url_for("auth.reset_password"))
    return render_template("forgot_password.html")


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pin = request.form.get("pin", "").strip()
        new_password = request.form.get("password", "").strip()
        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("auth.reset_password"))
        with get_session() as s:
            if reset_password_with_pin(s, email, pin, new_password):
                flash("Password reset successfully. Please log in.", "success")
                return redirect(url_for("auth.login"))
        flash("Reset PIN is invalid or expired.", "error")
        return redirect(url_for("auth.reset_password"))
    return render_template("reset_password.html")


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    session.pop("admin_last_active", None)
    agency_id = current_user.id if current_user.is_authenticated else None
    logout_user()
    logger.info("Logout", extra={"agency_id": agency_id})
    flash("Logged out successfully!", "success")
    return redirect(url_for("auth.login"))
