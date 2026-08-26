"""
build_partlevel_bank.py — Merge extraction (Part 2) + dependencies (Part 4) +
tags (Part 3) into final part-level question documents (schemaVersion 2),
validated against partlevel_schema.validate().

Inputs (all under scripts/part_extraction/):
  part_manifest.json      structure, per-part marks, per-part text, shared assets,
                          dependency fields (merged by build_dependencies.py)
  part_tags.json          per-part syllabus codes + confidence (build tag step)
Plus the bank manifests for the authoritative flat fields (paperCode, topic,
difficulty, calculatorStatus, year, isSpecimen, questionImageUrl).

Output: scripts/part_extraction/part_level_questions.json  (list of PartLevelQuestion)
Also runs Part 3.3 cross-check (old broad topic vs new part-level tags) and
prints the review lists (low/medium-confidence tags, partial extractions).

Run from backend/:  python scripts/build_partlevel_bank.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from partlevel_schema import build_dependency_graph, question_syllabus_codes, validate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PE = os.path.join(HERE, "part_extraction")
SYLLABUS = os.path.join(HERE, "syllabus_codes.json")
OUT = os.path.join(PE, "part_level_questions.json")

# broad-topic -> the syllabus section number that topic corresponds to, for the
# Part 3.3 cross-check (does the old whole-question bucket agree with the new
# part-level codes?).
_TOPIC_SECTION = {
    "number": {1}, "algebra": {2, 3}, "geometry": {4, 5}, "trigonometry": {6},
    "vectors": {7}, "probability": {8}, "statistics": {9},
    "calculus": {2, 3},  # 0580 has no calculus section; old bank used it loosely
}


def _load_bank_fields():
    fields = {}
    files = [os.path.join(HERE, "question_bank_manifest.json")]
    files += glob.glob(os.path.join(HERE, "batch_review", "batch*_manifest.json"))
    for fp in files:
        if os.path.exists(fp):
            for q in json.load(open(fp, encoding="utf-8")):
                fields[q["id"]] = q
    return fields


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.load(open(os.path.join(PE, "part_manifest.json"), encoding="utf-8"))
    tags = json.load(open(os.path.join(PE, "part_tags.json"), encoding="utf-8"))
    bank = _load_bank_fields()
    syl = json.load(open(SYLLABUS, encoding="utf-8"))
    valid_codes = {c["code"] for c in syl["flat_codes"]}
    code_section = {c["code"]: c["section"] for c in syl["flat_codes"]}

    docs = []
    review_low, review_med, untagged = [], [], []
    partial_extractions = []
    tag_mismatch_count = 0
    problems_all = []

    for rec in manifest:
        qid = rec["id"]
        b = bank.get(qid, {})
        sub_parts = []
        for sp in rec["subParts"]:
            pid = qid + "_" + "_".join(sp["path"])
            t = tags.get(pid, {})
            codes = t.get("syllabusCodes", [])
            conf = t.get("codeConfidence", "low")
            part = {
                "partId": pid,
                "label": sp["label"] or "(whole)",
                "path": sp["path"],
                "marks": sp["marks"],
                "syllabusCodes": codes,
                "codeConfidence": conf,
                "codeReason": t.get("codeReason", ""),
                "markSchemeText": rec.get("markSchemeByPart", {}).get(
                    "".join(sp["path"]) if sp["path"] != ["_"] else "_", ""),
                "questionText": sp.get("questionText", ""),
                "imageRefs": [pid] + [a["assetId"] for a in rec.get("sharedAssets", [])
                                      if sp["path"] in a.get("usedByPaths", [])],
                "dependsOnParts": sp.get("dependsOnParts", []),
                "dependencyKind": sp.get("dependencyKind", []),
                "selfContained": sp.get("selfContained", True),
                "swappable": sp.get("swappable", False),
            }
            sub_parts.append(part)
            if not codes:
                untagged.append(pid)
            elif conf == "low":
                review_low.append(pid)
            elif conf == "medium":
                review_med.append(pid)

        shared_assets = [{
            "assetId": a["assetId"], "kind": a["kind"],
            "imageUrl": a.get("imageUrl", f"/question_assets/{a['assetId']}.png"),
            "usedByParts": [qid + "_" + "_".join(p) for p in a.get("usedByPaths", [])],
            "label": a.get("label", ""),
        } for a in rec.get("sharedAssets", [])]

        doc = {
            # flat / back-compat
            "id": qid, "subject": b.get("subject", "math"),
            "paperType": b.get("paperType", rec.get("paperType", "")),
            "paperCode": b.get("paperCode", ""), "year": b.get("year"),
            "isSpecimen": b.get("isSpecimen", False),
            "originalQuestionNumber": b.get("originalQuestionNumber", rec.get("originalQuestionNumber")),
            "marks": b.get("marks", rec.get("bankMarks") or rec.get("leaf_marks_sum")),
            "difficulty": b.get("difficulty", ""),
            "calculatorStatus": b.get("calculatorStatus", ""),
            "questionImageUrl": b.get("questionImageUrl", ""),
            "topic": b.get("topic", ""),  # DEPRECATED broad bucket
            # part-level
            "schemaVersion": 2,
            "subParts": sub_parts,
            "sharedAssets": shared_assets,
            "extractionStatus": rec.get("extractionStatus", "extracted"),
            "marksReconciled": rec.get("marksReconciled", True),
        }
        doc["syllabusCodes"] = question_syllabus_codes(doc)
        doc["dependencyGraph"] = build_dependency_graph(
            {"subParts": sub_parts, "sharedAssets": [
                {"assetId": a["assetId"], "usedByParts": a["usedByParts"]} for a in shared_assets]})

        # Part 3.3 cross-check: old broad topic vs new part-level sections
        old_topic = (b.get("topic") or "").lower()
        new_sections = {code_section.get(c) for c in doc["syllabusCodes"] if c in code_section}
        expected = _TOPIC_SECTION.get(old_topic, set())
        if old_topic and doc["syllabusCodes"] and not (new_sections & expected):
            doc["tagMismatch"] = True
            tag_mismatch_count += 1
        else:
            doc["tagMismatch"] = bool(old_topic and expected and (new_sections - expected))

        if doc["extractionStatus"] != "extracted":
            partial_extractions.append(qid)

        problems = validate(doc, valid_codes)
        problems_all.extend(problems)
        docs.append(doc)

    json.dump(docs, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    print(f"part-level questions: {len(docs)}")
    print(f"total sub-parts: {sum(len(d['subParts']) for d in docs)}")
    print(f"validation problems: {len(problems_all)}")
    for p in problems_all[:12]:
        print("   !", p)
    print(f"\n--- Part 3.3 cross-check ---")
    print(f"questions where old broad topic disagreed with new part-level tags: {tag_mismatch_count}")
    print(f"\n--- review lists ---")
    print(f"untagged sub-parts: {len(untagged)}")
    print(f"low-confidence tags: {len(review_low)}")
    print(f"medium-confidence tags: {len(review_med)}")
    print(f"partial extractions (marks not reconciled): {partial_extractions}")
    print(f"\n-> {os.path.relpath(OUT)}")

    # dump the review lists to a file for Part 8
    json.dump({
        "untagged": untagged, "low_confidence": review_low,
        "medium_confidence": review_med, "partial_extractions": partial_extractions,
        "tag_mismatch_count": tag_mismatch_count,
    }, open(os.path.join(PE, "review_lists.json"), "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
