"""
prod_test.py — Hit the PRODUCTION backend end to end:
  1. Mint a Firebase ID token (Admin custom token -> signInWithCustomToken).
  2. POST /api/generate-paper (geometry + trigonometry) with that Bearer token.
  3. Confirm diagram questions are selected (hasImage + imageUrl).
  4. Confirm each imageUrl resolves to a real PNG on production.

Run from backend/:  python scripts/prod_test.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _init_firebase_app  # noqa: E402
from firebase_admin import auth as fb_auth  # noqa: E402

PROD = "https://grade-ai-production.up.railway.app"
GS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "..", "app", "android", "app", "google-services.json")


def _web_api_key() -> str:
    data = json.load(open(GS, encoding="utf-8"))
    return data["client"][0]["api_key"][0]["current_key"]


def _id_token() -> str:
    _init_firebase_app()
    custom = fb_auth.create_custom_token("prod-smoke-test").decode()
    r = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken",
        params={"key": _web_api_key()},
        json={"token": custom, "returnSecureToken": True}, timeout=30,
    )
    r.raise_for_status()
    return r.json()["idToken"]


def main() -> None:
    health = requests.get(f"{PROD}/health", timeout=20).json()
    print("PROD /health:", health)

    token = _id_token()
    body = {"subject": "math", "topics": ["geometry", "trigonometry"],
            "totalMarks": 90, "difficulty": "mixed"}
    r = requests.post(f"{PROD}/api/generate-paper", json=body,
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
    print("POST /api/generate-paper ->", r.status_code)
    r.raise_for_status()
    paper = r.json()

    qs = paper["questions"]
    img_qs = [q for q in qs if q.get("hasImage") and q.get("imageUrl")]
    print(f"\nPaper: {len(qs)} questions, {paper['totalMarks']} marks; image questions: {len(img_qs)}")
    for q in qs:
        print(f"  Q{q['assignedNumber']:<2} [{'IMG' if q.get('hasImage') else 'txt'}] "
              f"{q['topic']:<13} {q.get('imageUrl','')}")

    print("\nResolving image URLs on production:")
    ok = 0
    for q in img_qs:
        url = PROD + q["imageUrl"]
        h = requests.get(url, timeout=30)
        good = h.status_code == 200 and h.headers.get("content-type", "").startswith("image")
        ok += good
        print(f"  {'OK ' if good else 'FAIL'} {h.status_code} {h.headers.get('content-type','')} "
              f"{len(h.content):>7}B  {q['imageUrl']}")

    print(f"\nRESULT: {len(img_qs)} image questions, {ok}/{len(img_qs)} image URLs resolved on prod.")
    # Also spot-check a cleaned-text marker: no Symbol-font '#' artefacts in text.
    has_hash = [q['assignedNumber'] for q in qs if '#' in q.get('questionText', '')]
    print("Questions with stray '#' in text (should be none):", has_hash)


if __name__ == "__main__":
    main()
