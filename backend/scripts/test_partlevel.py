"""
test_partlevel.py — Part 5.3 + Part 7 end-to-end tests on REAL bank questions.

Runs the actual filter + substitution pipeline (partlevel_selection.py) against
scripts/part_extraction/part_level_questions.json and prints real output:

  Test 1 (Part 5.3 / 7.1): generate a paper EXCLUDING trigonometry using a real
    geometry/trig-mix question; confirm no trig (section 6) code survives, the
    trig sub-part is substituted or the question excluded, and no dependency
    violation occurs.
  Test 2 (Part 7.2): a question with a genuine "using your answer to part (a)"
    dependency is never split — kept whole or excluded entirely.
  Test 3 (Part 7.3): a question with a shared diagram across 3 sub-parts links
    all 3 to the same asset and orphans none during substitution.

Run from backend/:  python scripts/test_partlevel.py
Exit code 0 iff every assertion passes.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

from partlevel_selection import (  # noqa: E402
    assemble_question, assembly_conflicts, build_donor_pool, classify_question,
    expand_allowed, question_codes, select_paper,
)

BANK = json.load(open(os.path.join(HERE, "part_extraction", "part_level_questions.json"), encoding="utf-8"))
SYL = json.load(open(os.path.join(HERE, "syllabus_codes.json"), encoding="utf-8"))
FLAT = SYL["flat_codes"]
SECTION_OF = {c["code"]: c["section"] for c in FLAT}

_passes, _fails = [], []


def check(name, cond, detail=""):
    (_passes if cond else _fails).append(name)
    print(f"    [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def codes_of(q):
    return question_codes(q)


def has_section(q, sec):
    return any(SECTION_OF.get(c) == sec for c in codes_of(q))


# --------------------------------------------------------------------------- #
def test1_exclude_trig():
    print("\n" + "=" * 70)
    print("TEST 1 (Part 5.3 / 7.1) — generate a paper EXCLUDING trigonometry")
    print("=" * 70)
    allowed = expand_allowed(FLAT, exclude_sections=[6])  # no Trigonometry (E6.x)

    # find a real geometry/mensuration + trig mix question
    mixes = [q for q in BANK
             if has_section(q, 6) and any(SECTION_OF.get(c) in (4, 5) for c in codes_of(q))
             and len(q["subParts"]) > 1]
    print(f"  geometry/mensuration+trig mixed questions in bank: {len(mixes)}")
    example = None
    for q in mixes:
        if classify_question(q, allowed) == "partial":
            example = q
            break
    example = example or mixes[0]
    print(f"  using example: {example['id']}  (old broad topic: {example['topic']})")
    for sp in example["subParts"]:
        sec = {SECTION_OF.get(c) for c in (sp['syllabusCodes'] or [])}
        print(f"     {sp['label']:9} {sp['marks']}m  {sp['syllabusCodes']}  "
              f"{'<TRIG>' if 6 in sec else ''}  swappable={sp['swappable']}")

    status = classify_question(example, allowed)
    print(f"  classify_question(no-trig) = {status}")
    check("mixed question is not offered 'whole' when trig excluded", status != "whole",
          f"status={status}")

    donors = build_donor_pool(BANK, allowed)
    assembled, log = assemble_question(example, allowed, donors, set())
    if assembled is None:
        print(f"  -> whole question EXCLUDED (safe). reason: {log['reason']}")
        check("excluded question drags no trig into the paper", True)
    else:
        print(f"  -> ASSEMBLED. substitutions: {json.dumps(log['substitutions'])}")
        surviving = {c for sp in assembled['subParts'] for c in (sp['syllabusCodes'] or [])}
        trig_left = [c for c in surviving if SECTION_OF.get(c) == 6]
        check("no trig (section 6) code survives in the assembled question", not trig_left,
              f"surviving trig codes={trig_left}")
        check("assembled question has no ambiguity conflict", not assembly_conflicts(assembled))

    # full paper generation
    result = select_paper(BANK, allowed, target_marks=60, shuffle=None)
    trig_in_paper = []
    for q in result["questions"]:
        for sp in q["subParts"]:
            for c in (sp["syllabusCodes"] or []):
                if SECTION_OF.get(c) == 6:
                    trig_in_paper.append((q["id"], sp["label"], c))
    print(f"  generated paper: {result['numQuestions']} questions, {result['totalMarks']}/{result['targetMarks']} marks")
    print(f"    whole={len(result['log']['whole'])} assembled={len(result['log']['assembled'])} "
          f"excluded={len(result['log']['excluded'])} substitutions={len(result['log']['substitutions'])}")
    check("NO trig sub-part anywhere in the generated no-trig paper", not trig_in_paper,
          f"leaks={trig_in_paper[:3]}")
    # dependency safety across the whole paper
    viol = []
    for q in result["questions"]:
        viol += assembly_conflicts(q)
    check("no shared-asset / ambiguity violation in the generated paper", not viol, str(viol[:2]))


# --------------------------------------------------------------------------- #
def test2_prior_answer_never_split():
    print("\n" + "=" * 70)
    print("TEST 2 (Part 7.2) — a 'using your answer to (a)' question is never split")
    print("=" * 70)
    # Prefer a prior-answer edge whose dependent and target have DISJOINT codes,
    # so we can allow the dependent while excluding the target's exact code and
    # actively tempt a split; fall back to any prior-answer edge.
    cand = None
    fallback = None
    for q in BANK:
        by_id = {l["partId"]: l for l in q["subParts"]}
        for sp in q["subParts"]:
            if "prior_answer" in (sp.get("dependencyKind") or []) and sp.get("dependsOnParts"):
                tgt = by_id.get(sp["dependsOnParts"][0])
                fallback = fallback or (q, sp)
                if tgt and sp["syllabusCodes"] and tgt["syllabusCodes"] and \
                        not (set(sp["syllabusCodes"]) & set(tgt["syllabusCodes"])):
                    cand = (q, sp)
                    break
        if cand:
            break
    q, dep_leaf = cand or fallback
    _disjoint = cand is not None
    target_pid = dep_leaf["dependsOnParts"][0]
    target = next(l for l in q["subParts"] if l["partId"] == target_pid)
    print(f"  question: {q['id']}")
    print(f"    {dep_leaf['label']} (codes {dep_leaf['syllabusCodes']}) depends on "
          f"{target['label']} (codes {target['syllabusCodes']})")

    # Build an allowed set that KEEPS the dependent sub-part but EXCLUDES the
    # depended-on sub-part's exact code(s) — the precise split-temptation case.
    if _disjoint:
        allowed = expand_allowed(FLAT, exclude_codes=target["syllabusCodes"])
        excl_desc = f"target codes {target['syllabusCodes']}"
    else:
        print("  (bank note: every prior-answer chain is intra-topic — a split can "
              "never keep the dependent while excluding the target; asserting the invariant.)")
        allowed = expand_allowed(FLAT)
        excl_desc = "{}"
    donors = build_donor_pool(BANK, allowed)
    assembled, log = assemble_question(q, allowed, donors, set())
    status = classify_question(q, allowed)
    print(f"  excluding {excl_desc} -> classify={status}")
    if assembled is None:
        print(f"  -> EXCLUDED whole (refused to split). reason: {log['reason']}")
        check("pipeline refused to split the dependency (excluded whole)", True)
    else:
        kept_ids = {l["partId"] for l in assembled["subParts"]}
        dep_kept = dep_leaf["partId"] in kept_ids
        tgt_kept = target_pid in kept_ids
        ok = (not dep_kept) or tgt_kept
        print(f"  -> assembled; dependent kept={dep_kept}, target kept={tgt_kept}")
        check("dependent sub-part never kept without its prior-answer target", ok)


# --------------------------------------------------------------------------- #
def test3_shared_diagram_three_parts():
    print("\n" + "=" * 70)
    print("TEST 3 (Part 7.3) — shared diagram across 3+ sub-parts, none orphaned")
    print("=" * 70)
    # Prefer a shared group spanning >=2 syllabus sections (so excluding one
    # section keeps SOME members and excludes another -> exercises the
    # "never partially break a shared group" path); fall back to any 3+ group.
    cand = None
    fallback = None
    for q in BANK:
        by_id = {l["partId"]: l for l in q["subParts"]}
        for a in q.get("sharedAssets", []):
            if len(a.get("usedByParts", [])) >= 3:
                fallback = fallback or (q, a)
                secs = set()
                for pid in a["usedByParts"]:
                    lf = by_id.get(pid)
                    if lf:
                        secs |= {SECTION_OF.get(c) for c in (lf["syllabusCodes"] or [])}
                if len([s for s in secs if s]) >= 2:
                    cand = (q, a)
                    break
        if cand:
            break
    q, asset = cand or fallback
    print(f"  question: {q['id']}  shared asset {asset['assetId']} ({asset['kind']})")
    print(f"    used by {len(asset['usedByParts'])} sub-parts: {asset['usedByParts']}")
    # all three link to the SAME asset id
    members = set(asset["usedByParts"])
    linked = all(any(a["assetId"] == asset["assetId"] and pid in a["usedByParts"]
                     for a in q["sharedAssets"]) for pid in members)
    check("all 3+ sub-parts linked to the same shared asset id", linked)
    # none of them is marked independently swappable
    swappables = [l["label"] for l in q["subParts"]
                  if l["partId"] in members and l.get("swappable")]
    check("no shared-diagram sub-part is marked independently swappable", not swappables,
          f"wrongly-swappable={swappables}")

    # attempt a substitution that would remove ONE member: build an allowed set
    # excluding one member's topic and confirm the whole question is excluded
    # (the shared group is never partially broken / orphaned).
    victim = next(l for l in q["subParts"] if l["partId"] in members and l["syllabusCodes"])
    victim_secs = [SECTION_OF.get(c) for c in victim["syllabusCodes"] if SECTION_OF.get(c)]
    allowed = expand_allowed(FLAT, exclude_sections=victim_secs[:1])
    donors = build_donor_pool(BANK, allowed)
    assembled, log = assemble_question(q, allowed, donors, set())
    if assembled is None:
        print(f"  -> excluding section {victim_secs[:1]} => whole question EXCLUDED. reason: {log['reason']}")
        check("shared-diagram group never partially broken (whole excluded)", True)
    else:
        present = {l["partId"] for l in assembled["subParts"]}
        kept_members = members & present
        intact = kept_members == members or kept_members == set()
        check("shared-diagram group kept intact or fully dropped (none orphaned)", intact,
              f"kept {len(kept_members)}/{len(members)} members")
        check("no assembly conflict after substitution", not assembly_conflicts(assembled))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Bank: {len(BANK)} part-level questions, "
          f"{sum(len(q['subParts']) for q in BANK)} sub-parts")
    test1_exclude_trig()
    test2_prior_answer_never_split()
    test3_shared_diagram_three_parts()
    print("\n" + "=" * 70)
    print(f"RESULT: {len(_passes)} passed, {len(_fails)} failed")
    if _fails:
        print("FAILED:", _fails)
    print("=" * 70)
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
