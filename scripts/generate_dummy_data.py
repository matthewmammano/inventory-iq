#!/usr/bin/env python3
"""
Dummy Data Generation Script

This script generates dummy data for all models in PostgreSQL for testing purposes.
Can be run manually in both dev and prod environments when needed.

Usage:
    python scripts/generate_dummy_data.py [--users=5] [--items=20]
"""

import argparse
import sys

from app import create_app, db

# TODO ORANGE: make this work now to generate dummy data!

# from app.auth.models import Users, UserEmails, UserAlerts, UserItemLocations, UserItemTags
# from app.inventory.models import Items, ActionLogs, ItemLocationQuantities


def generate_dummy_data(num_users: int = 5, items_per_user: int = 20) -> None:
    """
    Generate comprehensive dummy data for all models.

    Parameters
    ----------
    num_users : int
        Number of users to create (default: 5)
    items_per_user : int
        Average number of items per user (default: 20)
    """
    print(f"[INFO] Would generate dummy data with {num_users} users and ~{items_per_user} items each")
    print("[INFO] Implementation TODO: pass for now")

    # TODO: Pass for now - implement full dummy data generation
    pass

    # Future implementation will include:
    # - Create dummy Users with realistic names and settings
    # - Create UserEmails for each user
    # - Create UserAlerts with varied alert preferences
    # - Create UserItemLocations (storage areas)
    # - Create UserItemTags for categorization
    # - Create Items with varied types, quantities, and metadata
    # - Create ActionLogs for realistic transaction history
    # - Create ItemLocationQuantities for current stock levels


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Generate dummy data for testing")
    parser.add_argument("--users", type=int, default=5, help="Number of users to create")
    parser.add_argument("--items", type=int, default=20, help="Items per user")

    args = parser.parse_args()

    try:
        print("[INFO] Initializing Flask application...")
        app = create_app()

        with app.app_context():
            print(f"[INFO] Connected to database: {db.engine.url}")
            generate_dummy_data(args.users, args.items)
            print("[INFO] Script completed successfully")
            return 0

    except Exception as e:
        print(f"[ERROR] Script failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
