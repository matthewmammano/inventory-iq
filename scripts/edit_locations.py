"""
edit_locations.py - Location management using model validation
"""
from app.auth.models import UserItemLocations
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
    locations = UserItemLocations.query.filter_by(user_id=user.id).order_by(UserItemLocations.name).all()
    
    select_from_list(
        locations,
        lambda loc, i: print(f"{i}. {loc.name}"),
        f"LOCATIONS FOR {user.display_name.upper()}"
    )


def add_location(user):
    """Add new location - validation handled by model."""
    print_header(f"ADD LOCATION FOR {user.display_name.upper()}")
    
    name = get_input("Location name: ")
    if not name:
        return
        
    # Create location - model handles validation
    location, error = create_with_validation(UserItemLocations, user_id=user.id, name=name)
    if error:
        print(f"\n[ERROR] {error}")
        
    input("\nPress Enter to continue...")


def delete_location(user):
    """Delete location with usage check."""
    locations = UserItemLocations.query.filter_by(user_id=user.id).order_by(UserItemLocations.name).all()
    
    selected = select_from_list(
        locations,
        lambda loc, i: print(f"{i}. {loc.name}"),
        f"DELETE LOCATION FOR {user.display_name.upper()}"
    )
    
    if not selected:
        return
        
    def check_usage(location):
        """Check if location is used in action logs."""
        from app.inventory.models import ActionLogs
        
        from_logs = ActionLogs.query.filter_by(from_location_id=location.id).first()
        to_logs = ActionLogs.query.filter_by(to_location_id=location.id).first()
        
        if from_logs or to_logs:
            print("\n[WARNING] This location is used in inventory logs.")
            print("Deleting may cause issues with historical tracking.")
            return get_yes_no("Are you SURE you want to delete?")
        return True
    
    delete_with_confirmation(selected, check_usage)
    input("\nPress Enter to continue...")


def user_location_menu(user):
    """Location management for specific user."""
    options = {
        "1": ("View Locations", lambda: view_locations(user)),
        "2": ("Add Location", lambda: add_location(user)),
        "3": ("Delete Location", lambda: delete_location(user)),
        "4": ("Return to Main Menu", lambda: True)
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
    
    options = {
        "1": ("Select User", select_and_manage),
        "2": ("Exit", exit_program)
    }
    
    run_menu("LOCATION MANAGEMENT", options)


if __name__ == "__main__":
    main()