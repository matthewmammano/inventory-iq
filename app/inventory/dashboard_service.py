"""Admin dashboard tiles: one open-alert count per alert type, and the page that clears it."""

from dataclasses import dataclass, replace
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.constants import AlertStatus, AlertType
from app.alerts.models import Alert


class AttentionSeverity(StrEnum):
    """How hard a tile pushes: stock you cannot use, stock heading that way, or a records gap."""

    CRITICAL = "critical"
    WARNING = "warning"
    WATCH = "watch"


class AttentionCounter(StrEnum):
    """What a tile's big number counts, and what the smaller number beside it adds."""

    ITEM_PIECES = "item_pieces"
    ITEM_SPOTS = "item_spots"
    ITEM_LOCATIONS = "item_locations"
    ALERT_ROWS = "alert_rows"


@dataclass(frozen=True, slots=True)
class AttentionTile:
    """One alert type as the dashboard shows it, in plain language for a non-technical admin."""

    title: str
    detail: str
    endpoint: str
    severity: AttentionSeverity
    counter: AttentionCounter
    extra_noun: str = ""
    sort_key: str = ""
    sort_direction: str = "desc"
    count: int = 0
    extra: int = 0

    @property
    def detail_text(self) -> str:
        """The small line, with the secondary count spelled out in its own unit."""
        if not self.extra_noun:
            return self.detail
        return self.detail.format(extra=_pluralize(self.extra, self.extra_noun))


# Insertion order is the dashboard's urgency order: real problems first, predictions after, housekeeping last.
ATTENTION_TILES: dict[AlertType, AttentionTile] = {
    AlertType.STOCKOUT: AttentionTile(
        "Out of Stock",
        "Items with nothing left on the shelf, at {extra}. Order first.",
        "admin.restock",
        AttentionSeverity.CRITICAL,
        AttentionCounter.ITEM_LOCATIONS,
        extra_noun="squad",
        sort_key="total",
        sort_direction="asc",
    ),
    AlertType.EXPIRED_STOCK: AttentionTile(
        "Expired",
        "Items past the expiration date. {extra} to pull off the shelf.",
        "admin.stock_levels",
        AttentionSeverity.CRITICAL,
        AttentionCounter.ITEM_PIECES,
        extra_noun="piece",
        sort_key="expired",
    ),
    AlertType.LOW_STOCK: AttentionTile(
        "Low Stock",
        "Items below the reorder amount you set, at {extra}.",
        "admin.restock",
        AttentionSeverity.WARNING,
        AttentionCounter.ITEM_LOCATIONS,
        extra_noun="squad",
        sort_key="total",
        sort_direction="asc",
    ),
    AlertType.EXPIRING_SOON: AttentionTile(
        "Expiring Soon",
        "Items with a date coming up soon. {extra} in all.",
        "admin.stock_levels",
        AttentionSeverity.WARNING,
        AttentionCounter.ITEM_PIECES,
        extra_noun="piece",
        sort_key="expiring_soon",
    ),
    AlertType.STOCKOUT_FORECAST: AttentionTile(
        "Will Run Out",
        "Items on track to hit zero at {extra}, at the current rate of use.",
        "admin.restock",
        AttentionSeverity.WARNING,
        AttentionCounter.ITEM_LOCATIONS,
        extra_noun="squad",
        sort_key="days_until_stockout",
        sort_direction="asc",
    ),
    AlertType.LOW_STOCK_FORECAST: AttentionTile(
        "Will Run Low",
        "Items on track to drop below the reorder amount at {extra}.",
        "admin.restock",
        AttentionSeverity.WARNING,
        AttentionCounter.ITEM_LOCATIONS,
        extra_noun="squad",
        sort_key="days_until_stockout",
        sort_direction="asc",
    ),
    AlertType.EXPIRATION_COUNT_NEEDED: AttentionTile(
        "Missing Dates",
        "Items needing an expiration date. {extra} to fill in.",
        "admin.pending_expiration_dates",
        AttentionSeverity.WATCH,
        AttentionCounter.ITEM_SPOTS,
        extra_noun="shelf spot",
    ),
    AlertType.UNKNOWN_UPC: AttentionTile(
        "Unknown Barcodes",
        "Someone scanned a barcode no item uses yet.",
        "admin.unknown_barcodes",
        AttentionSeverity.WATCH,
        AttentionCounter.ALERT_ROWS,
    ),
    AlertType.STALE_COUNT: AttentionTile(
        "Not Counted Lately",
        "Items nobody has counted in a while, at {extra}.",
        "admin.stock_levels",
        AttentionSeverity.WATCH,
        AttentionCounter.ITEM_LOCATIONS,
        extra_noun="squad",
    ),
    AlertType.RARE_TAKEOUT: AttentionTile(
        "Unusual Takeouts",
        "Taken out after a long quiet stretch.",
        "admin.admin_history",
        AttentionSeverity.WATCH,
        AttentionCounter.ALERT_ROWS,
    ),
}


def attention_tiles(session: Session, agency_id: int) -> list[AttentionTile]:
    """Every dashboard tile in urgency order, with the cleared ones pushed to the end."""
    open_alerts = _open_alerts_by_type(session, agency_id)
    tiles = [_counted_tile(tile, open_alerts.get(alert_type, [])) for alert_type, tile in ATTENTION_TILES.items()]
    return sorted(tiles, key=lambda tile: tile.count == 0)


def _counted_tile(tile: AttentionTile, alerts: list[Alert]) -> AttentionTile:
    count, extra = _tile_counts(tile.counter, alerts)
    return replace(tile, count=count, extra=extra)


def _tile_counts(counter: AttentionCounter, alerts: list[Alert]) -> tuple[int, int]:
    """The big number, then the smaller one in the unit the tile's detail line names."""
    if counter is AttentionCounter.ALERT_ROWS:
        return len(alerts), 0
    items = len({alert.item_id for alert in alerts if alert.item_id})
    match counter:
        case AttentionCounter.ITEM_PIECES:
            return items, sum((alert.detail or {}).get("quantity", 0) for alert in alerts)
        case AttentionCounter.ITEM_SPOTS:
            return items, len({(alert.item_id, (alert.detail or {}).get("storage_id")) for alert in alerts})
        case AttentionCounter.ITEM_LOCATIONS:
            return items, len({alert.agency_location_id for alert in alerts if alert.agency_location_id})


def _open_alerts_by_type(session: Session, agency_id: int) -> dict[AlertType, list[Alert]]:
    alerts = session.execute(select(Alert).where(Alert.agency_id == agency_id, Alert.status == AlertStatus.OPEN)).scalars().all()
    grouped: dict[AlertType, list[Alert]] = {}
    for alert in alerts:
        grouped.setdefault(alert.alert_type, []).append(alert)
    return grouped


def _pluralize(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
