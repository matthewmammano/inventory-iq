"""Structural setup: Agency, Locations, Storages, Items, NotificationRecipients.

Plain ORM construction -- SQLAlchemy @validates fires regardless of insert path,
so this still enforces real field-level validation. Operational history (scans,
counts, restocks, UPC lifecycle) goes through the real service layer instead;
see replay.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

import config as cfg
from app.auth.models import Agency, ItemTag, Location, NotificationPreferenceSetting, NotificationRecipient, Storage
from app.auth.notification_preferences import NotificationPreferenceKey
from app.inventory.models import Item
from profiles import CatalogProfiles

_TAG_COLORS = [
    "#EF4444", "#F97316", "#F59E0B", "#84CC16", "#22C55E", "#14B8A6",
    "#06B6D4", "#3B82F6", "#6366F1", "#8B5CF6", "#A855F7", "#EC4899",
    "#F43F5E", "#78716C", "#0EA5E9", "#10B981",
]

@dataclass(slots=True)
class LocationRig:
    location: Location
    storages: dict[str, Storage]  # name -> Storage
    multiplier: float


@dataclass(slots=True)
class SetupResult:
    agency: Agency
    locations: list[LocationRig]
    items: list[Item]
    items_by_name: dict[str, Item]


def setup_agency(
    session: Session,
    rng: random.Random,
    catalog: CatalogProfiles,
    *,
    reset_display_name: str | None = None,
    locations: list[cfg.LocationSpec] | None = None,
    disabled_features: frozenset[str] = frozenset(),
) -> SetupResult:
    agency = Agency(
        display_name=reset_display_name or cfg.DEFAULT_AGENCY_NAME,
        email=cfg.DEFAULT_AGENCY_EMAIL,
        image=cfg.DEFAULT_AGENCY_IMAGE,
        user_count_allow=True,
        user_restock_allow=False,
    )
    agency.password = generate_password_hash(cfg.DEFAULT_AGENCY_PASSWORD)  # bypasses set_password()'s strength check -- see config.py
    agency.set_pin(cfg.DEFAULT_AGENCY_PIN)
    session.add(agency)
    session.flush()

    locations = [_setup_location(session, agency, spec) for spec in (locations or cfg.DEFAULT_LOCATIONS)]
    items, items_by_name = _setup_items(session, agency, rng, catalog, disabled_features)
    _setup_recipients(session, agency)
    session.flush()

    return SetupResult(agency=agency, locations=locations, items=items, items_by_name=items_by_name)


def _setup_location(session: Session, agency: Agency, spec: cfg.LocationSpec) -> LocationRig:
    location = Location(agency_id=agency.id, name=spec.name)
    session.add(location)
    session.flush()

    storages = {}
    for name in cfg.STORAGE_NAMES:
        storage = Storage(agency_id=agency.id, location_id=location.id, name=name)
        session.add(storage)
        storages[name] = storage
    session.flush()

    return LocationRig(location=location, storages=storages, multiplier=spec.multiplier)


def _setup_items(
    session: Session, agency: Agency, rng: random.Random, catalog: CatalogProfiles, disabled_features: frozenset[str] = frozenset()
) -> tuple[list[Item], dict[str, Item]]:
    item_catalog = pd.read_csv(cfg.REFERENCE_DIR / "items.csv")
    tag_by_category = _setup_tags(session, agency, sorted(item_catalog["category"].unique()))

    items: list[Item] = []
    items_by_name: dict[str, Item] = {}
    for row in item_catalog.itertuples(index=False):
        profile = catalog.items[row.name]
        item = Item(
            agency_id=agency.id,
            name=row.name,
            active=True,
            image=row.image,
            increments=row.unit_label,
            min_quantity=profile.min_quantity,
            max_quantity=profile.max_quantity,
            batch_size=profile.batch_size,
            restock_delivery_days=profile.restock_delivery_days,
            expiration_tracking_enabled=profile.expiration.tracked and "expiration" not in disabled_features,
            guest_quick_adjust=rng.random() < 0.3,
            prior_daily_usage=profile.takeout.scans_per_day * profile.takeout.qty_mean,
        )
        item.tag_ids = [tag_by_category[row.category].id]
        session.add(item)
        items.append(item)
        items_by_name[row.name] = item
    session.flush()  # triggers the primary-UPC auto-generation listener
    return items, items_by_name


def _setup_tags(session: Session, agency: Agency, categories: list[str]) -> dict[str, ItemTag]:
    tags = {}
    for i, category in enumerate(categories):
        tag = ItemTag(agency_id=agency.id, tag_name=category, color=_TAG_COLORS[i % len(_TAG_COLORS)])
        session.add(tag)
        tags[category] = tag
    session.flush()
    return tags


def _setup_recipients(session: Session, agency: Agency) -> None:
    chief = NotificationRecipient(agency_id=agency.id, email="mattmammano+chief@gmail.com")
    session.add(chief)
    session.add(NotificationRecipient(agency_id=agency.id, email="mattmammano+quartermaster@gmail.com"))
    session.flush()  # need chief.id before attaching preference rows

    # Every preference type defaults per-key (see app/auth/notification_preferences.py
    # DEFAULT_ENABLED_BY_KEY) -- some default OFF (rare takeout, takeout/transfer action,
    # daily summary). Give one recipient an explicit row for every key, all enabled, so
    # there's always one account you can check to see every alert/summary type fire.
    for key in NotificationPreferenceKey:
        session.add(NotificationPreferenceSetting(recipient_id=chief.id, preference_key=key, enabled=True))
