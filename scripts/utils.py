import os
from typing import Any, Callable, Dict, List, Type

from sqlalchemy import select

from app import create_app
from app.auth.models import Users
from app.db import get_session


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header(title: str):
    """Print formatted header."""
    clear_screen()
    print("\n" + "=" * 50)
    print(f"{title.center(50)}")
    print("=" * 50 + "\n")


def get_input(prompt: str) -> str | None:
    """Get string input, return None if user quits."""
    value = input(prompt).strip()
    return None if value.lower() == "q" else value


def get_yes_no(prompt: str) -> bool | None:
    """Get yes/no input."""
    while True:
        value = get_input(f"{prompt} (y/n): ")
        if value is None:
            return None
        if value.lower() in ["y", "yes"]:
            return True
        elif value.lower() in ["n", "no"]:
            return False
        print("Enter 'y' or 'n'")


def select_from_list(
    items: List[Any], display_func: Callable, title: str
) -> Any | None:
    """Display paginated list and return selected item."""
    if not items:
        print_header(title)
        print("No items found.")
        input("\nPress Enter to continue...")
        return None

    page_size = 10
    total_pages = (len(items) + page_size - 1) // page_size
    page = 1

    while True:
        print_header(title)

        start = (page - 1) * page_size
        end = min(start + page_size, len(items))

        print(f"Page {page} of {total_pages}\n")
        for i in range(start, end):
            display_func(items[i], i + 1)

        print(f"\nOptions: [1-{len(items)}] select")
        if total_pages > 1:
            if page < total_pages:
                print("n - Next")
            if page > 1:
                print("p - Previous")
        print("q - Quit")

        choice = input("\nChoice: ").lower()

        if choice == "q":
            return None
        elif choice == "n" and page < total_pages:
            page += 1
        elif choice == "p" and page > 1:
            page -= 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return items[idx]
            print("Invalid selection.")
            input("Press Enter...")


def select_user() -> Users | None:
    """Select from active users using an explicit session."""
    with get_session() as session:
        stmt = select(Users).where(Users.active.is_(True)).order_by(Users.display_name)
        users_seq = session.execute(stmt).scalars().all()
        users = list(users_seq)
    return select_from_list(
        users, lambda u, i: print(f"{i}. {u.display_name} ({u.email})"), "SELECT USER"
    )


def ensure_app_context(func):
    """Decorator for Flask app context."""

    def wrapper(*args, **kwargs):
        app = create_app()
        with app.app_context():
            return func(*args, **kwargs)

    return wrapper


def create_with_validation(model_class: Type, **data) -> tuple[Any | None, str | None]:
    """
    Create model instance - validation happens automatically via @validates decorators.
    Returns (instance, error_message)
    """
    try:
        instance = model_class(**data)
        with get_session() as session:
            session.add(instance)
            session.commit()
        print(f"\n[SUCCESS] {model_class.__name__} created!")
        return instance, None
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"Database error: {e}"


def delete_with_confirmation(
    instance: Any, additional_check: Callable[[Any], bool] | None = None
) -> bool:
    """Delete model instance with confirmation."""
    name = getattr(instance, "name", None) or getattr(instance, "display_name", "item")

    # Run additional checks (like checking if item is in use)
    if additional_check and not additional_check(instance):
        return False

    if not get_yes_no(f"Delete '{name}'?"):
        return False

    try:
        with get_session() as session:
            session.delete(instance)
            session.commit()
        print(f"\n[SUCCESS] '{name}' deleted!")
        return True
    except Exception as e:
        print(f"\n[ERROR] Delete failed: {e}")
        return False


def run_menu(title: str, options: Dict[str, tuple[str, Callable]]):
    """Generic menu loop."""
    while True:
        print_header(title)

        for key, (label, _) in options.items():
            print(f"{key}. {label}")

        choice = get_input(f"\nChoice (1-{len(options)}): ")

        if choice is None or not choice.isdigit():
            break

        choice_num = int(choice)
        if str(choice_num) not in options:
            continue

        try:
            _, action = options[str(choice_num)]
            if action() is True:  # Exit signal
                break
        except KeyboardInterrupt:
            print("\nCancelled.")
        except Exception as e:
            print(f"\n[ERROR] {e}")
            input("Press Enter...")
