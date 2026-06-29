"""Auth routes: login, logout, set-password."""

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from loguru import logger

from app.shared.database import get_session
from app.shared.email_addresses import email_domain
from app.shared.validators import (
    password_requirements_error,
    validate_email_format,
    validate_pin_length,
)

from . import bp
from .password_reset_service import create_password_reset_pin, reset_password_with_pin
from .queries import get_agency_by_email


@bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        field_errors, normalized_email = _login_field_errors(email, password)

        if field_errors:
            logger.info("Login form rejected by field validation", extra={"field_count": len(field_errors), "email_domain": email_domain(email)})
            return _render_login(email, field_errors), 400

        with get_session() as s:
            agency = get_agency_by_email(normalized_email, s)

        if agency is None or not agency.active:
            logger.warning("Login rejected: invalid or inactive agency", extra={"email_domain": email_domain(email)})
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        if not agency.password:
            logger.info("Login redirected: password has not been set", extra={"agency_id": agency.id})
            flash("Use the emailed PIN to set your password.", "info")
            return redirect(url_for("auth.forgot_password", email=normalized_email))

        if agency.check_password(password):
            login_user(agency)
            logger.info(
                "User login succeeded for agency account",
                extra={"agency_id": agency.id, "squad": agency.display_name},
            )
            return redirect(url_for("guest.index", squad=agency.display_name))

        logger.warning("Login rejected: password mismatch", extra={"agency_id": agency.id})
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    return _render_login()


@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    flash("Use the reset PIN flow to set your password.", "info")
    return redirect(url_for("auth.forgot_password"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        field_errors, normalized_email = _email_field_errors(email)
        if field_errors:
            logger.info("Password reset request rejected by field validation", extra={"email_domain": email_domain(email)})
            return _render_forgot_password(email, field_errors), 400
        with get_session() as s:
            sent = create_password_reset_pin(s, normalized_email)
        if not sent:
            flash("Reset PIN email could not be sent. Try again shortly.", "error")
            return redirect(url_for("auth.forgot_password", email=normalized_email))
        flash("If that agency email is active, enter the reset PIN sent to that email.", "info")
        return redirect(url_for("auth.reset_password", email=normalized_email))
    return _render_forgot_password(request.args.get("email", "").strip())


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pin = request.form.get("pin", "").strip()
        new_password = request.form.get("password", "").strip()
        field_errors, normalized_email = _reset_password_field_errors(email, pin, new_password)
        if field_errors:
            logger.info(
                "Password reset form rejected by field validation",
                extra={"field_count": len(field_errors), "email_domain": email_domain(email)},
            )
            return _render_reset_password(email, field_errors, pin_value=pin), 400
        with get_session() as s:
            if reset_password_with_pin(s, normalized_email, pin, new_password):
                flash("Password reset. Please log in.", "success")
                return redirect(url_for("auth.login"))
        flash("Reset PIN is invalid or expired.", "error")
        return redirect(url_for("auth.reset_password", email=normalized_email))
    return _render_reset_password(request.args.get("email", "").strip())


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    session.pop("admin_last_active", None)
    agency_id = current_user.id if current_user.is_authenticated else None
    squad = current_user.display_name if current_user.is_authenticated else None
    logout_user()
    logger.info("User logout completed", extra={"agency_id": agency_id, "squad": squad})
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))


def _render_login(email_value: str = "", field_errors: dict[str, str] | None = None):
    return render_template(
        "login.html",
        logo_img="images/logos/me.svg",
        email_value=email_value,
        field_errors=field_errors or {},
    )


def _render_forgot_password(email_value: str = "", field_errors: dict[str, str] | None = None):
    return render_template(
        "forgot_password.html",
        email_value=email_value,
        field_errors=field_errors or {},
    )


def _render_reset_password(email_value: str = "", field_errors: dict[str, str] | None = None, *, pin_value: str = ""):
    return render_template(
        "reset_password.html",
        email_value=email_value,
        pin_value=pin_value,
        field_errors=field_errors or {},
    )


def _login_field_errors(email: str, password: str) -> tuple[dict[str, str], str]:
    errors, normalized_email = _email_field_errors(email)
    if not password:
        errors["password"] = "Password is required."  # nosec B105 - user-facing validation copy
    return errors, normalized_email


def _reset_password_field_errors(email: str, pin: str, password: str) -> tuple[dict[str, str], str]:
    errors, normalized_email = _email_field_errors(email)
    try:
        validate_pin_length(pin, 6)
    except ValueError:
        errors["pin"] = "PIN must be exactly 6 digits."
    if message := password_requirements_error(password):
        errors["password"] = message
    return errors, normalized_email


def _email_field_errors(email: str) -> tuple[dict[str, str], str]:
    try:
        return {}, validate_email_format(email, max_length=128, allow_none=False) or email
    except ValueError:
        return {"email": "Enter a valid email address."}, email
