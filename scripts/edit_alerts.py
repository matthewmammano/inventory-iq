#!/usr/bin/env python3
"""
edit_alerts.py - Script to manage user alerts in the InventoryIQ system
"""

import re

from app import db
from app.auth.models import UserAlerts
from scripts.utils import (
    clear_screen,
    confirm_action,
    ensure_app_context,
    paginate_display,
    print_header,
    prompt_for_boolean,
    prompt_for_integer,
    prompt_for_string,
    select_user,
)

# TODO YELLOW: fix all alerts in settings now


def validate_email(email):
    """Validate the email format using a regex pattern."""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None


def display_alerts(user):
    """Display all alerts for a user with pagination."""
    alerts = UserAlerts.query.filter_by(user_id=user.id).all()

    def display_alert(alert, index):
        print(f"{index}. Contact: {alert.contact_info}")
        print(f"   Low Stock Alerts: {'✓' if alert.alert_on_low_stock else '✗'}")
        print(f"   Scan Alerts: {'✓' if alert.alert_on_scan else '✗'}")
        print(f"   Unusual Scan Alerts: {'✓' if alert.alert_on_unusual_scan else '✗'}")
        print(f"   Daily Summary: {'✓' if alert.daily_summary else '✗'}")
        print(f"   Weekly Report: {'✓' if alert.weekly_report else '✗'}")
        print()

    print_header(f"ALERTS FOR {user.display_name.upper()}")

    if not alerts:
        print("No alerts found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Current alert configurations:\n")
    paginate_display(alerts, display_alert)
    input("\nPress Enter to continue...")


def add_alert(user):
    """Add a new alert configuration for a user."""
    print_header(f"ADD ALERT FOR {user.display_name.upper()}")

    # Get contact info
    print("Contact information can be an email address or phone number.")
    contact_info = prompt_for_string("Contact information: ")
    if contact_info == "q":
        return

    # Validate contact info
    if not (validate_email(contact_info) or validate_phone(contact_info)):
        print("[ERROR] Invalid contact information format.")
        input("\nPress Enter to continue...")
        return

    # Check if alert with this contact info already exists for this user
    existing = UserAlerts.query.filter_by(
        user_id=user.id, contact_info=contact_info
    ).first()

    if existing:
        print(
            f"[ERROR] Alert with contact '{contact_info}' already exists for this user!"
        )
        input("\nPress Enter to continue...")
        return

    # Get alert settings
    alert_on_low_stock = prompt_for_boolean("Enable low stock alerts?")
    alert_on_scan = prompt_for_boolean("Enable scan alerts?")
    alert_on_unusual_scan = prompt_for_boolean("Enable unusual scan alerts?")
    daily_summary = prompt_for_boolean("Enable daily summary?")
    weekly_report = prompt_for_boolean("Enable weekly report?")

    # Confirm action
    print("\nPlease confirm the alert configuration:")
    print(f"Contact: {contact_info}")
    print(f"Low Stock Alerts: {'Enabled' if alert_on_low_stock else 'Disabled'}")
    print(f"Scan Alerts: {'Enabled' if alert_on_scan else 'Disabled'}")
    print(f"Unusual Scan Alerts: {'Enabled' if alert_on_unusual_scan else 'Disabled'}")
    print(f"Daily Summary: {'Enabled' if daily_summary else 'Disabled'}")
    print(f"Weekly Report: {'Enabled' if weekly_report else 'Disabled'}")

    if not confirm_action("Add this alert configuration?"):
        print("Operation cancelled.")
        return

    # Create alert
    try:
        alert = UserAlerts(
            user_id=user.id,
            contact_info=contact_info,
            alert_on_low_stock=alert_on_low_stock,
            alert_on_scan=alert_on_scan,
            alert_on_unusual_scan=alert_on_unusual_scan,
            daily_summary=daily_summary,
            weekly_report=weekly_report,
        )
        db.session.add(alert)
        db.session.commit()
        print("\n[SUCCESS] ✅ Alert configuration added successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to add alert: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def delete_alert(user):
    """Delete an alert configuration for a user."""
    alerts = UserAlerts.query.filter_by(user_id=user.id).all()

    def display_alert(alert, index):
        print(f"{index}. Contact: {alert.contact_info}")
        print(f"   Low Stock Alerts: {'✓' if alert.alert_on_low_stock else '✗'}")
        print(f"   Scan Alerts: {'✓' if alert.alert_on_scan else '✗'}")
        print(f"   Unusual Scan Alerts: {'✓' if alert.alert_on_unusual_scan else '✗'}")
        print(f"   Daily Summary: {'✓' if alert.daily_summary else '✗'}")
        print(f"   Weekly Report: {'✓' if alert.weekly_report else '✗'}")
        print()

    print_header(f"DELETE ALERT FOR {user.display_name.upper()}")

    if not alerts:
        print("No alerts found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Select an alert to delete:\n")
    alert_index = paginate_display(alerts, display_alert)

    if alert_index == -1:
        return

    alert = alerts[alert_index]

    if not confirm_action(f"Delete alert for contact '{alert.contact_info}'?"):
        print("Operation cancelled.")
        return

    try:
        db.session.delete(alert)
        db.session.commit()
        print("\n[SUCCESS] ✅ Alert deleted successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to delete alert: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def user_alert_menu(user):
    """Menu for managing alerts for a specific user."""
    while True:
        print_header(f"ALERT MANAGEMENT FOR {user.display_name.upper()}")
        print("1. View Alerts")
        print("2. Add Alert")
        print("3. Delete Alert")
        print("4. Return to Main Menu")

        choice = prompt_for_integer("\nEnter your choice (1-4): ", 1, 4)

        if choice == 1:
            display_alerts(user)
        elif choice == 2:
            add_alert(user)
        elif choice == 3:
            delete_alert(user)
        elif choice == 4 or choice == -1:
            return


@ensure_app_context
def main():
    """Main function for the alert management script."""
    while True:
        print_header("ALERT MANAGEMENT")
        print("Select a user to manage alerts or exit:")
        print("1. Select User")
        print("2. Exit")

        choice = prompt_for_integer("\nEnter your choice (1-2): ", 1, 2)

        if choice == 1:
            user = select_user()
            if user:
                user_alert_menu(user)
        elif choice == 2 or choice == -1:
            clear_screen()
            print("Exiting alert management. Goodbye!")
            break


if __name__ == "__main__":
    main()
