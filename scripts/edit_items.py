"""
edit_items.py - Item management and CSV import using model validation
"""

import csv
import json
from pathlib import Path

from app import db
from app.inventory.models import Items
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


def import_items():
    """Import items from CSV with model validation."""
    print_header("IMPORT ITEMS FROM CSV")
    print("Replace ALL items for selected user with CSV data.")
    print("\nRequired CSV columns: user_id, name")
    print(
        "Optional: upc, active, tag_ids, increments, image, min_quantity, max_quantity, batch_size, expiration_days, restock_delivery_days"
    )
    print("\nExample:")
    print("user_id,name,increments,tag_ids,min_quantity")
    print('1,Bandage,individual,"[1,2]",10\n')

    # Select user
    user = select_user()
    if not user:
        return

    # Get CSV file path
    csv_path = get_input("CSV file path: ")
    if not csv_path or not Path(csv_path).exists():
        print(f"[ERROR] File not found: {csv_path}")
        input("Press Enter...")
        return

    try:
        # Load CSV data
        items_data = load_csv_items(csv_path, user.id)
        if not items_data:
            print(f"[WARNING] No items found for user {user.id}")
            input("Press Enter...")
            return

        current_count = Items.query.filter_by(user_id=user.id).count()
        print(f"\n[INFO] Found {len(items_data)} items in CSV")
        print(f"[WARNING] This will DELETE {current_count} existing items")

        if not get_yes_no("Continue with import?"):
            return

        # Delete existing and create new
        print("\n[INFO] Starting import...")

        # Delete all user's items
        deleted = Items.query.filter_by(user_id=user.id).delete()
        print(f"Deleted {deleted} existing items")

        # Create new items using model validation
        created = 0
        failed = 0

        for item_data in items_data:
            item, error = create_with_validation(Items, **item_data)
            if item:
                created += 1
            else:
                print(f"[ERROR] Failed to create '{item_data.get('name')}': {error}")
                failed += 1

        print("\n[SUCCESS] Import complete!")
        print(f"- Created: {created} items")
        print(f"- Failed: {failed} items")

    except Exception as e:
        print(f"[ERROR] Import failed: {e}")
        db.session.rollback()

    input("\nPress Enter...")


def load_csv_items(csv_path: str, user_id: int) -> list:
    """Load and parse CSV items for specific user."""
    items = []

    with open(csv_path, "r", encoding="utf-8") as f:
        # Auto-detect CSV delimiter
        sample = f.read(1024)
        f.seek(0)
        delimiter = csv.Sniffer().sniff(sample).delimiter

        reader = csv.DictReader(f, delimiter=delimiter)

        for row_num, row in enumerate(reader, 2):
            try:
                # Skip other users
                if int(row.get("user_id", 0)) != user_id:
                    continue

                # Build item data
                item_data = {"user_id": user_id, "name": row["name"].strip()}

                # Add optional fields if present
                optional_fields = {
                    "upc": str,
                    "active": lambda x: x.lower() in ("true", "1", "yes"),
                    "increments": str,
                    "image": str,
                    "min_quantity": int,
                    "max_quantity": int,
                    "batch_size": int,
                    "expiration_days": int,
                    "restock_delivery_days": int,
                    "prior_daily_usage": float,
                    "tag_ids": parse_tag_ids,
                }

                for field, converter in optional_fields.items():
                    if field in row and row[field].strip():
                        try:
                            item_data[field] = converter(row[field].strip())
                        except (ValueError, TypeError):
                            print(f"[WARNING] Row {row_num}: Invalid {field} value '{row[field]}', skipping")

                items.append(item_data)

            except (ValueError, KeyError) as e:
                print(f"[WARNING] Row {row_num}: {e}, skipping")

    return items


