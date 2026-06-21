"""Auth domain queries — agencies, locations, and tags."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.shared.database import managed_session

from .models import Agencies, AgencyItemTags, AgencyLocations, AgencyStorages


def get_agency(agency_id: int, session: Session | None = None) -> Agencies | None:
    with managed_session(session) as s:
        return s.execute(select(Agencies).where(Agencies.id == agency_id)).scalars().first()


def get_agency_by_email(email: str, session: Session | None = None) -> Agencies | None:
    with managed_session(session) as s:
        return s.execute(select(Agencies).where(Agencies.email == email)).scalars().first()


def get_agency_by_display_name(display_name: str, session: Session | None = None) -> Agencies | None:
    with managed_session(session) as s:
        return s.execute(select(Agencies).where(Agencies.display_name == display_name)).scalars().first()


def list_agencies(*, active: bool, session: Session | None = None) -> list[Agencies]:
    with managed_session(session) as s:
        stmt = select(Agencies).where(Agencies.active.is_(active)).order_by(Agencies.display_name)
        return list(s.execute(stmt).scalars().all())


def get_agency_permissions(display_name: str, session: Session | None = None) -> tuple[bool, bool] | None:
    """Return (count_allow, restock_allow) or None if agency not found."""
    with managed_session(session) as s:
        row = s.execute(select(Agencies.user_count_allow, Agencies.user_restock_allow).where(Agencies.display_name == display_name)).first()
        return (row.user_count_allow, row.user_restock_allow) if row else None


def list_locations(
    agency_id: int,
    *,
    agency_location_id: int | None = None,
    user_access_from: bool | None = None,
    user_access_to: bool | None = None,
    session: Session | None = None,
) -> list[AgencyStorages]:
    """Return storages for an agency, optionally filtered by scan-access flags."""
    with managed_session(session) as s:
        stmt = select(AgencyStorages).options(selectinload(AgencyStorages.location)).where(AgencyStorages.agency_id == agency_id)
        if agency_location_id is not None:
            stmt = stmt.where(AgencyStorages.location_id == agency_location_id)
        if user_access_from is not None:
            stmt = stmt.where(AgencyStorages.user_access_from.is_(user_access_from))
        if user_access_to is not None:
            stmt = stmt.where(AgencyStorages.user_access_to.is_(user_access_to))
        stmt = stmt.order_by(AgencyStorages.location_id, AgencyStorages.name)
        return list(s.execute(stmt).scalars().all())


def get_storage(storage_id: int, agency_id: int, session: Session | None = None) -> AgencyStorages | None:
    """Get a storage by ID, validating it belongs to the agency."""
    with managed_session(session) as s:
        return (
            s.execute(
                select(AgencyStorages)
                .options(selectinload(AgencyStorages.location))
                .where(
                    AgencyStorages.id == storage_id,
                    AgencyStorages.agency_id == agency_id,
                )
            )
            .scalars()
            .first()
        )


def list_top_locations(agency_id: int, session: Session | None = None) -> list[AgencyLocations]:
    with managed_session(session) as s:
        stmt = select(AgencyLocations).where(AgencyLocations.agency_id == agency_id).order_by(AgencyLocations.name)
        return list(s.execute(stmt).scalars().all())


def list_tags(agency_id: int, session: Session | None = None) -> list[AgencyItemTags]:
    with managed_session(session) as s:
        stmt = select(AgencyItemTags).where(AgencyItemTags.agency_id == agency_id).order_by(AgencyItemTags.tag_name)
        return list(s.execute(stmt).scalars().all())


def get_tags_by_ids(agency_id: int, tag_ids: list[int], session: Session | None = None) -> list[AgencyItemTags]:
    with managed_session(session) as s:
        stmt = select(AgencyItemTags).where(
            AgencyItemTags.id.in_(tag_ids),
            AgencyItemTags.agency_id == agency_id,
        )
        return list(s.execute(stmt).scalars().all())
