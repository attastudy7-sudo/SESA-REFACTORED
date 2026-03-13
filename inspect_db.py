import sqlite3

conn = sqlite3.connect('instance/sesa_dev.db')
cursor = conn.cursor()

print("=== ALL TABLES ===")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for row in cursor.fetchall():
    print(" ", row[0])

print("\n=== ALL INDEXES ===")
cursor.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name")
for row in cursor.fetchall():
    print(f"  {row[1]}.{row[0]}")

print("\n=== accounts columns ===")
cursor.execute("PRAGMA table_info(accounts)")
for row in cursor.fetchall():
    print(" ", row)

print("\n=== school columns ===")
cursor.execute("PRAGMA table_info(school)")
for row in cursor.fetchall():
    print(" ", row)

conn.close()