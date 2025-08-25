"""
edit_tags.py - Tag management using model validation
"""
from app.auth.models import UserItemTags
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


def view_tags(user):
    """View all tags for a user."""
    tags = UserItemTags.query.filter_by(user_id=user.id).order_by(UserItemTags.tag_name).all()
    
    select_from_list(
        tags,
        lambda tag, i: print(f"{i}. {tag.tag_name} (Color: {tag.color})"),
        f"TAGS FOR {user.display_name.upper()}"
    )


def add_tag(user):
    """Add new tag - validation handled by model."""
    print_header(f"ADD TAG FOR {user.display_name.upper()}")
    
    tag_name = get_input("Tag name: ")
    if not tag_name:
        return
        
    color = get_input("Color (hex like #3b82f6, or Enter for default): ") or None
        
    # Create tag - model handles ALL validation
    tag, error = create_with_validation(UserItemTags, user_id=user.id, tag_name=tag_name, color=color)
    if error:
        print(f"\n[ERROR] {error}")
        
    input("\nPress Enter to continue...")


def edit_tag_color(user):
    """Edit tag color."""
    tags = UserItemTags.query.filter_by(user_id=user.id).order_by(UserItemTags.tag_name).all()
    
    selected = select_from_list(
        tags,
        lambda tag, i: print(f"{i}. {tag.tag_name} (Color: {tag.color})"),
        f"EDIT TAG FOR {user.display_name.upper()}"
    )
    
    if not selected:
        return
        
    print(f"\nEditing: {selected.tag_name}")
    print(f"Current color: {selected.color}")
    
    new_color = get_input("New color (hex like #3b82f6): ")
    if not new_color:
        return
        
    # Model validation happens automatically
    try:
        selected.color = new_color  # Triggers @validates decorator
        from app import db
        db.session.commit()
        print(f"\n[SUCCESS] Tag color updated!")
    except ValueError as e:
        from app import db
        db.session.rollback()
        print(f"\n[ERROR] {e}")
        
    input("\nPress Enter to continue...")


def delete_tag(user):
    """Delete tag with item usage check."""
    tags = UserItemTags.query.filter_by(user_id=user.id).order_by(UserItemTags.tag_name).all()
    
    selected = select_from_list(
        tags,
        lambda tag, i: print(f"{i}. {tag.tag_name}"),
        f"DELETE TAG FOR {user.display_name.upper()}"
    )
    
    if not selected:
        return
        
    def check_and_clean_usage(tag):
        """Check if tag is used and remove from items."""
        from app.inventory.models import Items
        
        items_using_tag = Items.query.filter(
            Items.user_id == user.id, 
            Items.tag_ids.contains([tag.id])
        ).all()
        
        if items_using_tag:
            print(f"\n[WARNING] This tag is used by {len(items_using_tag)} item(s).")
            if not get_yes_no("Delete tag and remove from all items?"):
                return False
                
            # Remove tag from all items
            for item in items_using_tag:
                if tag.id in item.tag_ids:
                    item.tag_ids.remove(tag.id)
                    
        return True
    
    delete_with_confirmation(selected, check_and_clean_usage)
    input("\nPress Enter to continue...")


def user_tag_menu(user):
    """Tag management for specific user."""
    options = {
        "1": ("View Tags", lambda: view_tags(user)),
        "2": ("Add Tag", lambda: add_tag(user)),
        "3": ("Edit Tag Color", lambda: edit_tag_color(user)),
        "4": ("Delete Tag", lambda: delete_tag(user)),
        "5": ("Return to Main Menu", lambda: True)
    }
    
    run_menu(f"TAG MANAGEMENT FOR {user.display_name.upper()}", options)


@ensure_app_context
def main():
    """Main tag management menu."""
    def select_and_manage():
        user = select_user()
        if user:
            user_tag_menu(user)
    
    def exit_program():
        from scripts.utils import clear_screen
        clear_screen()
        print("Exiting tag management. Goodbye!")
        return True
    
    options = {
        "1": ("Select User", select_and_manage),
        "2": ("Exit", exit_program)
    }
    
    run_menu("TAG MANAGEMENT", options)


if __name__ == "__main__":
    main()