def parse_tag_ids(tag_str: str) -> list:
    """Parse tag_ids JSON string to list of integers."""
    if not tag_str:
        return []
    try:
        # Handle quoted JSON
        if tag_str.startswith('"') and tag_str.endswith('"'):
            tag_str = tag_str[1:-1]
        parsed = json.loads(tag_str)
        return [int(x) for x in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def view_items(user):
    """View all items for a user."""
    items = Items.query.filter_by(user_id=user.id).order_by(Items.name).all()

    select_from_list(
        items,
        lambda item, i: print(f"{i}. {item.name} (UPC: {item.upc or 'Auto'})"),
        f"ITEMS FOR {user.display_name.upper()}",
    )


def add_item(user):
    """Add new item - validation handled by model."""
    print_header(f"ADD ITEM FOR {user.display_name.upper()}")

    # Required fields
    name = get_input("Item name: ")
    if not name:
        return

    # Optional fields with smart defaults
    print("\nOptional fields (press Enter to skip):")

    upc = get_input("UPC (12 digits, or Enter for auto): ") or None
    increments = get_input("Increments (individual, box, case, etc.): ") or None
    image = get_input("Image URL: ") or None

    # Quantity fields
    min_qty = get_input("Minimum quantity: ")
    min_quantity = int(min_qty) if min_qty and min_qty.isdigit() else None

    max_qty = get_input("Maximum quantity: ")
    max_quantity = int(max_qty) if max_qty and max_qty.isdigit() else None

    batch_sz = get_input("Batch size: ")
    batch_size = int(batch_sz) if batch_sz and batch_sz.isdigit() else None

    exp_days = get_input("Expiration days: ")
    expiration_days = int(exp_days) if exp_days and exp_days.isdigit() else None

    delivery_days = get_input("Restock delivery days: ")
    restock_delivery_days = int(delivery_days) if delivery_days and delivery_days.isdigit() else None

    # Tag IDs (simplified - just enter comma-separated IDs)
    tag_input = get_input("Tag IDs (comma-separated, e.g. '1,2,3'): ")
    tag_ids = []
    if tag_input:
        try:
            tag_ids = [int(x.strip()) for x in tag_input.split(",") if x.strip().isdigit()]
        except ValueError:
            print("[WARNING] Invalid tag IDs, using none")

    # Build item data
    item_data = {
        "user_id": user.id,
        "name": name,
        "upc": upc,
        "increments": increments,
        "image": image,
        "min_quantity": min_quantity,
        "max_quantity": max_quantity,
        "batch_size": batch_size,
        "expiration_days": expiration_days,
        "restock_delivery_days": restock_delivery_days,
        "tag_ids": tag_ids,
    }

    # Remove None values
    item_data = {k: v for k, v in item_data.items() if v is not None}

    # Create item - model handles validation
    item, error = create_with_validation(Items, **item_data)
    if error:
        print(f"\n[ERROR] {error}")

    input("\nPress Enter to continue...")


def delete_item(user):
    """Delete item."""
    items = Items.query.filter_by(user_id=user.id).order_by(Items.name).all()

    selected = select_from_list(
        items,
        lambda item, i: print(f"{i}. {item.name} (UPC: {item.upc or 'Auto'})"),
        f"DELETE ITEM FOR {user.display_name.upper()}",
    )

    if not selected:
        return

    def check_usage(item):
        """Check if item is used in action logs."""
        from app.inventory.models import ActionLogs

        logs = ActionLogs.query.filter_by(item_id=item.id).first()

        if logs:
            print(
                f"\n[WARNING] This item has {ActionLogs.query.filter_by(item_id=item.id).count()} action log entries."
            )
            print("Deleting may cause issues with inventory tracking.")
            return get_yes_no("Are you SURE you want to delete?")
        return True

    delete_with_confirmation(selected, check_usage)
    input("\nPress Enter to continue...")


def user_item_menu(user):
    """Item management for specific user."""
    options = {
        "1": ("View Items", lambda: view_items(user)),
        "2": ("Add Item", lambda: add_item(user)),
        "3": ("Delete Item", lambda: delete_item(user)),
        "4": ("Import Items from CSV", lambda: import_items_for_user(user)),
        "5": ("Return to Main Menu", lambda: True),
    }

    run_menu(f"ITEM MANAGEMENT FOR {user.display_name.upper()}", options)


def import_items_for_user(user):
    """Import items for specific user (wrapper for existing function)."""
    print_header("IMPORT ITEMS FROM CSV")
    print(f"Import items for user: {user.display_name}")
    print("\nRequired CSV columns: user_id, name")
    print(
        "Optional: upc, active, tag_ids, increments, image, min_quantity, max_quantity, batch_size, expiration_days, restock_delivery_days"
    )
    print("\nExample:")
    print("user_id,name,increments,tag_ids,min_quantity")
    print(f'{user.id},Bandage,individual,"[1,2]",10\n')

    # Get CSV file path
    csv_path = get_input("CSV file path: ")
    if not csv_path or not Path(csv_path).exists():
        print(f"[ERROR] File not found: {csv_path}")
        input("Press Enter...")
        return

    try:
        # Load CSV data
        items_data = load_csv_items(csv_path, user.id)
        if not items_data:
            print(f"[WARNING] No items found for user {user.id}")
            input("Press Enter...")
            return

        current_count = Items.query.filter_by(user_id=user.id).count()
        print(f"\n[INFO] Found {len(items_data)} items in CSV")
        print(f"[WARNING] This will DELETE {current_count} existing items")

        if not get_yes_no("Continue with import?"):
            return

        # Delete existing and create new
        print("\n[INFO] Starting import...")

        # Delete all user's items
        deleted = Items.query.filter_by(user_id=user.id).delete()
        print(f"Deleted {deleted} existing items")

        # Create new items using model validation
        created = 0
        failed = 0

        for item_data in items_data:
            item, error = create_with_validation(Items, **item_data)
            if item:
                created += 1
            else:
                print(f"[ERROR] Failed to create '{item_data.get('name')}': {error}")
                failed += 1

        print("\n[SUCCESS] Import complete!")
        print(f"- Created: {created} items")
        print(f"- Failed: {failed} items")

    except Exception as e:
        print(f"[ERROR] Import failed: {e}")
        db.session.rollback()

    input("\nPress Enter...")


@ensure_app_context
def main():
    """Main item management menu."""

    def select_and_manage():
        user = select_user()
        if user:
            user_item_menu(user)

    def exit_program():
        from scripts.utils import clear_screen

        clear_screen()
        print("Exiting item management. Goodbye!")
        return True

    options = {
        "1": ("Select User", select_and_manage),
        "2": ("Import Items from CSV (Legacy)", import_items),
        "3": ("Exit", exit_program),
    }

    run_menu("ITEM MANAGEMENT", options)


if __name__ == "__main__":
    main()
