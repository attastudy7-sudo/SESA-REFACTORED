"""
Run from your project root:
    python export_questions.py

Reads directly from instance/sesa_dev.db — no Flask needed.
Creates questions_export.sql in the same folder.
"""

import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'sesa_dev.db')

if not os.path.exists(db_path):
    print(f"Database not found at: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='question'")
if not cursor.fetchone():
    print("No 'question' table found in the database.")
    print("Available tables:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for row in cursor.fetchall():
        print(f"  - {row[0]}")
    conn.close()
    exit(1)

cursor.execute("SELECT test_type, question_content FROM question ORDER BY id")
questions = cursor.fetchall()
conn.close()

if not questions:
    print("The question table is empty.")
    exit(0)

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'questions_export.sql')

with open(output_path, 'w', encoding='utf-8') as f:
    f.write('-- SESA Question Export\n')
    f.write('-- Paste into Neon SQL Editor and run\n\n')
    for test_type, content in questions:
        test_type = test_type.replace("'", "''")
        content   = content.replace("'", "''")
        f.write(
            f"INSERT INTO question (test_type, question_content, created_at) "
            f"VALUES ('{test_type}', '{content}', NOW());\n"
        )

print(f"✓ Exported {len(questions)} questions to: {output_path}")