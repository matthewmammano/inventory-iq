"""Quick sanity-check summary of a generated database. Read-only."""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from app.alerts.models import Alert
from app.auth.models import Agency, Location
from app.inventory.models import ActionLog, InventoryItemLocationState, InventoryStorageBalance, Item, UnknownUpcScan
from app.shared.config import settings
from app.shared.database import get_session, init_db


def main() -> None:
    init_db(settings.database_url)
    with get_session() as db:
        for agency in db.scalars(select(Agency)):
            print(f"\n=== Agency #{agency.id}: {agency.display_name} ===")
            locations = db.scalars(select(Location).where(Location.agency_id == agency.id)).all()
            print(f"locations: {[loc.name for loc in locations]}")

            n_items = db.scalar(select(func.count()).select_from(Item).where(Item.agency_id == agency.id))
            n_actions = db.scalar(select(func.count()).select_from(ActionLog).where(ActionLog.agency_id == agency.id))
            print(f"items: {n_items}, action_logs: {n_actions}")

            op_counts = db.execute(
                select(ActionLog.operation_type, func.count()).where(ActionLog.agency_id == agency.id).group_by(ActionLog.operation_type)
            ).all()
            print("op mix:", {str(op): n for op, n in op_counts})

            admin_counts = db.execute(
                select(ActionLog.admin_action, func.count()).where(ActionLog.agency_id == agency.id).group_by(ActionLog.admin_action)
            ).all()
            print("admin vs guest:", {("admin" if a else "guest"): n for a, n in admin_counts})

            neg_balances = db.scalar(
                select(func.count()).select_from(InventoryStorageBalance).where(
                    InventoryStorageBalance.agency_id == agency.id, InventoryStorageBalance.quantity < 0
                )
            )
            print(f"negative storage balances (drift realism check): {neg_balances}")

            alert_counts = db.execute(
                select(Alert.alert_type, Alert.status, func.count())
                .where(Alert.agency_id == agency.id)
                .group_by(Alert.alert_type, Alert.status)
            ).all()
            print("alerts by type/status:")
            for alert_type, status, n in sorted(alert_counts, key=lambda r: -r[2]):
                print(f"  {alert_type} [{status}]: {n}")

            states = db.execute(
                select(func.min(InventoryItemLocationState.days_until_stockout), func.max(InventoryItemLocationState.days_until_stockout))
                .where(InventoryItemLocationState.agency_id == agency.id)
            ).one()
            print(f"days_until_stockout range: {states}")

            unknown = db.execute(
                select(UnknownUpcScan.upc, UnknownUpcScan.status, UnknownUpcScan.lookup_title).where(UnknownUpcScan.agency_id == agency.id)
            ).all()
            print(f"unknown UPC rows ({len(unknown)}):")
            for upc, status, title in unknown:
                print(f"  {upc} [{status}] -> {title}")


if __name__ == "__main__":
    sys.exit(main())
