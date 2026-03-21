"""Temporary script to check DB state for migration 20260321_01."""

import os

try:
    import psycopg2

    conn = psycopg2.connect(os.environ.get("DATABASE_PUBLIC_URL", os.environ["DATABASE_URL"]))
except ImportError:
    import psycopg

    conn = psycopg.connect(os.environ.get("DATABASE_PUBLIC_URL", os.environ["DATABASE_URL"]))
cur = conn.cursor()

cur.execute(
    "SELECT typname FROM pg_type WHERE typname IN "
    "('ea_class_enum','ea_subtype_enum','execution_mode_enum',"
    "'reporter_mode_enum','ea_agent_status')"
)
enums = cur.fetchall()
print("=== ENUMS ===")
for row in enums:
    print(f"  {row[0]}")
if not enums:
    print("  (none)")

cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'ea_%'")
tables = cur.fetchall()
print("=== EA TABLES ===")
for row in tables:
    print(f"  {row[0]}")
if not tables:
    print("  (none)")

cur.execute("SELECT version_num FROM alembic_version")
versions = cur.fetchall()
print("=== ALEMBIC VERSION ===")
for row in versions:
    print(f"  {row[0]}")

conn.close()
