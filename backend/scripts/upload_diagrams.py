"""
upload_diagrams.py — Step 4: upload each verified diagram crop to Firebase
Storage and write its download URL back onto the Firestore question document.

  * Storage path:   question_diagrams/<questionId>.png
  * Firestore:      questions/<questionId>.imageUrl = <download URL>

The download URL uses the Firebase `firebaseStorageDownloadTokens` mechanism —
the same token-based URL the client SDK's getDownloadURL() produces — so it is
fetchable by both the mobile app and the backend PDF generator without any
public-ACL / uniform-bucket-access juggling.

Questions that genuinely have no figure in the source (manifest status
NO_FIGURE_FOUND) are flipped to hasImage=false so they re-enter the generator
pool as clean text-only questions.

Run from backend/:  python scripts/upload_diagrams.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from urllib.parse import quote

import requests
from firebase_admin import storage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firestore_service import _get_client  # noqa: E402
from auth import _init_firebase_app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
BUCKET = "grade-ai-b524c.firebasestorage.app"
COLLECTION = "questions"


def _download_url(bucket_name: str, object_path: str, token: str) -> str:
    return (
        f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/"
        f"{quote(object_path, safe='')}?alt=media&token={token}"
    )


def main() -> None:
    manifest = json.load(open(os.path.join(OUT, "_manifest.json"), encoding="utf-8"))
    _init_firebase_app()
    bucket = storage.bucket(BUCKET)
    db = _get_client()

    uploaded, flipped, verified = 0, 0, 0
    first_url = None

    for m in manifest:
        qid = m["questionId"]
        if m["status"] == "OK":
            local = os.path.join(HERE, m["png"])
            object_path = f"question_diagrams/{qid}.png"
            token = str(uuid.uuid4())
            blob = bucket.blob(object_path)
            blob.metadata = {"firebaseStorageDownloadTokens": token}
            blob.upload_from_filename(local, content_type="image/png")
            url = _download_url(bucket.name, object_path, token)
            db.collection(COLLECTION).document(qid).update({"imageUrl": url})
            uploaded += 1
            if first_url is None:
                first_url = url
            print(f"  uploaded  {qid:<28} -> {object_path}")
        elif m["status"] == "NO_FIGURE_FOUND":
            db.collection(COLLECTION).document(qid).update({"hasImage": False})
            flipped += 1
            print(f"  hasImage=false  {qid}  (no diagram in source)")

    # Smoke-test one URL end to end.
    if first_url:
        r = requests.get(first_url, timeout=20)
        verified = r.status_code
        print(f"\nVerify fetch of first URL: HTTP {verified}, {len(r.content)} bytes")

    print(f"\nDONE: uploaded={uploaded}  hasImage->false={flipped}")


if __name__ == "__main__":
    main()
