import sqlite3
import os

# Find the db file
db_path = 'instance/sesa_dev.db'

if not os.path.exists(db_path):
    print(f"ERROR: Could not find DB at '{db_path}'")
    print("Searching for .db files...")
    for root, dirs, files in os.walk('.'):
        for f in files:
            if f.endswith('.db'):
                print(f"  Found: {os.path.join(root, f)}")
    print("\nRe-run this script after updating db_path at the top.")
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT version_num FROM alembic_version;")
    current = cur.fetchone()
    print(f"Current revision: {current}")

    cur.execute("UPDATE alembic_version SET version_num = 'b9900ac3e06c';")
    conn.commit()

    cur.execute("SELECT version_num FROM alembic_version;")
    updated = cur.fetchone()
    print(f"Updated revision: {updated}")

    conn.close()
    print("Done! Now run: flask db upgrade")