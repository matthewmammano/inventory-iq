"""Auth domain queries — agencies, locations, and tags."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.shared.database import managed_session

from .models import Agency, ItemTag, Location, NotificationRecipient, Storage


@dataclass(frozen=True, slots=True)
class AgencyScanPermissions:
    count: bool
    restock: bool


def get_agency(agency_id: int, session: Session | None = None) -> Agency | None:
    with managed_session(session) as s:
        return s.execute(select(Agency).where(Agency.id == agency_id)).scalars().first()


def get_agency_by_email(email: str, session: Session | None = None) -> Agency | None:
    with managed_session(session) as s:
        return s.execute(select(Agency).where(Agency.email == email)).scalars().first()


def list_agencies(*, active: bool, session: Session | None = None) -> list[Agency]:
    with managed_session(session) as s:
        stmt = select(Agency).where(Agency.active.is_(active)).order_by(Agency.display_name)
        return list(s.execute(stmt).scalars().all())


def get_agency_permissions(agency_id: int, session: Session | None = None) -> AgencyScanPermissions | None:
    """Return guest scan permissions, or None if agency not found."""
    with managed_session(session) as s:
        row = s.execute(select(Agency.user_count_allow, Agency.user_restock_allow).where(Agency.id == agency_id)).first()
        return AgencyScanPermissions(count=bool(row.user_count_allow), restock=bool(row.user_restock_allow)) if row else None


def list_locations(
    agency_id: int,
    *,
    agency_location_id: int | None = None,
    user_access_from: bool | None = None,
    user_access_to: bool | None = None,
    session: Session | None = None,
) -> list[Storage]:
    """Return storages for an agency, optionally filtered by scan-access flags."""
    with managed_session(session) as s:
        stmt = select(Storage).options(selectinload(Storage.location)).where(Storage.agency_id == agency_id)
        if agency_location_id is not None:
            stmt = stmt.where(Storage.location_id == agency_location_id)
        if user_access_from is not None:
            stmt = stmt.where(Storage.user_access_from.is_(user_access_from))
        if user_access_to is not None:
            stmt = stmt.where(Storage.user_access_to.is_(user_access_to))
        stmt = stmt.order_by(Storage.location_id, Storage.name)
        return list(s.execute(stmt).scalars().all())


def get_storage(storage_id: int, agency_id: int, session: Session | None = None) -> Storage | None:
    """Get a storage by ID, validating it belongs to the agency."""
    with managed_session(session) as s:
        return (
            s.execute(
                select(Storage)
                .options(selectinload(Storage.location))
                .where(
                    Storage.id == storage_id,
                    Storage.agency_id == agency_id,
                )
            )
            .scalars()
            .first()
        )


def list_top_locations(agency_id: int, session: Session | None = None) -> list[Location]:
    with managed_session(session) as s:
        stmt = select(Location).where(Location.agency_id == agency_id).order_by(Location.name)
        return list(s.execute(stmt).scalars().all())


def list_active_emails(agency_id: int, session: Session | None = None, *, order_by_id: bool = False) -> list[NotificationRecipient]:
    with managed_session(session) as s:
        order_col = NotificationRecipient.id if order_by_id else NotificationRecipient.email
        stmt = (
            select(NotificationRecipient)
            .options(selectinload(NotificationRecipient.preferences))
            .where(NotificationRecipient.agency_id == agency_id, NotificationRecipient.active.is_(True))
            .order_by(order_col)
        )
        return list(s.execute(stmt).scalars().all())


def list_tags(agency_id: int, session: Session | None = None) -> list[ItemTag]:
    with managed_session(session) as s:
        stmt = select(ItemTag).where(ItemTag.agency_id == agency_id, ItemTag.active.is_(True)).order_by(ItemTag.tag_name)
        return list(s.execute(stmt).scalars().all())


def get_tags_by_ids(agency_id: int, tag_ids: list[int], session: Session | None = None) -> list[ItemTag]:
    with managed_session(session) as s:
        stmt = select(ItemTag).where(
            ItemTag.id.in_(tag_ids),
            ItemTag.agency_id == agency_id,
            ItemTag.active.is_(True),
        )
        return list(s.execute(stmt).scalars().all())
