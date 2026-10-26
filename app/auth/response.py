"""Response models for the signed-in agency and the places it keeps stock."""

from pydantic import BaseModel, ConfigDict, RootModel

from app.shared.image_paths import static_image_url

from .models import Agency, Location, Storage


class LocationResponse(BaseModel):
    """One top-level place an agency keeps stock."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str

    @classmethod
    def of(cls, location: Location) -> "LocationResponse":
        return cls(id=location.id, name=location.name)


class StorageResponse(BaseModel):
    """One storage unit, carrying the location name the kiosk shows beside it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location_id: int
    location_name: str

    @classmethod
    def of(cls, storage: Storage) -> "StorageResponse":
        return cls(
            id=storage.id,
            name=storage.name,
            location_id=storage.location_id,
            location_name=storage.location.name if storage.location else "",
        )


class DeviceLocationResponse(BaseModel):
    """The location this kiosk is bound to; null until someone picks one."""

    location_id: int | None


class LocationListResponse(RootModel[list[LocationResponse]]):
    """Every location an agency keeps stock in."""


class SignedInAgencyResponse(BaseModel):
    """The agency whose session is making the request, as the app shell needs it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    logo_url: str

    @classmethod
    def of(cls, agency: Agency) -> "SignedInAgencyResponse":
        return cls(id=agency.id, display_name=agency.display_name, logo_url=static_image_url(agency.image))
