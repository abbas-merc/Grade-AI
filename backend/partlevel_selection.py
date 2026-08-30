"""
partlevel_selection.py — Part 5 (filter) + Part 6 (smart substitution).

Pure, Firestore-free selection logic operating on part-level question docs
(schemaVersion 2, see scripts/partlevel_schema.py). Imported by
routers/paper_generator.py and exercised directly by scripts/test_partlevel.py.

The rule that fixes the bug (Part 5.1): a question is offered WHOLE only if
EVERY sub-part's syllabus codes fall inside the teacher's allowed set. A
question with some in-set and some out-of-set sub-parts is a PARTIAL candidate
(Part 5.2) handed to substitution (Part 6):

  * An out-of-set sub-part is removed and replaced by a donor sub-part from
    elsewhere in the bank that matches an allowed topic, has similar marks, and
    is itself independently swappable (Part 6.1) — but ONLY if removing it is
    safe.
  * Removal is UNSAFE, and the whole question is excluded instead (Part 6.2), if
    the out-of-set sub-part shares a diagram/context with a kept sub-part, is
    depended on by a kept sub-part, or a kept sub-part depends on its answer.
  * The assembled question is checked for ambiguous shared-diagram conflicts
    (Part 6.3), and the paper warns if the target mark total can't be reached
    (Part 6.4).
"""
from __future__ import annotations

from itertools import zip_longest
from typing import Iterable, Optional


# --------------------------------------------------------------------------- #
# Allowed-code helpers
# --------------------------------------------------------------------------- #
def expand_allowed(flat_codes: list[dict], *, exclude_sections: Iterable[int] = (),
                   exclude_codes: Iterable[str] = (),
                   only_sections: Optional[Iterable[int]] = None) -> set[str]:
    """Build the allowed-code set from the taxonomy's flat code list.
    `exclude_sections=[6]` drops all Trigonometry (E6.x/C6.x); `only_sections`
    restricts to just those sections."""
    ex_sec, ex_code = set(exclude_sections), set(exclude_codes)
    allowed = set()
    for c in flat_codes:
        if only_sections is not None and c["section"] not in set(only_sections):
            continue
        if c["section"] in ex_sec or c["code"] in ex_code:
            continue
        allowed.add(c["code"])
    return allowed


def _leaf_in_allowed(leaf: dict, allowed: set[str]) -> bool:
    codes = leaf.get("syllabusCodes") or []
    # An untagged leaf (no codes) is treated as NOT allowed — we never silently
    # admit a sub-part whose topic we couldn't determine.
    return bool(codes) and all(c in allowed for c in codes)


def question_codes(q: dict) -> set[str]:
    out = set()
    for sp in q.get("subParts", []):
        out.update(sp.get("syllabusCodes") or [])
    return out


# --------------------------------------------------------------------------- #
# Classification (Part 5.1 / 5.2)
# --------------------------------------------------------------------------- #
def classify_question(q: dict, allowed: set[str]) -> str:
    """'whole' | 'partial' | 'excluded'."""
    leaves = q.get("subParts", [])
    if not leaves:
        return "excluded"
    in_set = [l for l in leaves if _leaf_in_allowed(l, allowed)]
    out_set = [l for l in leaves if not _leaf_in_allowed(l, allowed)]
    if not out_set:
        return "whole"
    if not in_set:
        return "excluded"
    return "partial"


# --------------------------------------------------------------------------- #
# Donor pool for substitution (Part 6.1)
# --------------------------------------------------------------------------- #
def build_donor_pool(bank: list[dict], allowed: set[str]) -> list[dict]:
    """Every independently-swappable, in-topic sub-part in the bank, each tagged
    with its source question id so we never reuse a leaf in its own question."""
    donors = []
    for q in bank:
        for sp in q.get("subParts", []):
            if sp.get("swappable") and _leaf_in_allowed(sp, allowed):
                donors.append({**sp, "_sourceQuestion": q["id"]})
    return donors


