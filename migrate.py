# copy_to_neon.py
import os
import sqlite3
from dotenv import load_dotenv
load_dotenv()

import psycopg2

# ── Source: the uploaded sesa_dev.db ─────────────────────────────────────────
# Put this file in your project root first
LOCAL_DB = 'C:\\Users\\ANONYMOUS\\Desktop\\Dev Projects\\Python Projects\\SESA_refactored\\instance\\sesa_dev.db'

# ── Target: Neon ──────────────────────────────────────────────────────────────
NEON_URL = os.environ.get('DATABASE_URL', '')
if not NEON_URL or 'sqlite' in NEON_URL:
    print('ERROR: DATABASE_URL not pointing to Neon in .env')
    exit(1)

# Read from local SQLite
local = sqlite3.connect(LOCAL_DB)
questions = local.execute('SELECT id, test_type, question_content, created_at FROM question').fetchall()
accounts  = local.execute('SELECT id, fname, lname, email, username, password, level, gender, birthdate, last_login, created_at, school_id, is_admin FROM accounts').fetchall()
local.close()
print(f'Read {len(questions)} questions and {len(accounts)} accounts from local db')

# Write to Neon
conn = psycopg2.connect(NEON_URL)
cur = conn.cursor()

try:
    # Questions
    cur.execute('DELETE FROM question')
    for q in questions:
        cur.execute(
            'INSERT INTO question (id, test_type, question_content, created_at) VALUES (%s, %s, %s, %s)',
            q
        )
    print(f'Copied {len(questions)} questions')

    # Accounts
    cur.execute('DELETE FROM accounts')
    for a in accounts:
        a = list(a)
        a[12] = bool(a[12])  # convert is_admin 0/1 to False/True
        cur.execute(
            '''INSERT INTO accounts
               (id, fname, lname, email, username, password, level, gender,
                birthdate, last_login, created_at, school_id, is_admin)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            a
        )
    print(f'Copied {len(accounts)} accounts')
    
    conn.commit()
    print('Done! All data committed to Neon.')

except Exception as e:
    conn.rollback()
    print(f'ERROR: {e}')
    raise
finally:
    cur.close()
    conn.close()