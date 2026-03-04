# migrate.py
import sqlite3
import os

# Find the correct db path
possible_paths = [
    'instance/sesa.db',
    'sesa.db',
    'instance/sesa_dev.db',
    'sesa_dev.db',
]

db_path = None
for path in possible_paths:
    if os.path.exists(path):
        print(f'Found database at: {path}')
        db_path = path
        break

if not db_path:
    print('ERROR: Could not find database file!')
    exit(1)

conn = sqlite3.connect(db_path)

# Check existing columns first
cursor = conn.execute('PRAGMA table_info(school)')
existing = [row[1] for row in cursor.fetchall()]
print(f'Existing columns: {existing}')

try:
    conn.execute('ALTER TABLE school ADD COLUMN paystack_reference VARCHAR(100);')
    print('Added paystack_reference')
except Exception as e:
    print(f'paystack_reference skipped: {e}')

try:
    conn.execute('ALTER TABLE school ADD COLUMN payment_date DATETIME;')
    print('Added payment_date')
except Exception as e:
    print(f'payment_date skipped: {e}')

conn.commit()

# Confirm
cursor = conn.execute('PRAGMA table_info(school)')
final = [row[1] for row in cursor.fetchall()]
print(f'Final columns: {final}')

conn.close()
print('Done!')