def _find_donor(donors: list[dict], marks: int, allowed: set[str],
                used: set[str], avoid_question: str, tol: int = 1) -> Optional[dict]:
    """Closest-marks swappable donor for a removed sub-part, preferring an exact
    mark match so the paper's total stays accurate."""
    best = None
    best_gap = None
    for d in donors:
        if d["partId"] in used or d["_sourceQuestion"] == avoid_question:
            continue
        gap = abs(int(d.get("marks", 0)) - marks)
        if gap > tol:
            continue
        if best is None or gap < best_gap:
            best, best_gap = d, gap
            if gap == 0:
                break
    return best


# --------------------------------------------------------------------------- #
# Assembly + substitution (Part 6)
# --------------------------------------------------------------------------- #
def _shared_partids(q: dict) -> dict[str, set[str]]:
    """partId -> set of partIds it shares an asset with (co-members)."""
    out: dict[str, set[str]] = {}
    for a in q.get("sharedAssets", []):
        members = set(a.get("usedByParts", []))
        for m in members:
            out.setdefault(m, set()).update(members - {m})
    return out


def assemble_question(q: dict, allowed: set[str], donors: list[dict],
                      used_donors: set[str]) -> tuple[Optional[dict], dict]:
    """Return (assembled_question | None, log).

    None means 'exclude the whole question' (unsafe to split, per Part 6.2).
    """
    leaves = q.get("subParts", [])
    keep = [l for l in leaves if _leaf_in_allowed(l, allowed)]
    drop = [l for l in leaves if not _leaf_in_allowed(l, allowed)]
    keep_ids = {l["partId"] for l in keep}
    drop_ids = {l["partId"] for l in drop}
    shared = _shared_partids(q)
    log = {"questionId": q["id"], "substitutions": [], "reason": None}

    # --- safety gates (Part 6.2) ---
    for d in drop:
        pid = d["partId"]
        # (a) a kept sub-part depends on this excluded one's answer
        dependents = [k for k in keep if pid in (k.get("dependsOnParts") or [])]
        if dependents:
            log["reason"] = f"kept {dependents[0]['label']} depends on excluded {d['label']}"
            return None, log
        # (b) this excluded sub-part shares a diagram/context with a kept one
        if shared.get(pid, set()) & keep_ids:
            log["reason"] = f"excluded {d['label']} shares an asset with a kept sub-part"
            return None, log
        # (c) this excluded sub-part depends on another EXCLUDED one only — fine;
        #     but if it depends on a KEPT one, removing it is still safe (we drop
        #     the dependent, not the dependency). No gate needed.

    # also: a kept sub-part that depends on another kept sub-part is fine; a kept
    # sub-part depending on something outside the question is left as-is.

    # --- substitute each dropped sub-part (Part 6.1) ---
    new_parts = list(keep)
    for d in drop:
        donor = _find_donor(donors, int(d.get("marks", 0)), allowed,
                            used_donors, q["id"])
        if donor is None:
            # No safe same-marks donor. Drop the sub-part (marks reduced); the
            # selector + Part 6.4 warning account for the lower total. We do NOT
            # exclude the whole question here — the kept content is still valid.
            log["substitutions"].append({"removed": d["label"], "removedMarks": d.get("marks"),
                                          "replacedWith": None})
            continue
        used_donors.add(donor["partId"])
        new_parts.append(donor)
        log["substitutions"].append({
            "removed": d["label"], "removedMarks": d.get("marks"),
            "replacedWith": donor["partId"], "donorCodes": donor.get("syllabusCodes"),
            "donorMarks": donor.get("marks"),
        })

    if not new_parts:
        log["reason"] = "no sub-parts remain after exclusion"
        return None, log

    assembled = {**q, "subParts": new_parts,
                 "marks": sum(int(p.get("marks", 0)) for p in new_parts),
                 "assembled": True, "assemblyLog": log,
                 "syllabusCodes": sorted({c for p in new_parts for c in (p.get("syllabusCodes") or [])})}

    # --- Part 6.3 ambiguity check ---
    violations = assembly_conflicts(assembled)
    if violations:
        log["reason"] = f"assembly conflict: {violations[0]}"
        return None, log
    return assembled, log


