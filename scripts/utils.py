import os
from typing import Any, Callable, List, Optional

from app import create_app
from app.auth.models import Users


def clear_screen():
    """Clear the terminal screen based on operating system."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header(title: str):
    """Print a formatted header for the current operation."""
    clear_screen()
    print("\n" + "=" * 50)
    print(f"{title.center(50)}")
    print("=" * 50 + "\n")


def prompt_for_integer(message: str, min_val: int = None, max_val: int = None) -> int:
    """Prompt the user for an integer input with validation."""
    while True:
        try:
            value = input(message)
            if value.lower() == "q":
                return -1  # Special value for quit

            value = int(value)

            if min_val is not None and value < min_val:
                print(f"Value must be at least {min_val}. Try again.")
                continue

            if max_val is not None and value > max_val:
                print(f"Value must be at most {max_val}. Try again.")
                continue

            return value
        except ValueError:
            print("Please enter a valid number.")


def prompt_for_string(message: str, allow_empty: bool = False) -> str:
    """Prompt the user for a string input with validation."""
    while True:
        value = input(message)
        if value.lower() == "q":
            return "q"  # Special value for quit

        if not allow_empty and not value.strip():
            print("Input cannot be empty. Try again.")
            continue

        return value.strip()


def prompt_for_boolean(message: str) -> bool:
    """Prompt the user for a yes/no response."""
    while True:
        response = input(f"{message} (y/n): ").lower()
        if response in ["y", "yes"]:
            return True
        elif response in ["n", "no"]:
            return False
        else:
            print("Please enter 'y' or 'n'.")


def paginate_display(
    items: List[Any], display_function: Callable[[Any, int], None], page_size: int = 10
) -> int:
    """
    Display items with pagination and return the selected index.

    Args:
        items: List of items to display
        display_function: Function to display a single item with its index
        page_size: Number of items to display per page

    Returns:
        Selected index or -1 if user wants to quit
    """
    if not items:
        print("No items found.")
        input("Press Enter to continue...")
        return -1

    total_pages = (len(items) + page_size - 1) // page_size
    current_page = 1

    while True:
        clear_screen()
        start_index = (current_page - 1) * page_size
        end_index = min(start_index + page_size, len(items))

        print(f"\nPage {current_page} of {total_pages}\n")

        for i in range(start_index, end_index):
            display_function(items[i], i + 1)

        print("\nOptions:")
        if total_pages > 1:
            print("n - Next page" if current_page < total_pages else "")
            print("p - Previous page" if current_page > 1 else "")
        print("q - Return to previous menu")

        choice = input("\nEnter the number of your choice or an option: ").lower()

        if choice == "q":
            return -1
        elif choice == "n" and current_page < total_pages:
            current_page += 1
        elif choice == "p" and current_page > 1:
            current_page -= 1
        elif choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(items):
                return index
            else:
                print("Invalid selection. Try again.")
                input("Press Enter to continue...")
        else:
            print("Invalid input. Try again.")
            input("Press Enter to continue...")


def select_user() -> Optional[Users]:
    """
    Display a list of users and allow selection of one.

    Returns:
        Selected user object or None if cancelled
    """
    users = Users.query.filter_by(active=True).order_by(Users.display_name).all()

    def display_user(user, index):
        print(f"{index}. {user.display_name} ({user.email})")

    print_header("SELECT USER")
    print("Select a user to continue:\n")

    user_index = paginate_display(users, display_user)

    if user_index == -1:
        return None

    return users[user_index]


def confirm_action(message: str) -> bool:
    """Prompt for confirmation before proceeding with an action."""
    response = input(f"\n{message} (y/n): ").lower()
    return response in ["y", "yes"]


def ensure_app_context(func):
    """Decorator to ensure function runs within Flask app context."""

    def wrapper(*args, **kwargs):
        app = create_app()
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper
