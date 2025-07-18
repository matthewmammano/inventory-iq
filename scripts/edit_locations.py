#!/usr/bin/env python3
"""
edit_location.py - Script to manage user locations in the InventoryIQ system
"""

from app import db
from app.auth.models import UserItemLocations
from scripts.utils import (
    clear_screen,
    confirm_action,
    ensure_app_context,
    paginate_display,
    print_header,
    prompt_for_integer,
    prompt_for_string,
    select_user,
)


def display_locations(user):
    """Display all locations for a user with pagination."""
    locations = UserItemLocations.query.filter_by(user_id=user.id).order_by(UserItemLocations.name).all()

    def display_location(location, index):
        print(f"{index}. {location.name}")

    print_header(f"LOCATIONS FOR {user.display_name.upper()}")

    if not locations:
        print("No locations found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Available locations:\n")
    paginate_display(locations, display_location)
    input("\nPress Enter to continue...")


def add_location(user):
    """Add a new location for a user."""
    print_header(f"ADD LOCATION FOR {user.display_name.upper()}")

    # Get location name
    location_name = prompt_for_string("Location name: ")
    if location_name == "q":
        return

    # Check if location already exists for this user
    existing = UserItemLocations.query.filter_by(user_id=user.id, location_name=location_name).first()

    if existing:
        print(f"[ERROR] Location '{location_name}' already exists for this user!")
        input("\nPress Enter to continue...")
        return

    # Confirm action
    if not confirm_action(f"Add location '{location_name}' for user '{user.display_name}'?"):
        print("Operation cancelled.")
        return

    # Create location
    try:
        location = UserItemLocations(user_id=user.id, location_name=location_name)
        db.session.add(location)
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Location '{location_name}' added successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to add location: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def delete_location(user):
    """Delete a location for a user."""
    locations = UserItemLocations.query.filter_by(user_id=user.id).order_by(UserItemLocations.name).all()

    def display_location(location, index):
        print(f"{index}. {location.name}")

    print_header(f"DELETE LOCATION FOR {user.display_name.upper()}")

    if not locations:
        print("No locations found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Select a location to delete:\n")
    location_index = paginate_display(locations, display_location)

    if location_index == -1:
        return

    location = locations[location_index]

    # Check if location is used in action logs
    from app.inventory.models import ActionLogs

    from_logs = ActionLogs.query.filter_by(from_location_id=location.id).first()
    to_logs = ActionLogs.query.filter_by(to_location_id=location.id).first()

    if from_logs or to_logs:
        print("\n[WARNING] This location is used in inventory logs.")
        print("Deleting it may cause issues with historical inventory tracking.")

        if not confirm_action("Are you SURE you want to delete this location?"):
            print("Operation cancelled.")
            return
    elif not confirm_action(f"Delete location '{location.name}'?"):
        print("Operation cancelled.")
        return

    try:
        db.session.delete(location)
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Location '{location.name}' deleted successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to delete location: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def user_location_menu(user):
    """Menu for managing locations for a specific user."""
    while True:
        print_header(f"LOCATION MANAGEMENT FOR {user.display_name.upper()}")
        print("1. View Locations")
        print("2. Add Location")
        print("3. Delete Location")
        print("4. Return to Main Menu")

        choice = prompt_for_integer("\nEnter your choice (1-4): ", 1, 4)

        if choice == 1:
            display_locations(user)
        elif choice == 2:
            add_location(user)
        elif choice == 3:
            delete_location(user)
        elif choice == 4 or choice == -1:
            return


@ensure_app_context
def main():
    """Main function for the location management script."""
    while True:
        print_header("LOCATION MANAGEMENT")
        print("Select a user to manage locations or exit:")
        print("1. Select User")
        print("2. Exit")

        choice = prompt_for_integer("\nEnter your choice (1-2): ", 1, 2)

        if choice == 1:
            user = select_user()
            if user:
                user_location_menu(user)
        elif choice == 2 or choice == -1:
            clear_screen()
            print("Exiting location management. Goodbye!")
            break


if __name__ == "__main__":
    main()
