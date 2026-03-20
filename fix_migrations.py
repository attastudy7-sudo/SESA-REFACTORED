"""
Run this from your project root (same folder as main.py):
    python fix_migrations.py

What it does:
  1. Finds your local sesa.db
  2. Checks what revision alembic thinks it's on
  3. Stamps it to the latest revision that actually exists in migrations/versions/
  4. Prints what it did so you can verify
"""

import os
import sqlite3
import glob

DB_PATH = "sesa.db"
VERSIONS_DIR = os.path.join("migrations", "versions")


def get_migration_files():
    """Return all revision IDs from migration filenames."""
    pattern = os.path.join(VERSIONS_DIR, "*.py")
    files = [f for f in glob.glob(pattern) if not f.endswith("__pycache__")]
    revisions = []
    for f in files:
        basename = os.path.basename(f)
        if basename.startswith("__"):
            continue
        rev_id = basename.split("_")[0]
        if len(rev_id) >= 8:  # valid revision hash
            revisions.append((rev_id, basename))
    return revisions


def find_head(revisions):
    """Find the head revision by reading down_revision chains."""
    import importlib.util

    rev_map = {}
    for rev_id, filename in revisions:
        path = os.path.join(VERSIONS_DIR, filename)
        spec = importlib.util.spec_from_file_location("migration", path)
        mod  = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            down = getattr(mod, "down_revision", None)
            rev_map[rev_id] = down
        except Exception:
            rev_map[rev_id] = None

    # Head = revision that nothing points to as a down_revision
    all_downs = set(rev_map.values()) - {None}
    for rev_id in rev_map:
        if rev_id not in all_downs:
            return rev_id
    return list(rev_map.keys())[-1]


def fix():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Make sure you run this from your project root.")
        return

    if not os.path.exists(VERSIONS_DIR):
        print(f"ERROR: {VERSIONS_DIR} not found. Make sure you run this from your project root.")
        return

    revisions = get_migration_files()
    if not revisions:
        print("ERROR: No migration files found in migrations/versions/")
        return

    print(f"Found {len(revisions)} migration files:")
    for rev_id, fname in revisions:
        print(f"  {rev_id}  {fname}")

    head = find_head(revisions)
    print(f"\nDetected head revision: {head}")

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Check current alembic_version
    try:
        cur.execute("SELECT version_num FROM alembic_version")
        rows = cur.fetchall()
        print(f"Current alembic_version in DB: {rows}")
    except sqlite3.OperationalError:
        print("alembic_version table does not exist — will create it.")
        rows = []

    # Stamp to head
    if rows:
        cur.execute("DELETE FROM alembic_version")
    else:
        cur.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")

    cur.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (head,))
    conn.commit()
    conn.close()

    print(f"\nDone. alembic_version stamped to: {head}")
    print("You can now run:  flask db upgrade")
    print("(It should say 'Running upgrade ... -> ...' or 'Nothing to do.')")


if __name__ == "__main__":
    fix()