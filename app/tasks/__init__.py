"""
Task module for background jobs and scheduled tasks.
All tasks are configured to run via Railway's native cron scheduler.
"""

# Import all task functions for Railway to discover
from .archive_action_logs import archive_action_logs
from .backup_database import backup_database
from .check_admin_recount import check_admin_count_alerts
from .cleanup_sessions import cleanup_expired_sessions
from .generate_summary_reports import generate_summary_reports
from .monitor_database_size import monitor_database_size
from .process_email_alerts import process_email_alerts

__all__ = [
    "archive_action_logs",
    "backup_database",
    "check_admin_count_alerts",
    "cleanup_expired_sessions",
    "generate_summary_reports",
    "monitor_database_size",
    "process_email_alerts",
]
