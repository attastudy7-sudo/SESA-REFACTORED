"""
make_admin.py
─────────────
Promote an existing account to super-admin (is_admin = True).

Usage:
    python make_admin.py                        # interactive prompt
    python make_admin.py your@email.com         # by email
    python make_admin.py yourusername           # by username

Run from the project root (same folder as main.py).
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import db
from app.models.account import Accounts

app = create_app(os.environ.get('FLASK_ENV', 'development'))

def find_account(identifier: str):
    """Find account by email or username."""
    acc = Accounts.query.filter_by(email=identifier).first()
    if not acc:
        acc = Accounts.query.filter_by(username=identifier).first()
    return acc

def promote(identifier: str):
    acc = find_account(identifier)
    if not acc:
        print(f"\n❌  No account found for: '{identifier}'")
        print("    Check the email or username and try again.\n")
        return False

    if acc.is_admin:
        print(f"\n✅  {acc.full_name} (@{acc.username}) is already an admin.\n")
        return True

    acc.is_admin = True
    acc.is_counsellor = False   # admin supersedes counsellor role
    db.session.commit()
    print(f"\n✅  Done! {acc.full_name} (@{acc.username}) is now a super-admin.")
    print(f"    Email:    {acc.email}")
    print(f"    Role:     {acc.role}\n")
    return True

def list_admins():
    admins = Accounts.query.filter_by(is_admin=True).all()
    if not admins:
        print("\n   (no admins yet)\n")
    else:
        print(f"\n   Current admins ({len(admins)}):")
        for a in admins:
            print(f"   • {a.full_name} — @{a.username} — {a.email}")
        print()

with app.app_context():
    if len(sys.argv) > 1:
        # Passed as argument
        promote(sys.argv[1].strip())
    else:
        # Interactive
        print("\n── SESA Make Admin ─────────────────────────────")
        list_admins()
        identifier = input("Enter email or username to promote: ").strip()
        if identifier:
            promote(identifier)
        else:
            print("No input given. Exiting.\n") 