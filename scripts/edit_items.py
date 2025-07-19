#!/usr/bin/env python3
"""
edit_items.py - Script to import items from CSV in the InventoryIQ system
"""

import csv
import json
from pathlib import Path

from app import db
from app.inventory.models import Items
from scripts.utils import (
    clear_screen,
    confirm_action,
    ensure_app_context,
    print_header,
    prompt_for_integer,
    prompt_for_string,
    select_user,
)


def validate_csv_headers(headers):
    """Validate that required headers are present."""
    required_headers = {"user_id", "name"}
    optional_headers = {
        "upc", "active", "tag_ids", "increments", "image", 
        "min_quantity", "max_quantity", "batch_size", 
        "expiration_days", "restock_delivery_days"
    }

    headers_set = set(headers)

    # Check required headers
    missing_required = required_headers - headers_set
    if missing_required:
        raise ValueError(f"Missing required CSV headers: {missing_required}")

    # Check for invalid headers
    valid_headers = required_headers | optional_headers
    invalid_headers = headers_set - valid_headers
    if invalid_headers:
        print(f"[WARNING] Unknown CSV headers will be ignored: {invalid_headers}")

    print(f"[INFO] CSV headers validated. Found: {list(headers_set)}")


def parse_tag_ids(tag_ids_str):
    """Parse tag_ids from string to list."""
    if not tag_ids_str or tag_ids_str.strip() == "":
        return []

    try:
        # Handle both quoted and unquoted JSON arrays
        tag_ids_str = tag_ids_str.strip()
        if tag_ids_str.startswith('"') and tag_ids_str.endswith('"'):
            tag_ids_str = tag_ids_str[1:-1]  # Remove outer quotes

        parsed = json.loads(tag_ids_str)
        if not isinstance(parsed, list):
            raise ValueError("tag_ids must be a JSON array")

        # Ensure all items are integers
        return [int(tag_id) for tag_id in parsed]
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[WARNING] Invalid tag_ids format '{tag_ids_str}', using empty list. Error: {e}")
        return []


def parse_boolean(value):
    """Parse boolean value from CSV string."""
    if not value or value.strip() == "":
        return True  # Default to True if empty

    value = value.strip().lower()
    if value in ("true", "1", "yes", "y"):
        return True
    elif value in ("false", "0", "no", "n"):
        return False
    else:
        print(f"[WARNING] Invalid boolean value '{value}', defaulting to True")
        return True


def parse_integer(value, field_name):
    """Parse positive integer value from CSV string."""
    if not value or value.strip() == "":
        return None  # Return None for empty values
    
    try:
        parsed_value = int(value.strip())
        if parsed_value < 0:
            print(f"[WARNING] Negative value '{value}' for {field_name}, using None")
            return None
        return parsed_value
    except ValueError:
        print(f"[WARNING] Invalid integer value '{value}' for {field_name}, using None")
        return None


def load_items_from_csv(csv_file_path, target_user_id):
    """Load items from CSV file and return list of item dictionaries for the target user."""
    items = []

    with open(csv_file_path, "r", newline="", encoding="utf-8") as csvfile:
        # Detect delimiter
        sample = csvfile.read(1024)
        csvfile.seek(0)
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(sample).delimiter

        reader = csv.DictReader(csvfile, delimiter=delimiter)

        # Validate headers
        validate_csv_headers(reader.fieldnames)

        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Parse required fields
                user_id = int(row["user_id"])
                name = row["name"].strip()

                # Skip rows for different users
                if user_id != target_user_id:
                    continue

                if not name:
                    print(f"[WARNING] Row {row_num} has empty name, skipping")
                    continue

                # Build item dictionary with required fields
                item_data = {"user_id": user_id, "name": name}

                # Parse optional fields
                if "upc" in row and row["upc"].strip():
                    item_data["upc"] = row["upc"].strip()

                if "active" in row:
                    item_data["active"] = parse_boolean(row["active"])

                if "tag_ids" in row:
                    item_data["tag_ids"] = parse_tag_ids(row["tag_ids"])

                if "increments" in row and row["increments"].strip():
                    item_data["increments"] = row["increments"].strip()

                if "image" in row and row["image"].strip():
                    item_data["image"] = row["image"].strip()

                # Parse integer fields
                if "min_quantity" in row:
                    item_data["min_quantity"] = parse_integer(row["min_quantity"], "min_quantity")

                if "max_quantity" in row:
                    item_data["max_quantity"] = parse_integer(row["max_quantity"], "max_quantity")

                if "batch_size" in row:
                    item_data["batch_size"] = parse_integer(row["batch_size"], "batch_size")

                if "expiration_days" in row:
                    item_data["expiration_days"] = parse_integer(row["expiration_days"], "expiration_days")

                if "restock_delivery_days" in row:
                    item_data["restock_delivery_days"] = parse_integer(row["restock_delivery_days"], "restock_delivery_days")

                items.append(item_data)

            except ValueError as e:
                print(f"[ERROR] Error parsing row {row_num}: {e}")
                continue
            except Exception as e:
                print(f"[ERROR] Unexpected error parsing row {row_num}: {e}")
                continue

    return items


def delete_user_items(user_id):
    """Delete all existing items for a specific user."""
    try:
        deleted_count = db.session.query(Items).filter_by(user_id=user_id).delete()
        print(f"[INFO] Deleted {deleted_count} existing items for user {user_id}")
        return deleted_count
    except Exception as e:
        print(f"[ERROR] Error deleting existing items: {e}")
        raise


