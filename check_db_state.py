"""
check_db_migration_state.py
────────────────────────────
Run this BEFORE upgrading to confirm your database's current migration state.

Usage:
    python check_db_migration_state.py --url postgresql://user:pass@host/dbname

Or set DATABASE_URL env var and run:
    python check_db_migration_state.py
"""

import os
import sys
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor

EXPECTED_CHAIN = [
    ("3e9d32f2cbbe", "initial_migration"),
    ("4838ee558eeb", "add_counsellor_role_phone_audit_log"),
    ("b9900ac3e06c", "subscription_expiry_date"),
    ("c1a3f7e92d04", "account_lockout"),   # <-- the new one
]

def get_url(args):
    url = args.url or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: Provide --url or set DATABASE_URL env var.")
        sys.exit(1)
    # Render sometimes gives 'postgres://' which psycopg2 requires as 'postgresql://'
    return url.replace("postgres://", "postgresql://", 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="PostgreSQL connection URL")
    args = parser.parse_args()
    url = get_url(args)

    print("Connecting to database…")
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # 1. Check alembic_version table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'alembic_version'
        ) AS exists;
    """)
    if not cur.fetchone()["exists"]:
        print("\n⚠️  alembic_version table does NOT exist — database has never been migrated.")
        conn.close()
        return

    # 2. Get current revision(s)
    cur.execute("SELECT version_num FROM alembic_version;")
    rows = cur.fetchall()
    current_revisions = [r["version_num"] for r in rows]
    print(f"\n📌 Current alembic revision(s) in DB: {current_revisions}")

    # 3. Compare against expected chain
    print("\n📋 Expected migration chain:")
    for rev_id, name in EXPECTED_CHAIN:
        applied = rev_id in current_revisions
        status = "✅ applied" if applied else "⏳ pending"
        # Mark the head
        is_head = (rev_id == EXPECTED_CHAIN[-1][0])
        head_tag = " ← HEAD" if is_head else ""
        print(f"   {rev_id}  {name:<45} {status}{head_tag}")

    # 4. Check for account lockout columns (the migration we're fixing)
    print("\n🔍 Checking for account_lockout columns in DB…")
    for table in ("accounts", "school"):
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s AND column_name IN ('failed_attempts', 'locked_until');
        """, (table,))
        found = [r["column_name"] for r in cur.fetchall()]
        if len(found) == 2:
            print(f"   ✅ {table}: failed_attempts + locked_until both present")
        elif len(found) == 0:
            print(f"   ⏳ {table}: columns NOT yet added (migration pending)")
        else:
            print(f"   ⚠️  {table}: partial columns found: {found}")

    conn.close()
    print("\nDone. If any migrations show ⏳, run: flask db upgrade")

if __name__ == "__main__":
    main()