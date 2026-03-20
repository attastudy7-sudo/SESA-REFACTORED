import sqlite3
import os

db_path = "instance/sesa_dev.db"

if not os.path.exists(db_path):
    print("ERROR: sesa.db not found. Run this from your project root folder.")
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    cur.execute("DELETE FROM alembic_version")
    cur.execute("INSERT INTO alembic_version (version_num) VALUES ('0001_fresh_schema')")
    conn.commit()
    conn.close()
    print("Done — alembic_version stamped to 0001_fresh_schema")
    print("Now run: flask db upgrade")