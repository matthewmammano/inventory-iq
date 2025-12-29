"""
edit_locations.py - Location management using model validation
"""

from sqlalchemy import select

from app.auth.models import UserItemLocations
from app.db import get_session
from scripts.utils import (
    create_with_validation,
    delete_with_confirmation,
    ensure_app_context,
    get_input,
    get_yes_no,
    print_header,
    run_menu,
    select_from_list,
    select_user,
)


def view_locations(user):
    """View all locations for a user."""
    with get_session() as session:
        stmt = (
            select(UserItemLocations)
            .where(UserItemLocations.user_id == user.id)
            .order_by(UserItemLocations.name)
        )
        locations = list(session.execute(stmt).scalars().all())

    def display_location(loc, i):
        access_from = "✓" if loc.user_access_from else "✗"
        access_to = "✓" if loc.user_access_to else "✗"
        print(f"{i}. {loc.name} | From:{access_from} To:{access_to}")

    select_from_list(
        locations, display_location, f"LOCATIONS FOR {user.display_name.upper()}"
    )


def add_location(user):
    """Add new location - validation handled by model."""
    print_header(f"ADD LOCATION FOR {user.display_name.upper()}")

    name = get_input("Location name: ")
    if not name:
        return

    user_access_from = get_yes_no("Can users access items FROM this location? (y/n): ")
    user_access_to = get_yes_no("Can users access items TO this location? (y/n): ")

    # Create location - model handles validation
    location, error = create_with_validation(
        UserItemLocations,
        user_id=user.id,
        name=name,
        user_access_from=user_access_from,
        user_access_to=user_access_to,
    )
    if error:
        print(f"\n[ERROR] {error}")

    input("\nPress Enter to continue...")


def delete_location(user):
    """Delete location with usage check."""
    with get_session() as session:
        stmt = (
            select(UserItemLocations)
            .where(UserItemLocations.user_id == user.id)
            .order_by(UserItemLocations.name)
        )
        locations = list(session.execute(stmt).scalars().all())

    selected = select_from_list(
        locations,
        lambda loc, i: print(f"{i}. {loc.name}"),
        f"DELETE LOCATION FOR {user.display_name.upper()}",
    )

    if not selected:
        return

    def check_usage(location):
        """Check if location is used in action logs."""
        from sqlalchemy import select

        from app.db import get_session
        from app.inventory.models import ActionLogs

        with get_session() as session:
            stmt_from = select(ActionLogs).where(
                ActionLogs.from_location_id == location.id
            )
            stmt_to = select(ActionLogs).where(ActionLogs.to_location_id == location.id)
            from_logs = session.execute(stmt_from).scalars().first()
            to_logs = session.execute(stmt_to).scalars().first()

        if from_logs or to_logs:
            print("\n[WARNING] This location is used in inventory logs.")
            print("Deleting may cause issues with historical tracking.")
            res = get_yes_no("Are you SURE you want to delete?")
            return bool(res) if res is not None else False
        return True

    delete_with_confirmation(selected, check_usage)
    input("\nPress Enter to continue...")


def user_location_menu(user):
    """Location management for specific user."""
    options = {
        "1": ("View Locations", lambda: view_locations(user)),
        "2": ("Add Location", lambda: add_location(user)),
        "3": ("Delete Location", lambda: delete_location(user)),
        "4": ("Return to Main Menu", lambda: True),
    }

    run_menu(f"LOCATION MANAGEMENT FOR {user.display_name.upper()}", options)


@ensure_app_context
def main():
    """Main location management menu."""

    def select_and_manage():
        user = select_user()
        if user:
            user_location_menu(user)

    def exit_program():
        from scripts.utils import clear_screen

        clear_screen()
        print("Exiting location management. Goodbye!")
        return True

    options = {"1": ("Select User", select_and_manage), "2": ("Exit", exit_program)}

    run_menu("LOCATION MANAGEMENT", options)


if __name__ == "__main__":
    main()
