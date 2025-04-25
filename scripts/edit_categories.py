#!/usr/bin/env python3
"""
edit_category.py - Script to manage user categories in the InventoryIQ system
"""

import sys
from app import db
from app.auth.models import Users, UserCategories
from scripts.utils import (
    clear_screen, print_header, prompt_for_integer, prompt_for_string,
    prompt_for_boolean, confirm_action, ensure_app_context, select_user,
    paginate_display
)

def display_categories(user):
    """Display all categories for a user with pagination."""
    categories = UserCategories.query.filter_by(user_id=user.id).order_by(UserCategories.category_name).all()
    
    def display_category(category, index):
        print(f"{index}. {category.category_name}")
    
    print_header(f"CATEGORIES FOR {user.display_name.upper()}")
    
    if not categories:
        print("No categories found for this user.")
        input("\nPress Enter to continue...")
        return
    
    print("Available categories:\n")
    paginate_display(categories, display_category)
    input("\nPress Enter to continue...")

def add_category(user):
    """Add a new category for a user."""
    print_header(f"ADD CATEGORY FOR {user.display_name.upper()}")
    
    # Get category name
    category_name = prompt_for_string("Category name: ")
    if category_name == 'q':
        return
    
    # Check if category already exists for this user
    existing = UserCategories.query.filter_by(
        user_id=user.id, 
        category_name=category_name
    ).first()
    
    if existing:
        print(f"[ERROR] Category '{category_name}' already exists for this user!")
        input("\nPress Enter to continue...")
        return
    
    # Confirm action
    if not confirm_action(f"Add category '{category_name}' for user '{user.display_name}'?"):
        print("Operation cancelled.")
        return
    
    # Create category
    try:
        category = UserCategories(
            user_id=user.id,
            category_name=category_name
        )
        db.session.add(category)
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Category '{category_name}' added successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to add category: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")

def delete_category(user):
    """Delete a category for a user."""
    categories = UserCategories.query.filter_by(user_id=user.id).order_by(UserCategories.category_name).all()
    
    def display_category(category, index):
        print(f"{index}. {category.category_name}")
    
    print_header(f"DELETE CATEGORY FOR {user.display_name.upper()}")
    
    if not categories:
        print("No categories found for this user.")
        input("\nPress Enter to continue...")
        return
    
    print("Select a category to delete:\n")
    category_index = paginate_display(categories, display_category)
    
    if category_index == -1:
        return
    
    category = categories[category_index]
    
    # Check if category is used in items
    from app.inventory.models import Items
    items = Items.query.filter_by(category_id=category.id).first()
    
    if items:
        print("\n[WARNING] This category is used by existing inventory items.")
        print("Deleting it may cause issues with inventory management.")
        
        if not confirm_action("Are you SURE you want to delete this category?"):
            print("Operation cancelled.")
            return
    elif not confirm_action(f"Delete category '{category.category_name}'?"):
        print("Operation cancelled.")
        return
    
    try:
        db.session.delete(category)
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Category '{category.category_name}' deleted successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to delete category: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")

def user_category_menu(user):
    """Menu for managing categories for a specific user."""
    while True:
        print_header(f"CATEGORY MANAGEMENT FOR {user.display_name.upper()}")
        print("1. View Categories")
        print("2. Add Category")
        print("3. Delete Category")
        print("4. Return to Main Menu")
        
        choice = prompt_for_integer("\nEnter your choice (1-4): ", 1, 4)
        
        if choice == 1:
            display_categories(user)
        elif choice == 2:
            add_category(user)
        elif choice == 3:
            delete_category(user)
        elif choice == 4 or choice == -1:
            return

@ensure_app_context
def main():
    """Main function for the category management script."""
    while True:
        print_header("CATEGORY MANAGEMENT")
        print("Select a user to manage categories or exit:")
        print("1. Select User")
        print("2. Exit")
        
        choice = prompt_for_integer("\nEnter your choice (1-2): ", 1, 2)
        
        if choice == 1:
            user = select_user()
            if user:
                user_category_menu(user)
        elif choice == 2 or choice == -1:
            clear_screen()
            print("Exiting category management. Goodbye!")
            break

if __name__ == "__main__":
    main()