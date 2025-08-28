"""
Database Import Script

Usage: python db_import.py
"""

import sys

try:
    import psycopg2
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary")
    sys.exit(1)


def import_sql(database_url: str, sql_file: str) -> None:
    """Import SQL file to database."""

    # Read SQL file
    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print("Connecting to database...")
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()

    # Split into individual statements to check for errors
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    print(f"Validating {len(statements)} SQL statements...")
    errors = []

    # Test each statement with constraints disabled
    for i, statement in enumerate(statements, 1):
        try:
            # Re-disable constraints for each test (rollback resets them)
            cursor.execute("SET session_replication_role = replica;")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED;")
            cursor.execute(statement)
            conn.rollback()  # Don't commit, just test
        except Exception as e:
            errors.append(f"Line {i}: {e}")
            conn.rollback()  # Reset on error

    if errors:
        print("SQL errors found:")
        for error in errors:
            print(f"  {error}")
        print("Import cancelled - fix errors first")
        return

    # If no errors, execute for real
    print("No errors found, executing import...")
    cursor.execute(sql_content)
    conn.commit()

    # Quick verification of all tables
    tables = ["users", "items", "user_item_locations", "user_item_tags"]
    counts = {}

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
        except Exception:
            counts[table] = "missing"

    print("Import complete:")
    for table, count in counts.items():
        print(f"  {table}: {count}")

    cursor.close()
    conn.close()


def main():
    # Prompt for inputs
    database_url = input("Database URL: ").strip()
    sql_file = input("SQL file path: ").strip()

    try:
        import_sql(database_url, sql_file)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
