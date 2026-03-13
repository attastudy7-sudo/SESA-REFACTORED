import sqlite3

conn = sqlite3.connect('instance/sesa_dev.db')
conn.execute("UPDATE alembic_version SET version_num = '3e9d32f2cbbe'")
conn.commit()
conn.close()
print('Done')