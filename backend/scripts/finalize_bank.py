"""
finalize_bank.py — Merge manual calculator classifications into the batch
manifests, validate completeness, and report the full question-bank
distribution. Used both for pre-seed review (report only) and, after approval,
to produce the seed-ready records (see seed step).

NEW questions (457) come from batch{1,2,3,4}_manifest.json:
  * batch1/2 (2024): calculatorStatus filled from batch{n}_classifications.json.
  * batch3/4 (2025): calculatorStatus already set by designation in the manifest.

BACKFILL (81 existing) come from question_bank_manifest.json + the two new
fields in backfill_classifications.json (these UPDATE existing docs in place).

Run:  python scripts/finalize_bank.py
"""
from __future__ import annotations

import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW = os.path.join(HERE, "batch_review")

_DOC_FIELDS = (
    "id", "subject", "paperType", "paperCode", "year", "isSpecimen",
    "originalQuestionNumber", "marks", "topic", "difficulty",
    "calculatorStatus", "classificationReason", "questionImageUrl", "markSchemeText",
)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_new_records() -> list[dict]:
    """The 457 new questions, each with a validated calculatorStatus."""
    records: list[dict] = []
    for batch in ("batch1", "batch2", "batch3", "batch4"):
        manifest = _load(os.path.join(REVIEW, f"{batch}_manifest.json"))
        cls_path = os.path.join(REVIEW, f"{batch}_classifications.json")
        cls = _load(cls_path) if os.path.exists(cls_path) else {}
        for it in manifest:
            status = it.get("calculatorStatus")
            reason = it.get("classificationReason")
            if status is None:  # 2024 batches: fill from manual classification
                c = cls.get(it["id"])
                assert c, f"MISSING classification for {it['id']}"
                status, reason = c["calculatorStatus"], c["classificationReason"]
            assert status in ("non_calc_safe", "calc_required"), f"bad status {it['id']}={status}"
            rec = {k: it.get(k) for k in _DOC_FIELDS}
            rec["calculatorStatus"] = status
            rec["classificationReason"] = reason
            # integrity
            assert rec["questionImageUrl"], f"{rec['id']} missing image"
            assert (rec["markSchemeText"] or "").strip(), f"{rec['id']} missing MS"
            assert rec["marks"] and rec["marks"] > 0, f"{rec['id']} 0 marks"
            records.append(rec)
    return records


def build_backfill_records() -> list[dict]:
    """The 81 existing questions with just their two new fields (for in-place update)."""
    man = _load(os.path.join(HERE, "question_bank_manifest.json"))
    cls = _load(os.path.join(REVIEW, "backfill_classifications.json"))
    out = []
    for it in man:
        c = cls.get(it["id"])
        assert c, f"MISSING backfill classification for {it['id']}"
        out.append({"id": it["id"], "paperCode": it["paperCode"], "paperType": it["paperType"],
                    "year": it["year"], "topic": it["topic"], "difficulty": it["difficulty"],
                    "calculatorStatus": c["calculatorStatus"],
                    "classificationReason": c["classificationReason"]})
    return out


def _dist(title, records):
    print(f"\n===== {title}  (n={len(records)}) =====")
    print("  calculatorStatus :", dict(Counter(r["calculatorStatus"] for r in records)))
    print("  paperType        :", dict(Counter(r["paperType"] for r in records)))
    print("  year             :", dict(sorted(Counter(r["year"] for r in records).items())))
    print("  difficulty       :", dict(Counter(r["difficulty"] for r in records)))
    # calc status split by paperType
    for pt in ("P2", "P4"):
        sub = [r for r in records if r["paperType"] == pt]
        if sub:
            print(f"    {pt} calc split   :", dict(Counter(r["calculatorStatus"] for r in sub)))


def main():
    new = build_new_records()
    backfill = build_backfill_records()
    allrec = new + backfill
    print("VALIDATION PASSED: every question has a calculatorStatus.")
    _dist("NEW questions (batches 1-4)", new)
    _dist("BACKFILL (existing 81)", backfill)
    _dist("WHOLE BANK (new + existing)", allrec)

    # The non-calculator generation pool (what a Paper-2 request can draw from).
    nc = [r for r in allrec if r["calculatorStatus"] == "non_calc_safe"]
    print("\n===== NON-CALCULATOR POOL (calculatorStatus == non_calc_safe) =====")
    print(f"  total non_calc_safe questions: {len(nc)}  of {len(allrec)}")
    print("  by topic :", dict(sorted(Counter(r["topic"] for r in nc).items())))
    print("  marks available:", sum(r.get("marks", 0) or 0 for r in new if r["calculatorStatus"] == "non_calc_safe"),
          "(new questions only; backfill marks not in this manifest)")
    # topic coverage across whole bank
    print("\n  whole-bank topics:", dict(sorted(Counter(r["topic"] for r in allrec).items())))
    return new, backfill


if __name__ == "__main__":
    main()
