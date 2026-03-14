"""
safe_upgrade.py
────────────────
Runs flask db upgrade safely:
  1. Checks DB connectivity
  2. Shows current revision before upgrade
  3. Runs the upgrade
  4. Confirms new revision after upgrade

Usage:
    python safe_upgrade.py

Must be run from your project root (where your Flask app lives),
with your virtual environment activated.

Requires DATABASE_URL to be set in the environment (or a .env file).
"""

import os
import sys
import subprocess

def load_dotenv():
    """Minimal .env loader — no dependency on python-dotenv."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

def run(cmd, capture=False):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if capture:
        return result.stdout.strip(), result.returncode
    return None, result.returncode

def main():
    load_dotenv()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set.")
        sys.exit(1)

    # ── Step 1: show current revision ────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Current migration revision")
    print("=" * 60)
    _, rc = run(["flask", "db", "current"])
    if rc != 0:
        print("\nERROR: Could not get current revision. Is your venv active and FLASK_APP set?")
        sys.exit(1)

    # ── Step 2: show pending migrations ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: Pending migrations (heads)")
    print("=" * 60)
    run(["flask", "db", "heads"])

    # ── Step 3: confirm ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    answer = input("Proceed with 'flask db upgrade'? [y/N]: ").strip().lower()
    if answer != "y":
        print("Aborted.")
        sys.exit(0)

    # ── Step 4: upgrade ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: Running upgrade")
    print("=" * 60)
    _, rc = run(["flask", "db", "upgrade"])
    if rc != 0:
        print("\n❌ Upgrade FAILED. Check the error above.")
        sys.exit(1)

    # ── Step 5: confirm new state ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 4: New revision after upgrade")
    print("=" * 60)
    run(["flask", "db", "current"])
    print("\n✅ Upgrade complete!")

if __name__ == "__main__":
    main()