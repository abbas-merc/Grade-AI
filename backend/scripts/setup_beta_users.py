"""
scripts/setup_beta_users.py — Grant beta access to a fixed list of teachers.

For each email it looks up the Firebase Auth user, then sets ``is_beta=true`` and
``usage_count=0`` on that user's Firestore ``teachers/{uid}`` document (merged, so
existing fields such as ``pushToken`` are preserved).

IMPORTANT: as of writing, NO backend code reads ``is_beta`` or ``usage_count`` —
the app has no usage limiting yet. This script provisions the fields ahead of
that feature so beta accounts are ready the moment enforcement lands. Setting
them now is harmless and idempotent.

It reuses the same Firebase Admin app and Firestore client the backend uses
(via auth._init_firebase_app / firestore_service._get_client), so no separate
credentials or initialization are needed — just run it with the backend's
environment configured (FIREBASE_SERVICE_ACCOUNT_JSON or _PATH in .env).

Usage (from inside the backend/ directory, venv active):

    python scripts/setup_beta_users.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Running as `python scripts/setup_beta_users.py` puts backend/scripts on
# sys.path, not backend/. Add the backend package root so `auth` and
# `firestore_service` import the same modules the server uses.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firebase_admin import auth as firebase_auth  # noqa: E402

from auth import _init_firebase_app  # noqa: E402
from firestore_service import _get_client  # noqa: E402

# Replace these placeholders with the real beta teacher emails before running.
BETA_EMAILS: list[str] = [
    "teacher1@beta.com",
    "teacher2@beta.com",
    "teacher3@beta.com",
    "teacher4@beta.com",
]

_TEACHERS_COLLECTION = "teachers"


def grant_beta(email: str, db) -> bool:
    """Provision beta fields for one teacher. Returns True on success."""
    try:
        user = firebase_auth.get_user_by_email(email)
    except firebase_auth.UserNotFoundError:
        print(
            f"  [SKIP] {email}: User not found - they must sign up first "
            f"before you run this script."
        )
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {email}: Firebase Auth lookup failed: {exc}")
        return False

    try:
        db.collection(_TEACHERS_COLLECTION).document(user.uid).set(
            {"is_beta": True, "usage_count": 0},
            merge=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {email}: Firestore write failed: {exc}")
        return False

    print(f"  [OK]   {email}: uid={user.uid} -> is_beta=true, usage_count=0")
    return True


def main() -> None:
    _init_firebase_app()
    db = _get_client()

    print(f"Granting beta access to {len(BETA_EMAILS)} teacher(s)...\n")
    granted = sum(grant_beta(email, db) for email in BETA_EMAILS)
    print(f"\nDone. {granted}/{len(BETA_EMAILS)} teacher document(s) updated.")
    if granted < len(BETA_EMAILS):
        print(
            "Some emails were skipped/failed (see above). Re-run after those "
            "teachers have signed up."
        )


if __name__ == "__main__":
    main()
