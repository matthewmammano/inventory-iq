"""Template and form helpers for expiration-date inventory entry."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.inventory.constants import OperationType
from app.inventory.expiration_service import ExpirationAllocation, effective_expiration_notice_days, known_expiration_options
from app.inventory.models import InventoryExpirationBalance, InventoryStorageBalance, Item
from app.shared.clock import utc_now_naive
from app.shared.validators import parse_non_negative_int

MAX_NEW_EXPIRATION_ROWS = 10


@dataclass(frozen=True, slots=True)
class ExpirationEntrySpec:
    key: str
    item_id: int
    storage_id: int
    operation_type: OperationType
    quantity: int
    prefill_known: bool = False

    @property
    def allows_new_dates(self) -> bool:
        return self.operation_type in (OperationType.COUNT, OperationType.RESTOCK)

    @property
    def allows_other(self) -> bool:
        return True

    @property
    def new_date_row_count(self) -> int:
        if not self.allows_new_dates or self.quantity <= 0:
            return 0
        return max(1, min(self.quantity, MAX_NEW_EXPIRATION_ROWS))


@dataclass(frozen=True, slots=True)
class ExpirationOption:
    expires_on: date
    quantity: int
    suggested: bool
    default_quantity: int = 0


@dataclass(frozen=True, slots=True)
class ExpirationEntryGroup:
    spec: ExpirationEntrySpec
    item: Item
    storage: Storage
    options: list[ExpirationOption]

    @property
    def requires_entry(self) -> bool:
        return self.item.expiration_tracking_enabled and (self.spec.quantity > 0 or self.spec.prefill_known)


@dataclass(frozen=True, slots=True)
class ExpirationItemEntryGroup:
    item: Item
    groups: list[ExpirationEntryGroup]

    @property
    def storage_count(self) -> int:
        return len(self.groups)

    @property
    def total_quantity(self) -> int:
        return sum(group.spec.quantity for group in self.groups)


@dataclass(frozen=True, slots=True)
class ExpirationBreakdown:
    soonest_date: date | None
    expired_count: int = 0
    expiring_soon_count: int = 0
    good_count: int = 0
    missing_count: int = 0

    @property
    def soonest_label(self) -> str:
        return self.soonest_date.isoformat() if self.soonest_date else "NA"

    @property
    def soonest_sort_value(self) -> str:
        return self.soonest_date.isoformat() if self.soonest_date else "9999-12-31"

    @property
    def known_count(self) -> int:
        return self.expired_count + self.expiring_soon_count + self.good_count


def scan_expiration_spec(
    *,
    operation_type: OperationType,
    item_id: int,
    quantity: int,
    from_storage_id: int | None,
    to_storage_id: int | None,
) -> ExpirationEntrySpec | None:
    storage_id = from_storage_id if operation_type in (OperationType.TAKEOUT, OperationType.TRANSFER) else to_storage_id
    if storage_id is None or quantity <= 0:
        return None
    return ExpirationEntrySpec(
        key=f"scan_{operation_type.value}_{item_id}_{storage_id}",
        item_id=item_id,
        storage_id=storage_id,
        operation_type=operation_type,
        quantity=quantity,
    )


def bulk_expiration_specs(
    *,
    counts: Mapping[tuple[int, int], int],
    restocks: Mapping[tuple[int, int], int],
) -> list[ExpirationEntrySpec]:
    specs = [
        ExpirationEntrySpec(f"count_{item_id}_{storage_id}", item_id, storage_id, OperationType.COUNT, quantity)
        for (item_id, storage_id), quantity in counts.items()
        if quantity > 0
    ]
    specs.extend(
        ExpirationEntrySpec(f"restock_{item_id}_{storage_id}", item_id, storage_id, OperationType.RESTOCK, quantity)
        for (item_id, storage_id), quantity in restocks.items()
        if quantity > 0
    )
    return specs


def expiration_count_correction_specs(session: Session, agency_id: int) -> list[ExpirationEntrySpec]:
    expiration_totals = (
        select(
            InventoryExpirationBalance.item_id.label("item_id"),
            InventoryExpirationBalance.storage_id.label("storage_id"),
            func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0).label("expiration_quantity"),
        )
        .where(InventoryExpirationBalance.agency_id == agency_id)
        .group_by(InventoryExpirationBalance.item_id, InventoryExpirationBalance.storage_id)
        .subquery()
    )
    rows = session.execute(
        select(InventoryStorageBalance.item_id, InventoryStorageBalance.storage_id, InventoryStorageBalance.quantity)
        .join(Item, Item.id == InventoryStorageBalance.item_id)
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .outerjoin(
            expiration_totals,
            (expiration_totals.c.item_id == InventoryStorageBalance.item_id) & (expiration_totals.c.storage_id == InventoryStorageBalance.storage_id),
        )
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            Item.active.is_(True),
            Item.expiration_tracking_enabled.is_(True),
            InventoryStorageBalance.quantity != func.coalesce(expiration_totals.c.expiration_quantity, 0),
        )
        .order_by(Location.name, Storage.name, Item.name)
    ).all()
    return [
        ExpirationEntrySpec(
            f"expiration_count_{item_id}_{storage_id}",
            item_id,
            storage_id,
            OperationType.COUNT,
            int(quantity),
            prefill_known=True,
        )
        for item_id, storage_id, quantity in rows
    ]


def build_expiration_entry_groups(
    session: Session,
    agency_id: int,
    specs: Sequence[ExpirationEntrySpec],
) -> list[ExpirationEntryGroup]:
    if not specs:
        return []
    items = _items_by_id(session, agency_id, {spec.item_id for spec in specs})
    storages = _storages_by_id(session, agency_id, {spec.storage_id for spec in specs})
    return [
        ExpirationEntryGroup(
            spec=spec,
            item=items[spec.item_id],
            storage=storages[spec.storage_id],
            options=_expiration_options(session, agency_id, spec),
        )
        for spec in specs
        if spec.item_id in items and spec.storage_id in storages and _requires_expiration_entry(items[spec.item_id], spec)
    ]


def group_expiration_entries_by_item(groups: Sequence[ExpirationEntryGroup]) -> list[ExpirationItemEntryGroup]:
    grouped: dict[int, list[ExpirationEntryGroup]] = {}
    items: dict[int, Item] = {}
    for group in sorted(groups, key=lambda entry: (entry.item.name.lower(), entry.item.id, entry.storage.history_name.lower())):
        items[group.item.id] = group.item
        grouped.setdefault(group.item.id, []).append(group)
    return [ExpirationItemEntryGroup(items[item_id], item_groups) for item_id, item_groups in grouped.items()]


def parse_expiration_allocations(
    form: Any,
    groups: Sequence[ExpirationEntryGroup],
) -> dict[str, list[ExpirationAllocation]]:
    allocations_by_key: dict[str, list[ExpirationAllocation]] = {}
    for group in groups:
        allocations = _parse_group_allocations(form, group)
        total = sum(allocation.quantity for allocation in allocations)
        if total != group.spec.quantity:
            raise ValueError(f"Enter expiration quantities for all {group.spec.quantity} {group.item.name}.")
        allocations_by_key[group.spec.key] = allocations
    return allocations_by_key


def hidden_form_fields(form: Any, *, skip_prefixes: Sequence[str] = ("exp_",)) -> list[tuple[str, str]]:
    return [
        (key, value)
        for key in form
        for value in form.getlist(key)
        if key != "expiration_confirmed" and not any(key.startswith(prefix) for prefix in skip_prefixes)
    ]


def expired_quantity_by_item(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    item_ids: Sequence[int],
) -> dict[int, int]:
    """Sum of tracked expiration-balance quantity already past its expiration date, per item, at one location."""
    if not item_ids:
        return {}
    today = utc_now_naive().date()
    rows = session.execute(
        select(
            InventoryExpirationBalance.item_id,
            func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0),
        )
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .where(
            InventoryExpirationBalance.agency_id == agency_id,
            InventoryExpirationBalance.item_id.in_(item_ids),
            Storage.location_id == agency_location_id,
            InventoryExpirationBalance.expires_on < today,
        )
        .group_by(InventoryExpirationBalance.item_id)
    ).all()
    return {item_id: int(quantity or 0) for item_id, quantity in rows}


def expiration_breakdowns_by_item(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> dict[int, ExpirationBreakdown]:
    agency = session.get(Agency, agency_id)
    default_notice_days = int(agency.expiration_notice_days or 0) if agency else 0
    today = utc_now_naive().date()
    tracked_items = _tracked_items_by_id(session, agency_id)
    storage_totals = _storage_totals_by_item(session, agency_id, agency_location_id)
    expiration_rows = session.execute(
        select(
            InventoryExpirationBalance.item_id,
            InventoryExpirationBalance.expires_on,
            func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0),
        )
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .where(
            InventoryExpirationBalance.agency_id == agency_id,
            Storage.location_id == agency_location_id,
            InventoryExpirationBalance.quantity > 0,
        )
        .group_by(InventoryExpirationBalance.item_id, InventoryExpirationBalance.expires_on)
    ).all()
    grouped_rows: dict[int, list[tuple[date, int]]] = {}
    for item_id, expires_on, quantity in expiration_rows:
        if item_id in tracked_items:
            grouped_rows.setdefault(item_id, []).append((expires_on, int(quantity or 0)))

    return {
        item_id: _expiration_breakdown(
            rows=grouped_rows.get(item_id, []),
            total_quantity=storage_totals.get(item_id, 0),
            today=today,
            notice_days=effective_expiration_notice_days(item, default_notice_days),
        )
        for item_id, item in tracked_items.items()
    }


def action_expiration_summary(lines: Sequence[Any]) -> str:
    if not lines:
        return ""
    sorted_lines = sorted(lines, key=lambda line: (line.expires_on is None, line.expires_on or date.max))
    return ", ".join(f"{line.expires_on.isoformat() if line.expires_on else 'Other'} x{line.quantity}" for line in sorted_lines if line.quantity)


def _parse_group_allocations(form: Any, group: ExpirationEntryGroup) -> list[ExpirationAllocation]:
    key = group.spec.key
    allocations: list[ExpirationAllocation] = []
    for option in group.options:
        quantity = _quantity(form.get(f"exp_known_{key}_{option.expires_on.isoformat()}"))
        if quantity:
            allocations.append(ExpirationAllocation(option.expires_on, quantity))
    if group.spec.allows_new_dates:
        for index in _new_date_indexes(form, key, group.spec.new_date_row_count):
            expires_on = _date_value(form.get(f"exp_new_date_{key}_{index}"))
            quantity = _quantity(form.get(f"exp_new_qty_{key}_{index}"))
            if expires_on and quantity:
                allocations.append(ExpirationAllocation(expires_on, quantity))
            elif expires_on or quantity:
                raise ValueError(f"Enter both date and quantity for {group.item.name}.")
    if group.spec.allows_other:
        other_quantity = _quantity(form.get(f"exp_other_{key}"))
        if other_quantity:
            allocations.append(ExpirationAllocation(None, other_quantity))
    return allocations


def _new_date_indexes(form: Any, key: str, max_index_count: int) -> list[int]:
    prefixes = (f"exp_new_date_{key}_", f"exp_new_qty_{key}_")
    indexes: set[int] = set()
    for field_name in form:
        for prefix in prefixes:
            if field_name.startswith(prefix) and field_name.removeprefix(prefix).isdigit():
                index = int(field_name.removeprefix(prefix))
                if index >= max_index_count:
                    raise ValueError("Too many expiration date rows entered.")
                indexes.add(index)
    return sorted(indexes)


def _requires_expiration_entry(item: Item, spec: ExpirationEntrySpec) -> bool:
    return item.expiration_tracking_enabled and (spec.quantity > 0 or spec.prefill_known)


def _expiration_options(session: Session, agency_id: int, spec: ExpirationEntrySpec) -> list[ExpirationOption]:
    if spec.operation_type == OperationType.RESTOCK:
        # A restock is a delivery: only new dates for the incoming quantity apply, never reallocating existing lots.
        return []
    balances = known_expiration_options(session, agency_id, spec.item_id, spec.storage_id)
    return [
        ExpirationOption(
            expires_on=balance.expires_on,
            quantity=balance.quantity,
            suggested=spec.operation_type in (OperationType.TAKEOUT, OperationType.TRANSFER) and index == 0,
            default_quantity=balance.quantity if spec.prefill_known else 0,
        )
        for index, balance in enumerate(balances)
    ]


def _items_by_id(session: Session, agency_id: int, item_ids: set[int]) -> dict[int, Item]:
    if not item_ids:
        return {}
    return {
        item.id: item
        for item in session.execute(select(Item).where(Item.agency_id == agency_id, Item.id.in_(item_ids), Item.active.is_(True))).scalars()
    }


def _storages_by_id(session: Session, agency_id: int, storage_ids: set[int]) -> dict[int, Storage]:
    if not storage_ids:
        return {}
    return {
        storage.id: storage
        for storage in session.execute(select(Storage).where(Storage.agency_id == agency_id, Storage.id.in_(storage_ids))).scalars()
    }


def _tracked_items_by_id(session: Session, agency_id: int) -> dict[int, Item]:
    return {
        item.id: item
        for item in session.execute(
            select(Item).where(
                Item.agency_id == agency_id,
                Item.active.is_(True),
                Item.expiration_tracking_enabled.is_(True),
            )
        ).scalars()
    }


def _storage_totals_by_item(session: Session, agency_id: int, agency_location_id: int) -> dict[int, int]:
    rows = session.execute(
        select(
            InventoryStorageBalance.item_id,
            func.coalesce(func.sum(InventoryStorageBalance.quantity), 0),
        )
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            Storage.location_id == agency_location_id,
        )
        .group_by(InventoryStorageBalance.item_id)
    ).all()
    return {item_id: int(quantity or 0) for item_id, quantity in rows}


def _expiration_breakdown(
    *,
    rows: Sequence[tuple[date, int]],
    total_quantity: int,
    today: date,
    notice_days: int,
) -> ExpirationBreakdown:
    expired_count = expiring_soon_count = good_count = 0
    soonest_date = min((expires_on for expires_on, quantity in rows if quantity > 0), default=None)
    warning_date = today + timedelta(days=notice_days)
    for expires_on, quantity in rows:
        if expires_on < today:
            expired_count += quantity
        elif expires_on <= warning_date:
            expiring_soon_count += quantity
        else:
            good_count += quantity
    known_count = expired_count + expiring_soon_count + good_count
    return ExpirationBreakdown(
        soonest_date=soonest_date,
        expired_count=expired_count,
        expiring_soon_count=expiring_soon_count,
        good_count=good_count,
        missing_count=max(total_quantity - known_count, 0),
    )


def _quantity(value: str | None) -> int:
    if value in (None, ""):
        return 0
    parsed = parse_non_negative_int(value)
    if parsed is None:
        raise ValueError("Expiration quantities must be 0 or higher.")
    return parsed


def _date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Enter expiration dates as YYYY-MM-DD.") from exc
