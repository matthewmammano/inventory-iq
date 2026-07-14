"""Auth routes: login, logout, and password reset."""

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from loguru import logger
from pydantic import ValidationError

from app.shared.database import get_session
from app.shared.email_addresses import email_domain
from app.shared.rate_limit import AUTH_ATTEMPT_LIMITS, limiter

from . import bp
from .password_reset_service import create_password_reset_pin, reset_password_with_pin
from .queries import get_agency_by_email
from .schema import ForgotPasswordRequest, LoginRequest, ResetPasswordRequest

PASSWORD_REQUIRED_MESSAGE = "Password is required."  # nosec B105 - user-facing validation copy, not a credential


@bp.route("/", methods=["GET", "POST"])
@limiter.limit("; ".join(AUTH_ATTEMPT_LIMITS), methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        try:
            login_request = LoginRequest.model_validate({"email": email, "password": password})
        except ValidationError as exc:
            field_errors = _field_errors(exc, {"email": "Enter a valid email address.", "password": PASSWORD_REQUIRED_MESSAGE})
            logger.info("Login form rejected by field validation", extra={"field_count": len(field_errors), "email_domain": email_domain(email)})
            return _render_login(email, field_errors), 400

        with get_session() as s:
            agency = get_agency_by_email(login_request.email, s)

        if agency is None or not agency.active:
            logger.warning("Login rejected: invalid or inactive agency", extra={"email_domain": email_domain(email)})
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        if not agency.password:
            logger.info("Login redirected: password has not been set", extra={"agency_id": agency.id})
            flash("Use the emailed PIN to set your password.", "info")
            return redirect(url_for("auth.forgot_password", email=login_request.email))

        if agency.check_password(login_request.password):
            login_user(agency)
            logger.info("User login succeeded for agency account", extra={"agency_id": agency.id})
            return redirect(url_for("guest.index", agency_id=agency.id))

        logger.warning("Login rejected: password mismatch", extra={"agency_id": agency.id})
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))

    return _render_login()


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("; ".join(AUTH_ATTEMPT_LIMITS), methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        try:
            reset_request = ForgotPasswordRequest.model_validate({"email": email})
        except ValidationError as exc:
            field_errors = _field_errors(exc, {"email": "Enter a valid email address."})
            logger.info("Password reset request rejected by field validation", extra={"email_domain": email_domain(email)})
            return _render_forgot_password(email, field_errors), 400
        with get_session() as s:
            sent = create_password_reset_pin(s, reset_request.email)
        if not sent:
            flash("Reset PIN email could not be sent. Try again shortly.", "error")
            return redirect(url_for("auth.forgot_password", email=reset_request.email))
        flash("If that agency email is active, enter the reset PIN sent to that email.", "info")
        return redirect(url_for("auth.reset_password", email=reset_request.email))
    return _render_forgot_password(request.args.get("email", "").strip())


@bp.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("; ".join(AUTH_ATTEMPT_LIMITS), methods=["POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pin = request.form.get("pin", "").strip()
        new_password = request.form.get("password", "").strip()
        try:
            reset_request = ResetPasswordRequest.model_validate({"email": email, "pin": pin, "password": new_password})
        except ValidationError as exc:
            field_errors = _field_errors(
                exc,
                {
                    "email": "Enter a valid email address.",
                    "pin": "PIN must be exactly 6 digits.",
                },
            )
            logger.info(
                "Password reset form rejected by field validation",
                extra={"field_count": len(field_errors), "email_domain": email_domain(email)},
            )
            return _render_reset_password(email, field_errors, pin_value=pin), 400
        with get_session() as s:
            if reset_password_with_pin(s, reset_request.email, reset_request.pin, reset_request.password):
                flash("Password reset. Please log in.", "success")
                return redirect(url_for("auth.login"))
        flash("Reset PIN is invalid or expired.", "error")
        return redirect(url_for("auth.reset_password", email=reset_request.email))
    return _render_reset_password(request.args.get("email", "").strip())


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    session.pop("admin_last_active", None)
    agency_id = current_user.id if current_user.is_authenticated else None
    logout_user()
    logger.info("User logout completed", extra={"agency_id": agency_id})
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


def _field_errors(exc: ValidationError, messages: dict[str, str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        field = str(error["loc"][0])
        errors[field] = messages.get(field) or str((error.get("ctx") or {}).get("error") or error["msg"])
    return errors
