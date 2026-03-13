"""
Migration script for SESA improvement plan changes.
Run once: python migrate_improvements.py

Adds:
  - accounts.class_group   VARCHAR(50)
  - school.access_code     VARCHAR(8) UNIQUE
  - school.qr_token        VARCHAR(64) UNIQUE
"""
import sqlite3, os

DB_PATH = os.environ.get('DATABASE_PATH', 'instance/sesa_dev.db')

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    migrations = [
        ('accounts', 'class_group',  'ALTER TABLE accounts ADD COLUMN class_group VARCHAR(50)'),
        ('school',   'access_code',  'ALTER TABLE school ADD COLUMN access_code VARCHAR(8)'),
        ('school',   'qr_token',     'ALTER TABLE school ADD COLUMN qr_token VARCHAR(64)'),
    ]

    for table, col, sql in migrations:
        if not column_exists(cur, table, col):
            cur.execute(sql)
            print(f'  ✅  Added {table}.{col}')
        else:
            print(f'  ⏭️   {table}.{col} already exists')

    conn.commit()
    conn.close()
    print('\nMigration complete.')

if __name__ == '__main__':
    run()
