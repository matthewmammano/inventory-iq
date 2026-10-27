"""JSON endpoints for items, tags, and notification recipients."""

from collections.abc import Callable
from http import HTTPStatus
from typing import Final

from apiflask import HTTPError
from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_items_schema import ItemRequest, NotificationRecipientRequest, TagRequest
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.auth.queries import list_active_emails, list_tags
from app.inventory.admin_edit_service import (
    AdminRowNotFoundError,
    create_item,
    create_notification,
    create_tag,
    delete_item,
    delete_notification,
    delete_tag,
    update_item,
    update_notification,
    update_tag,
)
from app.inventory.admin_items_response import (
    AdminItemListResponse,
    AdminItemResponse,
    NotificationRecipientListResponse,
    NotificationRecipientResponse,
    TagListResponse,
    TagResponse,
)
from app.inventory.item_queries import list_items
from app.shared.database import get_session

ADMIN_DATA_ROUTE: Final[str] = f"{AGENCY_ROUTE}/admin"
ITEMS_ROUTE: Final[str] = f"{ADMIN_DATA_ROUTE}/items"
ITEM_ROUTE: Final[str] = f"{ITEMS_ROUTE}/<int:item_id>"
TAGS_ROUTE: Final[str] = f"{ADMIN_DATA_ROUTE}/tags"
TAG_ROUTE: Final[str] = f"{TAGS_ROUTE}/<int:tag_id>"
RECIPIENTS_ROUTE: Final[str] = f"{ADMIN_DATA_ROUTE}/notification-recipients"
RECIPIENT_ROUTE: Final[str] = f"{RECIPIENTS_ROUTE}/<int:recipient_id>"

NO_CONTENT: Final[tuple[str, int]] = ("", HTTPStatus.NO_CONTENT)


def _save_row[Row, Result](action: Callable[[Session], Row], build: Callable[[Row], Result]) -> Result:
    """Run one admin write in its own transaction, turning the service's refusals into JSON status codes."""
    with get_session() as session:
        try:
            row = action(session)
            session.commit()
        except AdminRowNotFoundError as error:
            raise HTTPError(HTTPStatus.NOT_FOUND, str(error)) from error
        except ValueError as error:
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        return build(row)


def _deleted(_row: object) -> tuple[str, int]:
    return NO_CONTENT


@api_bp.get(ITEMS_ROUTE)
@api_bp.output(AdminItemListResponse)
@api_bp.doc(summary="List every active item with the fields its admin editor changes")
@admin_only
def list_admin_items(agency_id: int) -> AdminItemListResponse:
    with get_session() as session:
        return AdminItemListResponse([AdminItemResponse.of(item) for item in list_items(agency_id, session=session)])


@api_bp.post(ITEMS_ROUTE)
@api_bp.input(ItemRequest)
@api_bp.output(AdminItemResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Add one item")
@admin_only
def add_admin_item(agency_id: int, json_data: ItemRequest) -> AdminItemResponse:
    return _save_row(lambda session: create_item(session, agency_id, json_data), AdminItemResponse.of)


@api_bp.patch(ITEM_ROUTE)
@api_bp.input(ItemRequest)
@api_bp.output(AdminItemResponse)
@api_bp.doc(summary="Save one item's whole row")
@admin_only
def save_admin_item(agency_id: int, item_id: int, json_data: ItemRequest) -> AdminItemResponse:
    return _save_row(lambda session: update_item(session, agency_id, item_id, json_data), AdminItemResponse.of)


@api_bp.delete(ITEM_ROUTE)
@api_bp.doc(summary="Hide one item, keeping its history")
@admin_only
def remove_admin_item(agency_id: int, item_id: int) -> tuple[str, int]:
    return _save_row(lambda session: delete_item(session, agency_id, item_id), _deleted)


@api_bp.get(TAGS_ROUTE)
@api_bp.output(TagListResponse)
@api_bp.doc(summary="List every active item tag")
@admin_only
def list_admin_tags(agency_id: int) -> TagListResponse:
    with get_session() as session:
        return TagListResponse([TagResponse.of(tag) for tag in list_tags(agency_id, session)])


@api_bp.post(TAGS_ROUTE)
@api_bp.input(TagRequest)
@api_bp.output(TagResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Add one item tag, reviving a hidden tag of the same name")
@admin_only
def add_admin_tag(agency_id: int, json_data: TagRequest) -> TagResponse:
    return _save_row(lambda session: create_tag(session, agency_id, json_data), TagResponse.of)


@api_bp.patch(TAG_ROUTE)
@api_bp.input(TagRequest)
@api_bp.output(TagResponse)
@api_bp.doc(summary="Save one tag's name and color")
@admin_only
def save_admin_tag(agency_id: int, tag_id: int, json_data: TagRequest) -> TagResponse:
    return _save_row(lambda session: update_tag(session, agency_id, tag_id, json_data), TagResponse.of)


@api_bp.delete(TAG_ROUTE)
@api_bp.doc(summary="Hide one item tag")
@admin_only
def remove_admin_tag(agency_id: int, tag_id: int) -> tuple[str, int]:
    return _save_row(lambda session: delete_tag(session, agency_id, tag_id), _deleted)


@api_bp.get(RECIPIENTS_ROUTE)
@api_bp.output(NotificationRecipientListResponse)
@api_bp.doc(summary="List every active alert and summary recipient")
@admin_only
def list_admin_notification_recipients(agency_id: int) -> NotificationRecipientListResponse:
    with get_session() as session:
        recipients = list_active_emails(agency_id, session)
        return NotificationRecipientListResponse([NotificationRecipientResponse.of(recipient) for recipient in recipients])


@api_bp.post(RECIPIENTS_ROUTE)
@api_bp.input(NotificationRecipientRequest)
@api_bp.output(NotificationRecipientResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Add one alert and summary recipient")
@admin_only
def add_admin_notification_recipient(agency_id: int, json_data: NotificationRecipientRequest) -> NotificationRecipientResponse:
    return _save_row(lambda session: create_notification(session, agency_id, json_data), NotificationRecipientResponse.of)


@api_bp.patch(RECIPIENT_ROUTE)
@api_bp.input(NotificationRecipientRequest)
@api_bp.output(NotificationRecipientResponse)
@api_bp.doc(summary="Save one recipient's whole row")
@admin_only
def save_admin_notification_recipient(agency_id: int, recipient_id: int, json_data: NotificationRecipientRequest) -> NotificationRecipientResponse:
    return _save_row(lambda session: update_notification(session, agency_id, recipient_id, json_data), NotificationRecipientResponse.of)


@api_bp.delete(RECIPIENT_ROUTE)
@api_bp.doc(summary="Stop sending to one recipient")
@admin_only
def remove_admin_notification_recipient(agency_id: int, recipient_id: int) -> tuple[str, int]:
    return _save_row(lambda session: delete_notification(session, agency_id, recipient_id), _deleted)