def create_items_from_data(items_data):
    """Create new items from parsed data."""
    created_count = 0
    failed_count = 0
    used_upcs = set()  # Track UPCs generated in this session

    for item_data in items_data:
        try:
            # Generate UPC manually if not provided
            if 'upc' not in item_data or not item_data['upc']:
                item_data['upc'] = generate_unique_upc(item_data['user_id'], used_upcs)
                used_upcs.add(item_data['upc'])
            
            item = Items(**item_data)
            db.session.add(item)
            created_count += 1
        except Exception as e:
            print(f"[ERROR] Error creating item '{item_data.get('name', 'Unknown')}': {e}")
            failed_count += 1
            continue

    return created_count, failed_count


def generate_unique_upc(user_id, used_upcs):
    """Generate a unique UPC that doesn't conflict with existing or recently generated ones."""
    from app.inventory.models import Items
    
    halfway_point = "500000000000"  # start auto-generation at halfway point
    max_attempts = 1000
    
    # Get the largest existing UPC from database
    largest_upc = (
        Items.query.filter(Items.user_id == user_id, Items.upc >= halfway_point)
        .order_by(Items.upc.desc()).first()
    )

    if largest_upc:
        base_11 = largest_upc.upc[:11]  # Remove check digit
        next_number = int(base_11) + 1
    else:
        next_number = int(halfway_point[:11])

    for attempt in range(max_attempts):
        next_base = str(next_number + attempt).zfill(11)
        check_digit = Items.calculate_upc_check_digit(next_base)
        new_upc = next_base + check_digit
        
        # Check if this UPC exists in database OR in our current session
        if (not Items.query.filter_by(upc=new_upc).first() and 
            new_upc not in used_upcs):
            return new_upc
    
    raise ValueError(f"Could not generate unique UPC after {max_attempts} attempts")


def import_items():
    """Import items from CSV file."""
    print_header("IMPORT ITEMS FROM CSV")
    print("This utility will replace ALL items for a selected user with items from a CSV file.")
    print("\nCSV Format:")
    print("Required columns: user_id, name")
    print("Optional columns: upc, active, tag_ids, increments, image,")
    print("                 min_quantity, max_quantity, batch_size,")
    print("                 expiration_days, restock_delivery_days")
    print("\nExample CSV:")
    print("user_id,name,increments,tag_ids,active,min_quantity,max_quantity,batch_size")
    print('1,Bandage,individual,"[1,2]",true,10,50,20')
    print('1,Aspirin,bottle,"[3]",true,5,100,25\n')

    # Select user
    user = select_user()
    if not user:
        return

    print(f"\nSelected user: {user.display_name} ({user.email})")

    # Get CSV file path
    csv_file_path = prompt_for_string("Enter path to CSV file: ")
    if csv_file_path == "q":
        return

    # Check if file exists
    if not Path(csv_file_path).exists():
        print(f"[ERROR] CSV file '{csv_file_path}' not found!")
        input("Press Enter to continue...")
        return

    try:
        print(f"\n[INFO] Loading items from CSV: {csv_file_path}")
        items_data = load_items_from_csv(csv_file_path, user.id)

        if not items_data:
            print(f"[WARNING] No items found for user {user.id} in CSV file")
            input("Press Enter to continue...")
            return

        print(f"[INFO] Found {len(items_data)} items for user {user.display_name}")

        # Show current item count
        current_count = db.session.query(Items).filter_by(user_id=user.id).count()
        print(f"[INFO] User currently has {current_count} items")

        # Confirmation
        print(f"\n[WARNING] This will DELETE ALL {current_count} existing items for {user.display_name}")
        print(f"[INFO] And replace them with {len(items_data)} items from the CSV")

        if not confirm_action("Continue with import?"):
            print("Import cancelled.")
            return

        # Start transaction
        print("\n[INFO] Starting database transaction...")

        # Delete all existing items for this user
        print(f"[INFO] Deleting existing items for {user.display_name}...")
        deleted_count = delete_user_items(user.id)

        # Create new items
        print("[INFO] Creating new items...")
        created_count, failed_count = create_items_from_data(items_data)

        # Commit the transaction
        db.session.commit()

        print("\n[SUCCESS] ✅ Import completed successfully!")
        print(f"- Deleted: {deleted_count} existing items")
        print(f"- Created: {created_count} new items")
        if failed_count > 0:
            print(f"- Failed: {failed_count} items (see errors above)")

        # Show UPC generation results
        items_without_upc = db.session.query(Items).filter(Items.user_id == user.id, Items.upc.is_(None)).count()
        items_with_upc = db.session.query(Items).filter(Items.user_id == user.id, Items.upc.isnot(None)).count()
        print(f"- Items with UPC: {items_with_upc}")
        print(f"- Items without UPC (duplicates or generation failed): {items_without_upc}")

        input("\nPress Enter to continue...")

    except Exception as e:
        print(f"[ERROR] Import failed: {e}")
        db.session.rollback()
        input("\nPress Enter to continue...")


@ensure_app_context
def main():
    """Main function for the item import script."""
    while True:
        print_header("ITEM MANAGEMENT")
        print("1. Import Items from CSV")
        print("2. Exit")

        choice = prompt_for_integer("\nEnter your choice (1-2): ", 1, 2)

        if choice == 1:
            import_items()
        elif choice == 2 or choice == -1:
            clear_screen()
            print("Exiting item management. Goodbye!")
            break


if __name__ == "__main__":
    main()
