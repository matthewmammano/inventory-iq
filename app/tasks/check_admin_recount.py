"""
TODO RED: Implement admin count monitoring

Check items needing admin count based on count_last_days setting.
User setting exists in app/auth/models.py:117-119

Cron job needed: 0 5 * * * (daily at 5 AM)
"""

from app import create_app


def check_admin_count_alerts():
    # Logic should:
    # 1. Get all users with count_last_days > 0
    # 2. Find items not admin-counted in X days
    # 3. Generate admin count alerts
    # 4. Use existing AlertDetectionService patterns
    pass


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        check_admin_count_alerts()
