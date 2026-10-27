"""JSON endpoints for the emails an agency sends alerts and summaries to."""

from http import HTTPStatus
from typing import Final

from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_notifications_schema import NotificationRecipientRequest
from app.api.admin_write import deleted, save_admin_row
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.auth.models import NotificationRecipient
from app.auth.queries import list_active_emails, list_top_locations
from app.inventory.admin_edit_service import create_notification, delete_notification, update_notification
from app.inventory.notifications_response import NotificationRecipientListResponse, NotificationRecipientResponse
from app.shared.database import get_session

RECIPIENTS_ROUTE: Final[str] = f"{AGENCY_ROUTE}/admin/notification-recipients"
RECIPIENT_ROUTE: Final[str] = f"{RECIPIENTS_ROUTE}/<int:recipient_id>"


def _location_names(agency_id: int, session: Session) -> dict[int, str]:
    return {location.id: location.name for location in list_top_locations(agency_id, session)}


def _saved(recipient: NotificationRecipient, session: Session) -> NotificationRecipientResponse:
    return NotificationRecipientResponse.of(recipient, _location_names(recipient.agency_id, session))


@api_bp.get(RECIPIENTS_ROUTE)
@api_bp.output(NotificationRecipientListResponse)
@api_bp.doc(summary="List every alert and summary recipient, with the toggle table its previews are drawn from")
@admin_only
def list_admin_notification_recipients(agency_id: int) -> NotificationRecipientListResponse:
    with get_session() as session:
        recipients = list_active_emails(agency_id, session)
        return NotificationRecipientListResponse.of(recipients, _location_names(agency_id, session))


@api_bp.post(RECIPIENTS_ROUTE)
@api_bp.input(NotificationRecipientRequest)
@api_bp.output(NotificationRecipientResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Add one alert and summary recipient")
@admin_only
def add_admin_notification_recipient(agency_id: int, json_data: NotificationRecipientRequest) -> NotificationRecipientResponse:
    return save_admin_row(lambda session: create_notification(session, agency_id, json_data), _saved)


@api_bp.patch(RECIPIENT_ROUTE)
@api_bp.input(NotificationRecipientRequest)
@api_bp.output(NotificationRecipientResponse)
@api_bp.doc(summary="Save one recipient's whole row")
@admin_only
def save_admin_notification_recipient(agency_id: int, recipient_id: int, json_data: NotificationRecipientRequest) -> NotificationRecipientResponse:
    return save_admin_row(lambda session: update_notification(session, agency_id, recipient_id, json_data), _saved)


@api_bp.delete(RECIPIENT_ROUTE)
@api_bp.doc(summary="Stop sending to one recipient")
@admin_only
def remove_admin_notification_recipient(agency_id: int, recipient_id: int) -> tuple[str, int]:
    return save_admin_row(lambda session: delete_notification(session, agency_id, recipient_id), deleted)
