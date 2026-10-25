"""Builders for the row graph every inventory test needs."""

from dataclasses import dataclass
from itertools import count
from typing import Final

from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.inventory.models import Item

AGENCY_PIN: Final[str] = "1234"
AGENCY_PASSWORD: Final[str] = "Squad-1234"
ITEM_MIN_QUANTITY: Final[int] = 2
ITEM_MAX_QUANTITY: Final[int] = 10

_agency_counter = count(1)


@dataclass(frozen=True, slots=True)
class AgencyFixture:
    """The agency, its two storages, and one item, all already persisted."""

    agency: Agency
    location: Location
    shelf: Storage
    truck: Storage
    item: Item

    @property
    def id(self) -> int:
        return self.agency.id


def build_agency(session: Session, *, expiration_tracking: bool = False) -> AgencyFixture:
    squad = next(_agency_counter)
    agency = Agency(display_name=f"Squad {squad}", email=f"squad{squad}@example.com", active=True)
    agency.set_pin(AGENCY_PIN)  # the column stores a hash, so it has to go through the model
    agency.set_password(AGENCY_PASSWORD)
    session.add(agency)
    session.flush()

    location = Location(agency_id=agency.id, name="Station")
    session.add(location)
    session.flush()

    shelf = _build_storage(session, agency.id, location.id, "Shelf")
    truck = _build_storage(session, agency.id, location.id, "Truck")
    item = build_item(session, agency.id, expiration_tracking=expiration_tracking)
    session.commit()
    return AgencyFixture(agency=agency, location=location, shelf=shelf, truck=truck, item=item)


def build_item(session: Session, agency_id: int, *, name: str = "Gauze Pads", expiration_tracking: bool = False) -> Item:
    item = Item(
        agency_id=agency_id,
        name=name,  # upc is left unset: a before_flush hook generates a valid agency-unique one
        active=True,
        min_quantity=ITEM_MIN_QUANTITY,
        max_quantity=ITEM_MAX_QUANTITY,
        tag_ids=[],
        expiration_tracking_enabled=expiration_tracking,
    )
    session.add(item)
    session.flush()
    return item


def _build_storage(session: Session, agency_id: int, location_id: int, name: str) -> Storage:
    storage = Storage(agency_id=agency_id, location_id=location_id, name=name, user_access_from=True, user_access_to=True)
    session.add(storage)
    session.flush()
    return storage
