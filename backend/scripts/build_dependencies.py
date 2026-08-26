"""
build_dependencies.py — Part 4: per-sub-part dependency detection + graph.

Reads scripts/part_extraction/part_manifest.json and, for every sub-part,
detects whether it:
  * references a SHARED diagram/table/context also used by another sub-part
    (from Part 2.2 — sharedAssets.usedByPaths),
  * references the RESULT of a previous sub-part ("using your answer to part (a)",
    "hence", "from part (b)", or a mark-scheme "ft their (a)" follow-through),
  * is otherwise SELF-CONTAINED.

It then builds a per-question dependency graph (Part 4.2) and marks each leaf
`swappable` iff it: has no prior-answer dependency on a sibling, is not depended
on by a sibling, and shares no diagram/context asset. Low-confidence detections
are flagged for review (Part 4.3).

Output: scripts/part_extraction/part_dependencies.json
        (also merges dependency fields back into part_manifest.json)

Run from backend/:  python scripts/build_dependencies.py
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PART_MANIFEST = os.path.join(HERE, "part_extraction", "part_manifest.json")
OUT = os.path.join(HERE, "part_extraction", "part_dependencies.json")

# --- dependency phrase patterns -------------------------------------------- #
# Explicit prior-answer reference WITH a target part, e.g.
# "using your answer to part (a)", "the value found in part (b)(i)".
_EXPLICIT = re.compile(
    r"(?:your\s+(?:answer|value|result|values|results)s?\s+(?:to|from|in|for)\s+"
    r"(?:part\s*)?|(?:found|obtained|calculated)\s+in\s+(?:part\s*)?|"
    r"from\s+part\s*|in\s+part\s*|answer\s+to\s+(?:part\s*)?)"
    r"\(([a-h])\)(?:\s*\(([ivx]{1,4})\))?",
    re.I,
)
# Generic dependency cue with no explicit target -> depends on previous sibling.
_GENERIC = re.compile(r"\b(hence|use\s+your|using\s+your|from\s+your\s+(?:answer|value|result))\b", re.I)
# Mark-scheme follow-through: "ft", "their (a)", "FT their answer".
_MS_FT = re.compile(r"\bft\b|follow[\s-]?through|their\s*\(([a-h])\)", re.I)


def _path_key(path):
    return "".join(path) if path != ["_"] else "_"


def _leaf_index(leaves):
    """label/path lookups for resolving a referenced 'part (a)' to leaf ids."""
    by_letter = {}   # 'a' -> [leaf,...]
    by_full = {}     # ('a','i') -> leaf
    for lf in leaves:
        p = lf["path"]
        if p == ["_"]:
            continue
        by_letter.setdefault(p[0], []).append(lf)
        by_full[tuple(p)] = lf
    return by_letter, by_full


def detect(rec):
    leaves = rec["subParts"]
    ids = {}
    for lf in leaves:
        lf["_id"] = rec["id"] + "_" + "_".join(lf["path"])
        ids[tuple(lf["path"])] = lf["_id"]
    by_letter, by_full = _leaf_index(leaves)

    # shared-asset membership: partId -> [assetId,...]
    asset_of = {}
    for a in rec.get("sharedAssets", []):
        for pth in a.get("usedByPaths", []):
            asset_of.setdefault(rec["id"] + "_" + "_".join(pth), []).append(a["assetId"])

    results = {}
    for i, lf in enumerate(leaves):
        pid = lf["_id"]
        text = (lf.get("questionText", "") or "")
        ms = ""  # per-part MS slice, if present
        msk = rec.get("markSchemeByPart", {})
        ms = msk.get(_path_key(lf["path"]), "") or msk.get("".join(lf["path"]), "")

        depends_on = []          # partIds this leaf needs
        kinds = []
        conf = "high"
        notes = []

        # 1. explicit prior-answer reference with target
        for m in _EXPLICIT.finditer(text + "\n" + ms):
            letter, roman = m.group(1), m.group(2)
            if roman and (letter, roman) in {tuple(l["path"]) for l in leaves}:
                tgt = ids.get((letter, roman))
            else:
                # reference to a letter part -> depend on its last leaf (or the letter leaf)
                cand = by_letter.get(letter, [])
                tgt = cand[-1]["_id"] if cand else None
            if tgt and tgt != pid and tgt not in depends_on:
                depends_on.append(tgt)
                kinds.append("prior_answer")
                notes.append(f"explicit ref to part ({letter}{'' if not roman else '('+roman+')'})")

        # 2. mark-scheme follow-through
        if not depends_on:
            mft = _MS_FT.search(ms)
            if mft:
                letter = mft.group(1)
                if letter and by_letter.get(letter):
                    tgt = by_letter[letter][-1]["_id"]
                    if tgt != pid:
                        depends_on.append(tgt); kinds.append("prior_answer")
                        notes.append(f"mark scheme follow-through to ({letter})")
                        conf = "high"
                elif i > 0:
                    depends_on.append(leaves[i-1]["_id"]); kinds.append("prior_answer")
                    notes.append("mark scheme 'ft' -> previous sub-part"); conf = "medium"

        # 3. generic cue -> previous sibling
        if not depends_on and _GENERIC.search(text):
            if i > 0:
                depends_on.append(leaves[i-1]["_id"]); kinds.append("prior_answer")
                notes.append("generic cue ('hence'/'use your') -> previous sub-part")
                conf = "medium"
            else:
                conf = "low"; notes.append("generic dependency cue but no previous sub-part")

        # 4. shared assets
        assets = asset_of.get(pid, [])
        if assets:
            kinds.append("shared_diagram" if any("fig" in a for a in assets) else "shared_context")
            notes.append(f"shares asset(s): {assets}")

        results[pid] = {
            "questionId": rec["id"],
            "label": lf["label"],
            "path": lf["path"],
            "dependsOnParts": depends_on,
            "sharedAssets": assets,
            "dependencyKind": sorted(set(kinds)),
            "dependencyConfidence": conf if (depends_on or assets) else "high",
            "selfContained": not depends_on and not assets,
            "notes": notes,
        }

    # reverse edges: is any sibling depending on me?
    depended_by = {pid: [] for pid in results}
    for pid, r in results.items():
        for tgt in r["dependsOnParts"]:
            depended_by.setdefault(tgt, []).append(pid)
    for pid, r in results.items():
        shares = bool(r["sharedAssets"])
        needs = bool(r["dependsOnParts"])
        needed = bool(depended_by.get(pid))
        r["dependedOnByParts"] = depended_by.get(pid, [])
        r["swappable"] = not shares and not needs and not needed

    # graph
    graph = {
        "nodes": list(results.keys()),
        "edges": [{"src": pid, "dst": t, "kind": "prior_answer"}
                  for pid, r in results.items() for t in r["dependsOnParts"]],
        "sharedAssetEdges": [{"asset": a["assetId"], "parts": [rec["id"] + "_" + "_".join(p) for p in a.get("usedByPaths", [])]}
                             for a in rec.get("sharedAssets", [])],
    }
    return results, graph


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.load(open(PART_MANIFEST, encoding="utf-8"))
    all_deps = {}
    low = []
    n_prior = n_shared = n_self = 0
    for rec in manifest:
        deps, graph = detect(rec)
        rec["dependencyGraph"] = graph
        for pid, r in deps.items():
            all_deps[pid] = r
            if "prior_answer" in r["dependencyKind"]:
                n_prior += 1
            if r["sharedAssets"]:
                n_shared += 1
            if r["selfContained"]:
                n_self += 1
            if r["dependencyConfidence"] == "low":
                low.append(pid)
        # attach per-leaf dependency fields onto the manifest sub-parts too
        for sp in rec["subParts"]:
            pid = rec["id"] + "_" + "_".join(sp["path"])
            d = deps[pid]
            sp["dependsOnParts"] = d["dependsOnParts"]
            sp["dependencyKind"] = d["dependencyKind"]
            sp["selfContained"] = d["selfContained"]
            sp["swappable"] = d["swappable"]
            sp.pop("_id", None)

    json.dump(all_deps, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    json.dump(manifest, open(PART_MANIFEST, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    total = len(all_deps)
    swap = sum(1 for r in all_deps.values() if r["swappable"])
    print(f"sub-parts: {total}")
    print(f"  with a prior-answer dependency: {n_prior}")
    print(f"  using a shared diagram/context: {n_shared}")
    print(f"  fully self-contained: {n_self}")
    print(f"  independently swappable: {swap}")
    print(f"  low-confidence (need review): {len(low)}")
    print(f"-> {os.path.relpath(OUT)}  (+ merged into part_manifest.json)")


if __name__ == "__main__":
    main()
