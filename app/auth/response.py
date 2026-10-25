"""Response models for agency places: locations and the storages inside them."""

from pydantic import BaseModel, ConfigDict, RootModel

from .models import Location, Storage


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


class LocationListResponse(RootModel[list[LocationResponse]]):
    """Every location an agency keeps stock in."""
