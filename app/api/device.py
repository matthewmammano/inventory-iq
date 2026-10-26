"""JSON endpoints for the location this kiosk is bound to."""

from http import HTTPStatus

from apiflask import HTTPError
from flask import make_response
from loguru import logger

from app.api.blueprint import api_bp
from app.api.schema import DeviceLocationRequest
from app.auth.device_locations import current_device_token, request_device_location_id, save_device_location, set_device_cookie
from app.auth.response import DeviceLocationResponse
from app.shared.database import get_session

DEVICE_ROUTE = "/agencies/<int:agency_id>/device/location"
UNKNOWN_LOCATION_MESSAGE = "That location is not one of this agency's."


@api_bp.get(DEVICE_ROUTE)
@api_bp.output(DeviceLocationResponse)
@api_bp.doc(summary="Read the location this device is bound to")
def read_device_location(agency_id: int) -> DeviceLocationResponse:
    return DeviceLocationResponse(location_id=request_device_location_id(agency_id))


@api_bp.put(DEVICE_ROUTE)
@api_bp.input(DeviceLocationRequest)
@api_bp.output(DeviceLocationResponse)
@api_bp.doc(summary="Bind this device to one location for a year")
def bind_device_location(agency_id: int, json_data: DeviceLocationRequest):
    token = current_device_token()
    with get_session() as session:
        try:
            save_device_location(agency_id, token, json_data.location_id, session)
        except ValueError as error:
            logger.info("Device location rejected: unknown location", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.NOT_FOUND, UNKNOWN_LOCATION_MESSAGE) from error
        session.commit()
    logger.info("Device bound to a location", extra={"agency_id": agency_id, "agency_location_id": json_data.location_id})
    response = make_response(DeviceLocationResponse(location_id=json_data.location_id).model_dump())
    set_device_cookie(response, token)
    return response
