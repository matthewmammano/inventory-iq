"""Admin pending-task summaries for unresolved inventory work."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.constants import AlertStatus, AlertType
from app.alerts.models import Alert
from app.inventory.constants import UnknownUpcStatus
from app.inventory.models import UnknownUpcScan


@dataclass(frozen=True, slots=True)
class StaleCountTask:
    agency_location_id: int
    location_name: str
    item_ids: list[int]

    @property
    def count(self) -> int:
        return len(self.item_ids)


@dataclass(frozen=True, slots=True)
class PendingTaskSummary:
    missing_expiration_count: int
    stale_counts: list[StaleCountTask]
    new_barcode_count: int

    @property
    def total_count(self) -> int:
        return self.missing_expiration_count + sum(task.count for task in self.stale_counts) + self.new_barcode_count


def pending_task_summary(session: Session, agency_id: int) -> PendingTaskSummary:
    return PendingTaskSummary(
        missing_expiration_count=_open_event_count(session, agency_id, AlertType.EXPIRATION_COUNT_NEEDED),
        stale_counts=_stale_count_tasks(session, agency_id),
        new_barcode_count=_new_barcode_count(session, agency_id),
    )


def pending_task_count(session: Session, agency_id: int) -> int:
    return pending_task_summary(session, agency_id).total_count


def _open_event_count(session: Session, agency_id: int, alert_type: AlertType) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.agency_id == agency_id,
                Alert.alert_type == alert_type,
                Alert.status == AlertStatus.OPEN,
            )
        )
        or 0
    )


def _stale_count_tasks(session: Session, agency_id: int) -> list[StaleCountTask]:
    details = session.execute(
        select(Alert.detail).where(
            Alert.agency_id == agency_id,
            Alert.alert_type == AlertType.STALE_COUNT,
            Alert.status == AlertStatus.OPEN,
        )
    ).scalars()
    by_location: dict[int, tuple[str, set[int]]] = {}
    for detail in details:
        location_id = detail.get("agency_location_id")
        item_id = detail.get("item_id")
        if not isinstance(location_id, int) or not isinstance(item_id, int):
            continue
        location_name = str(detail.get("location_name") or "Location")
        existing_name, item_ids = by_location.setdefault(location_id, (location_name, set()))
        by_location[location_id] = (existing_name, item_ids | {item_id})
    return [
        StaleCountTask(location_id, location_name, sorted(item_ids))
        for location_id, (location_name, item_ids) in sorted(by_location.items(), key=lambda row: row[1][0])
    ]


def _new_barcode_count(session: Session, agency_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(UnknownUpcScan)
            .where(UnknownUpcScan.agency_id == agency_id, UnknownUpcScan.status == UnknownUpcStatus.PENDING)
        )
        or 0
    )
