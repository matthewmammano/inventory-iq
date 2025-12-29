"""
edit_users.py - User management using model validation
"""

import pytz

from app.auth.models import Users
from scripts.utils import (
    clear_screen,
    create_with_validation,
    ensure_app_context,
    get_input,
    print_header,
    run_menu,
    select_user,
)


def add_user():
    """Add a new user - validation handled by Users model."""
    print_header("ADD NEW USER")
    print("Users will set passwords on first login.\n")

    # Collect basic info
    display_name = get_input("Display Name: ")
    if not display_name:
        return

    email = get_input("Email address: ")
    if not email:
        return

    pin = get_input("PIN (4 digits): ")
    if not pin:
        return

    # Timezone selection
    print("\nTimezone options:")
    print("1. US/Eastern  2. US/Central  3. US/Mountain  4. US/Pacific  5. Custom")

    choice = get_input("Select (1-5, default 1): ") or "1"

    timezone_map = {
        "1": "US/Eastern",
        "2": "US/Central",
        "3": "US/Mountain",
        "4": "US/Pacific",
    }

    if choice == "5":
        print("Examples: Europe/London, Asia/Tokyo, Australia/Sydney")
        timezone_name = get_input("Enter timezone: ")
        if not timezone_name or timezone_name not in pytz.all_timezones:
            timezone_name = "US/Eastern"
    else:
        timezone_name = timezone_map.get(choice, "US/Eastern")

    # Optional fields
    image_url = get_input("Profile image URL (optional): ") or None
    notes = get_input("Notes (optional): ") or None

    # Create user - model handles ALL validation
    user_data = {
        "display_name": display_name,
        "email": email,
        "pin": pin,
        "timezone": timezone_name,
        "image": image_url,
        "notes": notes,
        "password": None,  # Set on first login
    }

    user, error = create_with_validation(Users, **user_data)
    if error:
        print(f"\n[ERROR] {error}")

    input("\nPress Enter to continue...")


def delete_user():
    """Deactivate user instead of deleting."""
    print_header("DEACTIVATE USER")
    print("This will deactivate the user (preserves data).\n")

    user = select_user()
    if not user:
        return

    print(f"\nSelected: {user.display_name} ({user.email})")

    from scripts.utils import get_yes_no

    if not get_yes_no(f"Deactivate user '{user.display_name}'?"):
        return

    try:
        user.active = False
        from app.db import get_session

        with get_session() as session:
            session.add(user)
            session.commit()
        print(f"\n[SUCCESS] User '{user.display_name}' deactivated.")
    except Exception as e:
        from app.db import get_session

        # On exception, attempt a rollback in a new session for safety
        try:
            with get_session() as session:
                session.rollback()
        except Exception:
            pass
        print(f"\n[ERROR] Failed to deactivate: {e}")

    input("\nPress Enter to continue...")


@ensure_app_context
def main():
    """Main user management menu."""

    def exit_program():
        clear_screen()
        print("Exiting user management. Goodbye!")
        return True

    options = {
        "1": ("Add New User", add_user),
        "2": ("Deactivate User", delete_user),
        "3": ("Exit", exit_program),
    }

    run_menu("USER MANAGEMENT", options)


if __name__ == "__main__":
    main()
