"""
publish_two.py — Publish the 2 newly-extracted figures (2021 Q5, 2022 Q4):
copy crops into backend/static/question_diagrams, set imageUrl + hasImage=True,
and strip the now-redundant "[Diagram: …]" fallback line from questionText.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firestore_service import _get_client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")
STATIC_DIR = os.path.join(os.path.dirname(HERE), "static", "question_diagrams")
COLLECTION = "questions"


def main() -> None:
    manifest = json.load(open(os.path.join(OUT, "_manifest_two.json"), encoding="utf-8"))
    db = _get_client()
    for m in manifest:
        qid = m["questionId"]
        shutil.copyfile(os.path.join(HERE, m["png"]), os.path.join(STATIC_DIR, f"{qid}.png"))
        snap = db.collection(COLLECTION).document(qid).get().to_dict() or {}
        text = snap.get("questionText", "") or ""
        # Drop the leading "[Diagram: …]" fallback line (image now replaces it).
        kept = [ln for ln in text.split("\n") if not ln.strip().startswith("[Diagram:")]
        cleaned = "\n".join(kept).strip()
        db.collection(COLLECTION).document(qid).update({
            "hasImage": True,
            "imageUrl": f"/diagrams/{qid}.png",
            "questionText": cleaned,
        })
        print(f"published {qid}: image + imageUrl set, [Diagram:…] stripped")
    print("DONE.")


if __name__ == "__main__":
    main()
