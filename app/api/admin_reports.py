"""JSON endpoints for stock levels, restock, history, and the item trend chart."""

from dataclasses import replace
from http import HTTPStatus

from apiflask import HTTPError
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_reports_schema import HistoryEmailRequest, HistoryPageQuery, ReportEmailRequest, ReportLocationQuery
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.auth.device_locations import request_device_location_id
from app.auth.models import Location
from app.auth.queries import list_top_locations
from app.inventory.constants import INVALID_FORM_DATA_MESSAGE
from app.inventory.count_page_service import build_inventory_count_page, select_history_location, select_report_location
from app.inventory.history_service import (
    HISTORY_PAGE_SIZE,
    HistoryLogQuery,
    count_history_logs,
    list_history_logs,
    normalize_history_sort_key,
)
from app.inventory.item_queries import get_agency_item
from app.inventory.report_email_service import (
    EmailDeliveryResult,
    HistoryReportRange,
    ReportEmailOutcome,
    send_history_report,
    send_inventory_count_report,
    send_restock_report,
)
from app.inventory.reports_response import (
    HistoryReportResponse,
    ReportEmailResultResponse,
    RestockReportResponse,
    StockLevelsReportResponse,
)
from app.inventory.restock_page_service import cached_restock_page_rows
from app.inventory.schema import HistoryDateRange
from app.prediction.history_service import build_item_trend_chart
from app.prediction.schema import ItemTrendChartResponse
from app.shared.database import get_session
from app.shared.pagination import PageWindow
from app.shared.validators import first_validation_error_message

REPORTS_ROUTE = f"{AGENCY_ROUTE}/reports"
STOCK_LEVELS_ROUTE = f"{REPORTS_ROUTE}/stock-levels"
RESTOCK_ROUTE = f"{REPORTS_ROUTE}/restock"
HISTORY_ROUTE = f"{REPORTS_ROUTE}/history"
TREND_ROUTE = f"{AGENCY_ROUTE}/items/<int:item_id>/locations/<int:agency_location_id>/trend"

NO_LOCATIONS_MESSAGE = "Add a location before reading this report."
NO_RECIPIENTS_MESSAGE = "Select at least one email recipient."
RESTOCK_UNAVAILABLE_MESSAGE = "Restock analysis could not load. Try again."
TREND_NOT_FOUND_MESSAGE = "Item or location not found."


def _report_location(agency_id: int, requested_id: int | None, session: Session) -> Location | None:
    return select_report_location(
        list_top_locations(agency_id, session),
        requested_id,
        device_location_id=request_device_location_id(agency_id),
    )


def _history_location(agency_id: int, requested_id: int | None, session: Session) -> Location | None:
    return select_history_location(
        list_top_locations(agency_id, session),
        requested_id,
        device_location_id=request_device_location_id(agency_id),
    )


def _email_result(result: EmailDeliveryResult, *, agency_id: int, log_name: str) -> ReportEmailResultResponse:
    """Judge one report email the way v1 does, then answer with its counts."""
    match result.outcome:
        case ReportEmailOutcome.NO_RECIPIENTS:
            logger.info(f"{log_name} request rejected: no recipients matched", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, NO_RECIPIENTS_MESSAGE)
        case ReportEmailOutcome.PARTIAL:
            logger.error(f"{log_name} partially failed", extra={"agency_id": agency_id, "sent": result.sent, "recipient_count": result.total})
        case ReportEmailOutcome.SENT:
            logger.info(f"{log_name} sent successfully", extra={"agency_id": agency_id, "recipient_count": result.sent})
    return ReportEmailResultResponse.of(result)


@api_bp.get(STOCK_LEVELS_ROUTE)
@api_bp.input(ReportLocationQuery, location="query")
@api_bp.output(StockLevelsReportResponse)
@api_bp.doc(summary="Read what every item holds right now in one location")
@admin_only
def read_stock_levels_report(agency_id: int, query_data: ReportLocationQuery) -> StockLevelsReportResponse:
    with get_session() as session:
        location = _report_location(agency_id, query_data.location_id, session)
        if location is None:
            raise HTTPError(HTTPStatus.NOT_FOUND, NO_LOCATIONS_MESSAGE)
        page = build_inventory_count_page(session, agency_id, location.id)
        return StockLevelsReportResponse.of(location, page, current_user.expiration_notice_days)


@api_bp.post(f"{STOCK_LEVELS_ROUTE}/email")
@api_bp.input(ReportEmailRequest)
@api_bp.output(ReportEmailResultResponse)
@api_bp.doc(summary="Email the stock levels report to the chosen recipients")
@admin_only
def email_stock_levels_report(agency_id: int, json_data: ReportEmailRequest) -> ReportEmailResultResponse:
    with get_session() as session:
        result = send_inventory_count_report(session, agency_id, json_data.notification_recipient_ids)
    return _email_result(result, agency_id=agency_id, log_name="Inventory report email")


