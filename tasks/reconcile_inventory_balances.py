"""Audit and repair derived inventory balances from action history.

Production task: python -m tasks.reconcile_inventory_balances
"""

import argparse

from app import create_app
from app.shared.config import settings
from app.shared.scheduler import SchedulerJobName, run_inventory_balance_audit, run_scheduled_task


def run(*, agency_id: int | None = None, repair: bool = True) -> None:
    """Run the inventory balance audit for one agency or all active agencies."""
    settings.scheduler_enabled = False
    app = create_app()
    with (
        app.app_context(),
        run_scheduled_task(
            "reconcile_inventory_balances",
            SchedulerJobName.RECONCILE_INVENTORY_BALANCES,
            scheduler_agency_id=agency_id or 0,
            agency_id=agency_id,
            repair=repair,
        ) as task_result,
    ):
        if task_result is not None:
            task_result.update(run_inventory_balance_audit(agency_id=agency_id, repair=repair))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit derived inventory balances.")
    parser.add_argument("--agency-id", type=int, help="run for one agency only")
    parser.add_argument("--check-only", action="store_true", help="log discrepancies without rebuilding balances")
    args = parser.parse_args()
    run(agency_id=args.agency_id, repair=not args.check_only)
