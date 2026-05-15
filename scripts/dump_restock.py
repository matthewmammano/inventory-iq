"""Print one location's restock analysis for quick manual QA."""

from app import create_app
from app.auth.queries import list_top_locations
from app.prediction.bulk_service import BulkService
from app.shared.database import get_session

AGENCY_ID = 1


def main() -> None:
    """Print restock rows for the first location in the demo agency."""
    app = create_app()
    with app.app_context(), get_session() as session:
        location = list_top_locations(AGENCY_ID, session=session)[0]
        rows = BulkService.get_restock_analysis(session, AGENCY_ID, location.id)

    print(f"RESTOCK ANALYSIS: agency={AGENCY_ID} location={location.name}")
    print(f"Total items: {len(rows)}")

    for row in rows:
        item = row["item"]
        confidence = row["confidence_display"]
        confidence_display = confidence if confidence is not None else ""
        print(
            f"{item.name}: current={row['current_total']} usage={row['daily_usage_rate']:.2f} "
            f"stockout={row['days_until_stockout']} confidence={confidence_display} "
            f"order={row['order_amount_display']}"
        )


if __name__ == "__main__":
    main()
