"""
publish_diagrams.py — Step 4 (Firebase-Storage-free variant).

The Firebase project has no billing account, so a Storage bucket cannot be
provisioned (Storage on the *.firebasestorage.app scheme requires the Blaze
plan). Instead we host the verified diagram crops from the backend itself —
which the app already depends on — and record a host-agnostic relative path on
each Firestore question document:

  * copy  scripts/diagram_out/<id>.png  ->  backend/static/question_diagrams/<id>.png
  * set   questions/<id>.imageUrl = "/diagrams/<id>.png"

main.py serves backend/static/question_diagrams at /diagrams, and
generate-paper resolves the relative path to an absolute URL per request (so it
works on the LAN in dev and on Railway in prod alike). Questions with no figure
in the source (NO_FIGURE_FOUND) are flipped to hasImage=false.

Run from backend/:  python scripts/publish_diagrams.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firestore_service import _get_client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
OUT = os.path.join(HERE, "diagram_out")
STATIC_DIR = os.path.join(BACKEND, "static", "question_diagrams")
COLLECTION = "questions"


def main() -> None:
    manifest = json.load(open(os.path.join(OUT, "_manifest.json"), encoding="utf-8"))
    os.makedirs(STATIC_DIR, exist_ok=True)
    db = _get_client()

    published, flipped = 0, 0
    for m in manifest:
        qid = m["questionId"]
        if m["status"] == "OK":
            src = os.path.join(HERE, m["png"])
            dst = os.path.join(STATIC_DIR, f"{qid}.png")
            shutil.copyfile(src, dst)
            rel = f"/diagrams/{qid}.png"
            db.collection(COLLECTION).document(qid).update({"imageUrl": rel, "hasImage": True})
            published += 1
            print(f"  published  {qid:<28} -> static{os.sep}question_diagrams{os.sep}{qid}.png  ({rel})")
        elif m["status"] == "NO_FIGURE_FOUND":
            db.collection(COLLECTION).document(qid).update({"hasImage": False, "imageUrl": ""})
            flipped += 1
            print(f"  hasImage=false  {qid}  (no diagram in source)")

    print(f"\nDONE: published={published}  hasImage->false={flipped}")
    print(f"Static files: {STATIC_DIR}")


if __name__ == "__main__":
    main()