def assembly_conflicts(q: dict) -> list[str]:
    """Part 6.3 — no two sub-parts may reference different diagrams under an
    ambiguous shared label. Safe iff every kept shared-asset group is fully
    present and every substituted/self-contained part carries its own image."""
    problems = []
    present = {p["partId"] for p in q.get("subParts", [])}
    for a in q.get("sharedAssets", []):
        members = set(a.get("usedByParts", []))
        kept_members = members & present
        if kept_members and kept_members != members:
            problems.append(
                f"shared asset {a['assetId']} referenced by {sorted(kept_members)} "
                f"but its group {sorted(members)} is not fully present")
    return problems


# --------------------------------------------------------------------------- #
# Paper selection (subset-sum to hit target) — Part 6.4
# --------------------------------------------------------------------------- #
_MIN_Q, _MAX_Q = 1, 20


def _subset_sum(items: list[dict], target: int) -> list[dict]:
    """Pick a subset whose marks sum as close to `target` as possible without
    exceeding it (bounded subset-sum DP; favours fewer, higher-mark items)."""
    n = len(items)
    if n == 0:
        return []
    max_k = min(_MAX_Q, n)
    reach = [set() for _ in range(max_k + 1)]
    reach[0].add(0)
    came = [dict() for _ in range(max_k + 1)]
    for idx, q in enumerate(items):
        m = int(q.get("marks", 0) or 0)
        if m <= 0:
            continue
        for k in range(max_k, 0, -1):
            for s in list(reach[k - 1]):
                ns = s + m
                if ns <= target and ns not in reach[k]:
                    reach[k].add(ns)
                    came[k][ns] = idx
    best = None
    for k in range(1, max_k + 1):
        if reach[k]:
            s = max(reach[k])
            if best is None or s > best[0] or (s == best[0] and k < best[1]):
                best = (s, k)
    if best is None:
        return []
    s, k = best
    chosen = []
    while k > 0:
        idx = came[k][s]
        chosen.append(idx)
        s -= int(items[idx].get("marks", 0) or 0)
        k -= 1
    return [items[i] for i in reversed(chosen)]


def select_paper(bank: list[dict], allowed: set[str], target_marks: int, *,
                 paper_type: Optional[str] = None, difficulty: Optional[str] = None,
                 shuffle=None) -> dict:
    """Assemble a topic-safe paper hitting `target_marks` where possible.

    Returns {questions, totalMarks, targetMarks, warnings, log:{whole,assembled,
    excluded,substitutions}}.
    """
    pool = bank
    if paper_type == "P2":
        pool = [q for q in pool if q.get("calculatorStatus") == "non_calc_safe"]
    if difficulty and difficulty != "mixed":
        pool = [q for q in pool if q.get("difficulty") == difficulty]

    donors = build_donor_pool(bank, allowed)  # donors drawn from the WHOLE bank
    used_donors: set[str] = set()

    candidates: list[dict] = []
    log = {"whole": [], "assembled": [], "excluded": [], "substitutions": []}
    for q in pool:
        status = classify_question(q, allowed)
        if status == "whole":
            candidates.append(q)
            log["whole"].append(q["id"])
        elif status == "excluded":
            log["excluded"].append({"id": q["id"], "reason": "no in-topic sub-parts"})
        else:  # partial
            assembled, alog = assemble_question(q, allowed, donors, used_donors)
            if assembled is None:
                log["excluded"].append({"id": q["id"], "reason": alog["reason"]})
            else:
                candidates.append(assembled)
                log["assembled"].append(q["id"])
                if alog["substitutions"]:
                    log["substitutions"].append(alog)

    if shuffle:
        shuffle(candidates)
    chosen = _subset_sum(candidates, target_marks)
    total = sum(int(q.get("marks", 0)) for q in chosen)

    warnings = []
    if total < target_marks:
        warnings.append(
            f"Requested {target_marks} marks but only {total} could be assembled "
            f"from in-topic content ({len(candidates)} usable questions). "
            f"The paper is under target — widen the allowed topics or lower the target.")
    # final integrity: no assembled question may contain an ambiguity conflict
    for q in chosen:
        for v in assembly_conflicts(q):
            warnings.append(f"[{q['id']}] {v}")

    return {"questions": chosen, "totalMarks": total, "targetMarks": target_marks,
            "numQuestions": len(chosen), "warnings": warnings, "log": log}
