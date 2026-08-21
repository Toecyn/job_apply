"""
One-time migration: copy all rows from local tracker.db (SQLite) into the
hosted Postgres DB pointed to by DATABASE_URL.

Run once, after DATABASE_URL is set in .env:
    python migrate_to_postgres.py
"""
import os
import sqlite3
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = "tracker.db"

TABLES = ["jobs", "applied_companies", "ai_calls", "batch_jobs"]


def get_sqlite_rows(table):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def migrate_table(pg_conn, table):
    rows = get_sqlite_rows(table)
    if not rows:
        print(f"  {table}: 0 rows in tracker.db, skipping")
        return 0

    columns = list(rows[0].keys())
    values = [[row[c] for c in columns] for row in rows]

    col_list = ", ".join(columns)
    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO {table} ({col_list}) VALUES %s ON CONFLICT DO NOTHING",
            values
        )
        if "id" in columns and table == "applied_companies":
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('applied_companies', 'id'), "
                "COALESCE((SELECT MAX(id) FROM applied_companies), 1))"
            )
    pg_conn.commit()
    print(f"  {table}: inserted up to {len(rows)} rows")
    return len(rows)


def main():
    with open("schema.sql") as f:
        schema = f.read()

    pg_conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with pg_conn.cursor() as cur:
        cur.execute(schema)
    pg_conn.commit()
    print("Schema ensured in Postgres.\n")

    print("Migrating tables...")
    for table in TABLES:
        migrate_table(pg_conn, table)

    print("\nVerifying row counts...")
    with pg_conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            pg_count = cur.fetchone()[0]
            sqlite_count = len(get_sqlite_rows(table))
            match = "OK" if pg_count == sqlite_count else "MISMATCH"
            print(f"  {table}: sqlite={sqlite_count} postgres={pg_count} [{match}]")

    pg_conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
