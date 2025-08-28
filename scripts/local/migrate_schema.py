"""Customizable database schema migration script for Railway PostgreSQL."""

import sys

try:
    import psycopg2
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary")
    sys.exit(1)


def apply_schema_migrations(cursor, conn) -> None:
    """
    ADD YOUR SCHEMA CHANGES HERE

    Each cursor.execute() should be one ALTER TABLE statement.
    Add as many as needed for your schema changes.
    """

    # MIGRATION 1: Change password column to TEXT
    print("  - Changing users.password to TEXT...")
    cursor.execute("ALTER TABLE users ALTER COLUMN password TYPE TEXT;")

    # MIGRATION 2: Add more changes here as needed
    # print("  - Adding new column...")
    # cursor.execute("ALTER TABLE items ADD COLUMN new_field TEXT;")

    # MIGRATION 3: Modify other columns
    # print("  - Changing column type...")
    # cursor.execute("ALTER TABLE items ALTER COLUMN description TYPE TEXT;")

    # MIGRATION 4: Create indexes
    # print("  - Creating index...")
    # cursor.execute("CREATE INDEX idx_users_email ON users(email);")

    # Commit all changes together
    conn.commit()


def verify_migrations(cursor) -> None:
    """
    ADD YOUR VERIFICATION CHECKS HERE

    Check that your schema changes were applied correctly.
    """

    # VERIFICATION 1: Check password column type
    print("Verifying schema changes...")
    cursor.execute("""
        SELECT column_name, data_type, character_maximum_length 
        FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'password'
    """)

    result = cursor.fetchone()
    if result:
        col_name, data_type, max_length = result
        print(f"  ✓ users.password: {data_type} (max_length: {max_length})")

    # VERIFICATION 2: Add more checks as needed
    # cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'items' AND column_name = 'new_field'")
    # if cursor.fetchone():
    #     print("  ✓ items.new_field: exists")

    # VERIFICATION 3: Check constraints, indexes, etc.
    # cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'users' AND indexname = 'idx_users_email'")
    # if cursor.fetchone():
    #     print("  ✓ idx_users_email: created")


def migrate_schema(database_url: str) -> None:
    """Execute schema migrations with rollback on failure."""

    print("Connecting to database...")
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()

    try:
        print("Applying migrations...")
        apply_schema_migrations(cursor, conn)

        verify_migrations(cursor)

        print("Schema migration completed successfully!")

    except Exception as e:
        print(f"Migration failed, rolling back: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def main():
    print("Railway PostgreSQL Schema Migrator")
    print("=" * 40)

    database_url = input("Database URL: ").strip()

    if not database_url:
        print("Database URL is required")
        return

    try:
        migrate_schema(database_url)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
