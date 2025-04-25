#!/usr/bin/env python3
"""
edit_users.py - Script to edit user information in the InventoryIQ system
"""

import sys
import re
import pytz
from app import db
from app.auth.models import Users
from scripts.utils import (
    clear_screen, print_header, prompt_for_integer, prompt_for_string,
    prompt_for_boolean, confirm_action, ensure_app_context, select_user
)

def validate_email(email):
    """Validate the email format using a regex pattern."""
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(pattern, email) is not None

def validate_pin(pin):
    """Validate that PIN is 4 digits."""
    return pin.isdigit() and len(pin) == 4

def add_user():
    """Add a new user to the system."""
    print_header("ADD NEW USER")
    print("This utility will add a new user to the system.")
    print("Users will set their own passwords when they first access the system.\n")

    # Get display name
    display_name = prompt_for_string('Display Name (short acronym or abbreviation): ')
    if display_name == 'q':
        return
        
    # Check if display name already exists
    if Users.query.filter_by(display_name=display_name).first():
        print(f"[ERROR] Display name '{display_name}' already exists!")
        input("Press Enter to continue...")
        return

    # Get PIN
    while True:
        pin = prompt_for_string('PIN (4 digits): ')
        if pin == 'q':
            return
        if validate_pin(pin):
            break
        print("PIN must be 4 digits. Try again.")

    # Get email
    while True:
        email = prompt_for_string('Email address: ')
        if email == 'q':
            return
            
        if not validate_email(email):
            print('Invalid email format! Try again.')
            continue
                
        # Check if email exists
        if Users.query.filter_by(email=email).first():
            print(f'[ERROR] Email \'{email}\' already exists! Try a different email.')
            continue
        break

    # Get timezone
    print("\nAvailable timezone options:")
    print("1. US/Eastern (New York, Boston, Miami)")
    print("2. US/Central (Chicago, Dallas, Mexico City)")
    print("3. US/Mountain (Denver, Salt Lake City)")
    print("4. US/Pacific (Los Angeles, Seattle, Vancouver)")
    print("5. Enter custom timezone")
    
    timezone_choice = input("\nSelect timezone (1-5, default is 1): ") or "1"
    
    timezone_map = {
        "1": "US/Eastern",
        "2": "US/Central",
        "3": "US/Mountain",
        "4": "US/Pacific"
    }
    
    if timezone_choice == "5":
        print("\nCommon timezone examples:")
        print("- Europe/London, Europe/Paris, Europe/Berlin")
        print("- Asia/Tokyo, Asia/Singapore, Asia/Dubai")
        print("- Australia/Sydney, Pacific/Auckland")
        print("- America/Toronto, America/Mexico_City")
        
        while True:
            timezone_name = input("\nEnter timezone (see pytz.all_timezones for complete list): ")
            if timezone_name in pytz.all_timezones:
                break
            else:
                print(f"Invalid timezone: {timezone_name}")
                print("If unsure, press Enter to use US/Eastern")
                if not timezone_name:
                    timezone_name = "US/Eastern"
                    break
    else:
        timezone_name = timezone_map.get(timezone_choice, "US/Eastern")     

    # Additional information
    image_url = prompt_for_string("Profile image URL (or press Enter to skip): ", allow_empty=True)
    notes = prompt_for_string("Additional notes about the user (or press Enter to skip): ", allow_empty=True)

    # Confirmation
    print("\nPlease confirm the following information:")
    print(f"Display Name: {display_name}")
    print(f"Email: {email}")
    print(f"PIN: {pin}")
    print(f"Timezone: {timezone_name}")
    print(f"Image URL: {image_url or 'None'}")
    print(f"Notes: {notes or 'None'}")
    
    if not confirm_action("Create this user?"):
        print("User creation cancelled.")
        return

    # Create and save user
    try:
        # Create new user with password set to NULL
        user = Users(
            display_name=display_name,
            email=email,
            password=None,  # Password will be set by user on first login
            pin=pin,
            timezone=timezone_name,
            image=image_url,
            notes=notes
        )
        
        db.session.add(user)
        db.session.commit()
        
        print(f"\n[SUCCESS] ✅ User '{display_name}' added successfully!")
        print(f"The user will need to set their password on first login.")
        input("\nPress Enter to continue...")
        
    except Exception as e:
        print(f"\n[ERROR] Failed to create user: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")

def delete_user():
    """Delete (deactivate) a user from the system."""
    print_header("DELETE USER")
    print("This utility will deactivate a user in the system.")
    print("Note: User data will be preserved but the user will no longer be able to log in.\n")
    
    user = select_user()
    if not user:
        return
    
    print(f"\nSelected user: {user.display_name} ({user.email})")
    
    if not confirm_action(f"Are you sure you want to deactivate user '{user.display_name}'?"):
        print("Operation cancelled.")
        return
        
    try:
        # Instead of deleting, we'll set active = False
        user.active = False
        db.session.commit()
        print(f"\n[SUCCESS] ✅ User '{user.display_name}' has been deactivated.")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to deactivate user: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")

@ensure_app_context
def main():
    """Main function for the user edit script."""
    while True:
        print_header("USER MANAGEMENT")
        print("1. Add New User")
        print("2. Delete User")
        print("3. Exit")
        
        choice = prompt_for_integer("\nEnter your choice (1-3): ", 1, 3)
        
        if choice == 1:
            add_user()
        elif choice == 2:
            delete_user()
        elif choice == 3 or choice == -1:
            clear_screen()
            print("Exiting user management. Goodbye!")
            break

if __name__ == "__main__":
    main()