@api_bp.get(RESTOCK_ROUTE)
@api_bp.input(ReportLocationQuery, location="query")
@api_bp.output(RestockReportResponse)
@api_bp.doc(summary="Read what one location should reorder")
@admin_only
def read_restock_report(agency_id: int, query_data: ReportLocationQuery) -> RestockReportResponse:
    with get_session() as session:
        location = _report_location(agency_id, query_data.location_id, session)
        if location is None:
            raise HTTPError(HTTPStatus.NOT_FOUND, NO_LOCATIONS_MESSAGE)
        try:
            rows = cached_restock_page_rows(session, agency_id, location.id)
        except Exception as error:
            logger.exception("Restock report failed to load", extra={"agency_id": agency_id, "location_id": location.id})
            raise HTTPError(HTTPStatus.INTERNAL_SERVER_ERROR, RESTOCK_UNAVAILABLE_MESSAGE) from error
        return RestockReportResponse.of(location, rows)


@api_bp.post(f"{RESTOCK_ROUTE}/email")
@api_bp.input(ReportEmailRequest)
@api_bp.output(ReportEmailResultResponse)
@api_bp.doc(summary="Email the restock report to the chosen recipients")
@admin_only
def email_restock_report(agency_id: int, json_data: ReportEmailRequest) -> ReportEmailResultResponse:
    with get_session() as session:
        result = send_restock_report(session, agency_id, json_data.notification_recipient_ids, json_data.location_id)
    return _email_result(result, agency_id=agency_id, log_name="Restock report email")


@api_bp.get(HISTORY_ROUTE)
@api_bp.input(HistoryPageQuery, location="query")
@api_bp.output(HistoryReportResponse)
@api_bp.doc(summary="Read one page of action history, newest first")
@admin_only
def read_history_report(agency_id: int, query_data: HistoryPageQuery) -> HistoryReportResponse:
    with get_session() as session:
        location = _history_location(agency_id, query_data.location_id, session)
        location_filter_id = location.id if location else None
        log_query = HistoryLogQuery(
            query_data.page,
            HISTORY_PAGE_SIZE,
            sort_key=normalize_history_sort_key(query_data.sort),
            descending=query_data.descending,
        )
        window = PageWindow(log_query.page, count_history_logs(session, agency_id, location_filter_id, log_query), HISTORY_PAGE_SIZE)
        log_query = replace(log_query, page=window.current_page)
        logs = list_history_logs(session, agency_id, location_filter_id, log_query)
        return HistoryReportResponse.of(location, window, sort_key=log_query.sort_key, descending=log_query.descending, logs=logs)


@api_bp.post(f"{HISTORY_ROUTE}/email")
@api_bp.input(HistoryEmailRequest)
@api_bp.output(ReportEmailResultResponse)
@api_bp.doc(summary="Email the history report for one date range to the chosen recipients")
@admin_only
def email_history_report(agency_id: int, json_data: HistoryEmailRequest) -> ReportEmailResultResponse:
    date_range = _history_date_range(agency_id, json_data)
    with get_session() as session:
        result = send_history_report(
            session,
            agency_id,
            json_data.notification_recipient_ids,
            json_data.location_id,
            HistoryReportRange(date_range.start_utc, date_range.end_utc, date_range.start_label, date_range.end_label),
        )
    return _email_result(result, agency_id=agency_id, log_name="History report email")


def _history_date_range(agency_id: int, request_data: HistoryEmailRequest) -> HistoryDateRange:
    try:
        return HistoryDateRange(
            timezone=current_user.timezone,
            start_date=request_data.start_date,
            end_date=request_data.end_date,
        )
    except ValidationError as error:
        logger.info("History email date range rejected", extra={"agency_id": agency_id, "location_id": request_data.location_id})
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, first_validation_error_message(error, INVALID_FORM_DATA_MESSAGE)) from error


@api_bp.get(TREND_ROUTE)
@api_bp.output(ItemTrendChartResponse)
@api_bp.doc(summary="Read one item's count, operation, and trendline series in one location")
@admin_only
def read_item_trend_chart(agency_id: int, item_id: int, agency_location_id: int) -> ItemTrendChartResponse:
    with get_session() as session:
        item = get_agency_item(agency_id, item_id, include_inactive=True, session=session)
        location = next((known for known in list_top_locations(agency_id, session) if known.id == agency_location_id), None)
        if item is None or location is None:
            logger.info(
                "Item trend chart rejected: item or location not found",
                extra={"agency_id": agency_id, "item_id": item_id, "location_id": agency_location_id},
            )
            raise HTTPError(HTTPStatus.NOT_FOUND, TREND_NOT_FOUND_MESSAGE)
        return build_item_trend_chart(session, agency_id, item, location)
