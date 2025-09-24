"""
Monthly database size monitoring and usage analytics email report.

Checks database size and sends detailed usage information per squad including:
- Database growth metrics
- Items per user/squad
- Activity levels (scans, restocks, etc.)
- Storage efficiency metrics
- Growth trends

Cron job needed: 0 9 1 * * (monthly on 1st at 9 AM)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from flask import current_app, render_template_string
from flask_mailman import EmailMessage
from sqlalchemy import func

from app import create_app, db, mail
from app.auth.models import Users
from app.inventory.models import ActionLogs, Items, ItemLocationQuantities, OperationType

logger = logging.getLogger(__name__)


class DatabaseMonitorService:
    """Service for monitoring database size and generating usage reports."""

    @staticmethod
    def get_database_size_info() -> Dict[str, Any]:
        """Get database file size and table statistics."""
        try:
            # Get database file path
            db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if db_uri.startswith("sqlite:///"):
                db_path = db_uri.replace("sqlite:///", "")
                if not db_path.startswith("/"):
                    # Relative path - use instance folder
                    db_path = os.path.join(current_app.instance_path, db_path)

                if os.path.exists(db_path):
                    file_size = os.path.getsize(db_path)
                    size_mb = round(file_size / (1024 * 1024), 2)
                else:
                    file_size, size_mb = 0, 0.0
            else:
                # For production DB, we can't easily get file size
                file_size, size_mb = None, None

            # Get table row counts
            table_counts = {
                "users": Users.query.count(),
                "items": Items.query.count(),
                "action_logs": ActionLogs.query.count(),
                "item_location_quantities": ItemLocationQuantities.query.count(),
            }

            return {
                "file_size_bytes": file_size,
                "file_size_mb": size_mb,
                "table_counts": table_counts,
                "database_path": db_path if 'db_path' in locals() else "Unknown",
                "measurement_date": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Error getting database size info: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_user_squad_analytics() -> List[Dict[str, Any]]:
        """Get detailed analytics per user/squad."""
        try:
            users = Users.query.filter_by(active=True).all()
            analytics = []

            for user in users:
                # Basic counts
                total_items = Items.query.filter_by(user_id=user.id, active=True).count()
                total_locations = len(user.locations)

                # Activity in last 30 days
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                recent_actions = ActionLogs.query.filter(
                    ActionLogs.user_id == user.id,
                    ActionLogs.time_scanned >= thirty_days_ago
                ).count()

                # Breakdown by operation type (last 30 days)
                operation_counts = {}
                for op_type in OperationType:
                    count = ActionLogs.query.filter(
                        ActionLogs.user_id == user.id,
                        ActionLogs.operation_type == op_type,
                        ActionLogs.time_scanned >= thirty_days_ago
                    ).count()
                    operation_counts[op_type.value] = count

                # Storage efficiency - items with quantities
                items_with_stock = db.session.query(
                    func.count(ItemLocationQuantities.id)
                ).filter(
                    ItemLocationQuantities.user_id == user.id,
                    ItemLocationQuantities.quantity > 0
                ).scalar() or 0

                # Calculate efficiency ratio
                efficiency_ratio = (items_with_stock / total_items * 100) if total_items > 0 else 0

                # Growth trend - compare this month vs last month
                this_month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)

                this_month_actions = ActionLogs.query.filter(
                    ActionLogs.user_id == user.id,
                    ActionLogs.time_scanned >= this_month_start
                ).count()

                last_month_actions = ActionLogs.query.filter(
                    ActionLogs.user_id == user.id,
                    ActionLogs.time_scanned >= last_month_start,
                    ActionLogs.time_scanned < this_month_start
                ).count()

                growth_trend = "stable"
                if this_month_actions > last_month_actions * 1.2:
                    growth_trend = "increasing"
                elif this_month_actions < last_month_actions * 0.8:
                    growth_trend = "decreasing"

                analytics.append({
                    "user_id": user.id,
                    "display_name": user.display_name,
                    "email": user.email,
                    "total_items": total_items,
                    "total_locations": total_locations,
                    "recent_actions_30d": recent_actions,
                    "operation_breakdown": operation_counts,
                    "items_with_stock": items_with_stock,
                    "storage_efficiency_pct": round(efficiency_ratio, 1),
                    "growth_trend": growth_trend,
                    "this_month_actions": this_month_actions,
                    "last_month_actions": last_month_actions,
                })

            return analytics

        except Exception as e:
            logger.error(f"Error getting user squad analytics: {e}")
            return []

    @staticmethod
    def generate_report_email(db_info: Dict[str, Any], squad_analytics: List[Dict[str, Any]]) -> str:
        """Generate HTML email report."""

        # Email template
        template = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background-color: #f4f4f4; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .section { margin-bottom: 25px; }
        .metric { display: inline-block; margin: 10px 15px 10px 0; }
        .metric-label { font-weight: bold; color: #555; }
        .metric-value { font-size: 1.2em; color: #2c5aa0; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .trend-increasing { color: #28a745; font-weight: bold; }
        .trend-decreasing { color: #dc3545; font-weight: bold; }
        .trend-stable { color: #6c757d; }
        .efficiency-good { color: #28a745; }
        .efficiency-ok { color: #ffc107; }
        .efficiency-poor { color: #dc3545; }
    </style>
</head>
<body>
    <div class="header">
        <h2>📊 Monthly Database & Usage Report</h2>
        <p>Generated on {{ report_date }}</p>
    </div>

    <div class="section">
        <h3>💾 Database Size Metrics</h3>
        {% if db_info.file_size_mb %}
        <div class="metric">
            <div class="metric-label">Database Size:</div>
            <div class="metric-value">{{ db_info.file_size_mb }} MB</div>
        </div>
        {% endif %}

        <div class="metric">
            <div class="metric-label">Total Users:</div>
            <div class="metric-value">{{ db_info.table_counts.users }}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Items:</div>
            <div class="metric-value">{{ db_info.table_counts.items }}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Actions:</div>
            <div class="metric-value">{{ db_info.table_counts.action_logs }}</div>
        </div>
    </div>

    <div class="section">
        <h3>👥 Squad Usage Analytics</h3>
        <table>
            <thead>
                <tr>
                    <th>Squad</th>
                    <th>Items</th>
                    <th>Locations</th>
                    <th>Actions (30d)</th>
                    <th>Storage Efficiency</th>
                    <th>Growth Trend</th>
                </tr>
            </thead>
            <tbody>
                {% for squad in squad_analytics %}
                <tr>
                    <td><strong>{{ squad.display_name }}</strong></td>
                    <td>{{ squad.total_items }}</td>
                    <td>{{ squad.total_locations }}</td>
                    <td>{{ squad.recent_actions_30d }}</td>
                    <td>
                        <span class="{% if squad.storage_efficiency_pct >= 80 %}efficiency-good{% elif squad.storage_efficiency_pct >= 50 %}efficiency-ok{% else %}efficiency-poor{% endif %}">
                            {{ squad.storage_efficiency_pct }}%
                        </span>
                    </td>
                    <td>
                        <span class="trend-{{ squad.growth_trend }}">
                            {{ squad.growth_trend.title() }}
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h3>📈 Detailed Squad Breakdown</h3>
        {% for squad in squad_analytics %}
        <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
            <h4>{{ squad.display_name }}</h4>
            <p><strong>Activity Breakdown (30 days):</strong></p>
            <ul>
                <li>Counts: {{ squad.operation_breakdown.COUNT }}</li>
                <li>Restocks: {{ squad.operation_breakdown.RESTOCK }}</li>
                <li>Takeouts: {{ squad.operation_breakdown.TAKEOUT }}</li>
                <li>Transfers: {{ squad.operation_breakdown.TRANSFER }}</li>
            </ul>
            <p><strong>Storage:</strong> {{ squad.items_with_stock }}/{{ squad.total_items }} items have stock ({{ squad.storage_efficiency_pct }}% efficiency)</p>
        </div>
        {% endfor %}
    </div>

    <div class="section">
        <p><em>This report is generated automatically on the 1st of each month. For questions, contact your system administrator.</em></p>
    </div>
</body>
</html>
        """

        return render_template_string(template,
                                      report_date=datetime.now().strftime("%B %d, %Y"),
                                      db_info=db_info,
                                      squad_analytics=squad_analytics)

    @staticmethod
    def send_monthly_report() -> Dict[str, Any]:
        """Generate and send monthly database monitoring report."""
        try:
            # Collect database info
            logger.info("Collecting database size information...")
            db_info = DatabaseMonitorService.get_database_size_info()

            # Collect squad analytics
            logger.info("Collecting squad analytics...")
            squad_analytics = DatabaseMonitorService.get_user_squad_analytics()

            # Generate email report
            logger.info("Generating email report...")
            html_content = DatabaseMonitorService.generate_report_email(db_info, squad_analytics)

            # Get admin email (first user or configured email)
            admin_email = current_app.config.get("MAIL_DEFAULT_SENDER")
            if not admin_email:
                # Fallback to first active user
                first_user = Users.query.filter_by(active=True).first()
                admin_email = first_user.email if first_user else None

            if not admin_email:
                raise ValueError("No admin email configured for reports")

            # Send email
            logger.info(f"Sending monthly report to {admin_email}")
            msg = EmailMessage(
                subject=f"📊 Monthly Database Report - {datetime.now().strftime('%B %Y')}",
                body=html_content,
                from_email=current_app.config["MAIL_DEFAULT_SENDER"],
                to=[admin_email],
            )
            msg.content_subtype = "html"
            mail.send(msg)

            result = {
                "success": True,
                "report_sent_to": admin_email,
                "database_size_mb": db_info.get("file_size_mb"),
                "total_users": len(squad_analytics),
                "total_items": db_info.get("table_counts", {}).get("items", 0),
                "report_date": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(f"Monthly database report sent successfully: {result}")
            return result

        except Exception as e:
            logger.error(f"Error sending monthly database report: {e}")
            return {"success": False, "error": str(e)}


def main() -> Dict[str, Any]:
    """Main function for running as cron job."""
    app = create_app()

    with app.app_context():
        try:
            result = DatabaseMonitorService.send_monthly_report()

            if result.get("success"):
                logger.info("Monthly database monitoring completed successfully")
                print(f"✅ Report sent to {result['report_sent_to']}")
                print(f"📊 Database: {result.get('database_size_mb', 'N/A')} MB")
                print(f"👥 Users: {result['total_users']}")
                print(f"📦 Items: {result['total_items']}")
            else:
                logger.error(f"Monthly database monitoring failed: {result.get('error')}")
                print(f"❌ Error: {result.get('error')}")

            return result

        except Exception as e:
            logger.error(f"Critical error in monthly database monitoring: {e}")
            print(f"💥 Critical error: {e}")
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    main()