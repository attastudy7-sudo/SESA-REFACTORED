"""
Run from project root:
    python seed_test_data.py
"""
import os, random, sqlite3
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash

# ── Point directly at the dev database ──────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'sesa_dev.db')

FIRST_NAMES = ['Ama','Kofi','Abena','Kwame','Akosua','Yaw','Efua','Kojo',
               'Adwoa','Kweku','Afua','Kwabena','Afia','Fiifi','Maame',
               'Nana','Esi','Kwesi','Araba','Kwaku','Abiba','Sena','Efia',
               'Dela','Mawuli','Dzifa','Selorm','Kafui','Yayra','Elorm']
LAST_NAMES  = ['Mensah','Asante','Boateng','Owusu','Amoah','Darko','Osei',
               'Frimpong','Adjei','Agyeman','Appiah','Bonsu','Antwi','Ntim',
               'Kyei','Baffour','Sarpong','Poku','Acheampong','Tetteh']

TEST_TYPES = [
    'Separation Anxiety Disorder',
    'Social Phobia',
    'Generalised Anxiety Disorder',
    'Panic Disorder',
    'Obsessive Compulsive Disorder',
    'Major Depressive Disorder',
]

STAGES = [
    ('Normal Stage',   0.45),
    ('Mild Stage',     0.25),
    ('Elevated Stage', 0.18),
    ('Clinical Stage', 0.12),
]

def pick_stage():
    r = random.random()
    cumulative = 0
    for stage, prob in STAGES:
        cumulative += prob
        if r <= cumulative:
            return stage
    return 'Normal Stage'

def score_for_stage(stage):
    if 'Normal'   in stage: return random.randint(0,  12)
    if 'Mild'     in stage: return random.randint(13, 22)
    if 'Elevated' in stage: return random.randint(23, 32)
    return random.randint(33, 40)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# Find the school
cur.execute("SELECT id, school_name FROM school WHERE LOWER(admin_name) LIKE '%hubertadmin%'")
row = cur.fetchone()

if not row:
    print('Could not find hubertadmin school. Schools in DB:')
    for r in cur.execute("SELECT id, school_name, admin_name FROM school").fetchall():
        print(f'  id={r[0]}  name={r[1]}  admin={r[2]}')
    con.close()
    exit(1)

school_id, school_name = row
print(f'Seeding: {school_name} (id={school_id})')

now = datetime.now(timezone.utc)
created_students = 0
created_results  = 0

for i in range(30):
    fname = random.choice(FIRST_NAMES)
    lname = random.choice(LAST_NAMES)
    username = f"{fname.lower()}.{lname.lower()}.seed{i}"

    cur.execute("SELECT id FROM accounts WHERE username = ?", (username,))
    if cur.fetchone():
        continue

    password = generate_password_hash('password123')
    level    = random.choice(['highschool', 'middleschool'])
    gender   = random.choice(['male', 'female'])
    cgroup   = random.choice(['Form 1A', 'Form 2B', 'Form 3C', 'Form 1B'])
    created  = (now - timedelta(days=random.randint(10, 120))).isoformat()

    email = f"{username}@seed.sesa"
    cur.execute("""
        INSERT INTO accounts (fname, lname, username, email, password, school_name, gender,
                              class_group, school_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (fname, lname, username, email, password, school_name, gender, cgroup, school_id, created))

    student_id = cur.lastrowid
    created_students += 1

    num_tests  = random.randint(2, 4)
    used_types = random.sample(TEST_TYPES, num_tests)

    for test_type in used_types:
        stage     = pick_stage()
        score     = score_for_stage(stage)
        taken_at  = (now - timedelta(days=random.randint(0, 90))).isoformat()

        cur.execute("""
            INSERT INTO test_results (user_id, test_type, score, max_score, stage, taken_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (student_id, test_type, score, 40, stage, taken_at))
        created_results += 1

con.commit()
con.close()
print(f'Done. Created {created_students} students and {created_results} test results.')