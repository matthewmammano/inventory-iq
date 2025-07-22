#!/usr/bin/env python3
"""
edit_tags.py - Script to manage user tags in the InventoryIQ system
"""

from app import db
from app.auth.models import UserItemTags
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


def display_tags(user):
    """Display all tags for a user with pagination."""
    tags = (
        UserItemTags.query.filter_by(user_id=user.id)
        .order_by(UserItemTags.tag_name)
        .all()
    )

    def display_tag(tag, index):
        print(f"{index}. {tag.tag_name} (Color: {tag.color})")

    print_header(f"TAGS FOR {user.display_name.upper()}")

    if not tags:
        print("No tags found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Available tags:\n")
    paginate_display(tags, display_tag)
    input("\nPress Enter to continue...")


def add_tag(user):
    """Add a new tag for a user."""
    print_header(f"ADD TAG FOR {user.display_name.upper()}")

    # Get tag name
    tag_name = prompt_for_string("Tag name: ")
    if tag_name == "q":
        return

    # Validate tag name length
    if len(tag_name) > 50:
        print("[ERROR] Tag name must be 50 characters or less!")
        input("\nPress Enter to continue...")
        return

    # Get tag color (optional)
    color = prompt_for_string("Tag color (hex format like #3b82f6, or press Enter for default blue): ", allow_empty=True)
    if color == "q":
        return
    
    # Validate color format if provided
    if color and not (color.startswith('#') and len(color) == 7):
        print("[ERROR] Color must be in hex format like #3b82f6")
        input("\nPress Enter to continue...")
        return

    # Check if tag already exists for this user
    existing = UserItemTags.query.filter_by(
        user_id=user.id, tag_name=tag_name
    ).first()

    if existing:
        print(f"[ERROR] Tag '{tag_name}' already exists for this user!")
        input("\nPress Enter to continue...")
        return

    # Confirm action
    color_text = f" with color {color}" if color else ""
    if not confirm_action(
        f"Add tag '{tag_name}'{color_text} for user '{user.display_name}'?"
    ):
        print("Operation cancelled.")
        return

    # Create tag
    try:
        tag_data = {"user_id": user.id, "tag_name": tag_name}
        if color:
            tag_data["color"] = color
        tag = UserItemTags(**tag_data)
        db.session.add(tag)
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Tag '{tag_name}' added successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to add tag: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def edit_tag(user):
    """Edit a tag's color for a user."""
    tags = (
        UserItemTags.query.filter_by(user_id=user.id)
        .order_by(UserItemTags.tag_name)
        .all()
    )

    def display_tag(tag, index):
        print(f"{index}. {tag.tag_name} (Color: {tag.color})")

    print_header(f"EDIT TAG FOR {user.display_name.upper()}")

    if not tags:
        print("No tags found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Select a tag to edit:\n")
    tag_index = paginate_display(tags, display_tag)

    if tag_index == -1:
        return

    tag = tags[tag_index]
    
    print(f"\nEditing tag: {tag.tag_name}")
    print(f"Current color: {tag.color}")
    
    # Get new color
    new_color = prompt_for_string("New color (hex format like #3b82f6): ")
    if new_color == "q":
        return
    
    # Validate color format
    if not (new_color.startswith('#') and len(new_color) == 7):
        print("[ERROR] Color must be in hex format like #3b82f6")
        input("\nPress Enter to continue...")
        return

    # Confirm action
    if not confirm_action(f"Change color of tag '{tag.tag_name}' from {tag.color} to {new_color}?"):
        print("Operation cancelled.")
        return

    try:
        tag.color = new_color
        db.session.commit()
        print(f"\n[SUCCESS] ✅ Tag '{tag.tag_name}' color updated successfully!")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to update tag: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def delete_tag(user):
    """Delete a tag for a user."""
    tags = (
        UserItemTags.query.filter_by(user_id=user.id)
        .order_by(UserItemTags.tag_name)
        .all()
    )

    def display_tag(tag, index):
        print(f"{index}. {tag.tag_name}")

    print_header(f"DELETE TAG FOR {user.display_name.upper()}")

    if not tags:
        print("No tags found for this user.")
        input("\nPress Enter to continue...")
        return

    print("Select a tag to delete:\n")
    tag_index = paginate_display(tags, display_tag)

    if tag_index == -1:
        return

    tag = tags[tag_index]

    # Check if tag is used in items
    from app.inventory.models import Items

    items_with_tag = Items.query.filter(
        Items.user_id == user.id,
        Items.tag_ids.contains([tag.id])
    ).first()

    if items_with_tag:
        print("\n[WARNING] This tag is used by existing inventory items.")
        print("Deleting it may cause issues with inventory management.")

        if not confirm_action("Are you SURE you want to delete this tag?"):
            print("Operation cancelled.")
            return
    elif not confirm_action(f"Delete tag '{tag.tag_name}'?"):
        print("Operation cancelled.")
        return

    try:
        # Remove tag from all items that use it
        items_using_tag = Items.query.filter(
            Items.user_id == user.id,
            Items.tag_ids.contains([tag.id])
        ).all()
        
        for item in items_using_tag:
            if tag.id in item.tag_ids:
                item.tag_ids.remove(tag.id)
        
        # Delete the tag
        db.session.delete(tag)
        db.session.commit()
        print(
            f"\n[SUCCESS] ✅ Tag '{tag.tag_name}' deleted successfully!"
        )
        if items_using_tag:
            print(f"Removed tag from {len(items_using_tag)} item(s).")
        input("\nPress Enter to continue...")
    except Exception as e:
        print(f"\n[ERROR] Failed to delete tag: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


def user_tag_menu(user):
    """Menu for managing tags for a specific user."""
    while True:
        print_header(f"TAG MANAGEMENT FOR {user.display_name.upper()}")
        print("1. View Tags")
        print("2. Add Tag")
        print("3. Edit Tag Color")
        print("4. Delete Tag")
        print("5. Return to Main Menu")

        choice = prompt_for_integer("\nEnter your choice (1-5): ", 1, 5)

        if choice == 1:
            display_tags(user)
        elif choice == 2:
            add_tag(user)
        elif choice == 3:
            edit_tag(user)
        elif choice == 4:
            delete_tag(user)
        elif choice == 5 or choice == -1:
            return


@ensure_app_context
def main():
    """Main function for the tag management script."""
    while True:
        print_header("TAG MANAGEMENT")
        print("Select a user to manage tags or exit:")
        print("1. Select User")
        print("2. Exit")

        choice = prompt_for_integer("\nEnter your choice (1-2): ", 1, 2)

        if choice == 1:
            user = select_user()
            if user:
                user_tag_menu(user)
        elif choice == 2 or choice == -1:
            clear_screen()
            print("Exiting tag management. Goodbye!")
            break


if __name__ == "__main__":
    main()