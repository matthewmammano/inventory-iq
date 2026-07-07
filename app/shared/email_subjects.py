"""Shared labels and subject builders for report emails."""

REPORT_SUBJECT_PREFIX = "\u2b1c [REPORT]"
INVENTORY_COUNTS_TITLE = "Inventory Counts"
HISTORY_LOGS_TITLE = "History Logs"
INVENTORY_SUMMARIES_TITLE = "Inventory Summaries"
RESTOCK_REPORT_TITLE = "Restock Estimates"


def report_subject(title: str, agency_name: str) -> str:
    """Return the standard subject line for report emails."""
    return f"{REPORT_SUBJECT_PREFIX} {title} - {agency_name}"


def inventory_summary_title(period_label: str) -> str:
    """Return the standard title for one scheduled inventory summary period."""
    return f"Inventory {period_label} Summary"
