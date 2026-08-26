"""
partlevel_schema.py — The part-level question data model (Part 1.2/1.3).

This is the single source of truth for the NEW schema shape used by the
extraction (Stage 2), tagging (Stage 3), dependency (Stage 4), and
filter/substitution (Stage 5/6) code. Everything else imports the TypedDicts
and the validate()/subpart_id()/question_syllabus_codes() helpers from here so
the shape is defined in exactly one place.

Design principles
-----------------
* Additive & backward compatible. Existing flat fields (id, subject, marks,
  topic, questionImageUrl, markSchemeText, calculatorStatus, ...) are retained
  untouched so the current app keeps working during migration. `schemaVersion`
  is bumped to 2 and the new part-level fields are layered on top.
* `topic` (the old single broad bucket) is kept but marked DEPRECATED; the
  authoritative topic signal is now each sub-part's `syllabusCodes`, drawn only
  from scripts/syllabus_codes.json. A question-level `syllabusCodes` union is
  stored for cheap filtering.
* Dependency data (Part 4) is stored redundantly for convenience: each sub-part
  carries `dependsOnParts`/`dependencyKind`, shared assets carry `usedByParts`,
  and a derived `dependencyGraph` gives the explicit adjacency the selector uses.

See docs/part_level_schema.md for the prose specification.
"""
from __future__ import annotations

from typing import List, Literal, Optional, TypedDict

Confidence = Literal["high", "medium", "low"]
DependencyKind = Literal["prior_answer", "shared_diagram", "shared_table", "shared_context"]
AssetKind = Literal["diagram", "table", "figure", "graph"]
ExtractionStatus = Literal["extracted", "partial", "needs_manual_rescan"]


class SubPart(TypedDict, total=False):
    partId: str                 # stable: "<questionId>_<a|b_i|...>"
    label: str                  # display label exactly as Cambridge prints it, e.g. "(b)(ii)"
    path: List[str]             # structural path, e.g. ["b", "ii"] — used for ordering/nesting
    marks: int                  # marks for THIS sub-part (sums to question marks)
    syllabusCodes: List[str]    # 1+ codes from syllabus_codes.json (e.g. ["E6.5"])
    codeConfidence: Confidence  # Part 3.2 — how directly the MS maps to the code
    codeReason: str             # short justification (MS phrase -> code)
    markSchemeText: str         # MS text scoped to this sub-part
    questionText: str           # QP text scoped to this sub-part (if extractable)
    imageRefs: List[str]        # assetIds (sub-part crop + any shared assets) needed to render it
    dependsOnParts: List[str]   # partIds of siblings this part needs to stand alone (Part 4.1)
    dependencyKind: List[DependencyKind]
    dependencyConfidence: Confidence  # Part 4.3
    selfContained: bool         # no prior-answer / shared-context dependency
    swappable: bool             # selfContained AND owns no shared asset => independently swappable


class SharedAsset(TypedDict, total=False):
    assetId: str                # "<questionId>_fig1"
    kind: AssetKind
    imageUrl: str               # "/question_assets/<assetId>.png"
    usedByParts: List[str]      # every partId that references it (never just the first)
    label: str                  # "Fig. 7.1" / "the diagram above" anchor text, if any


class ImageAsset(TypedDict, total=False):
    assetId: str
    type: Literal["subpart", "shared", "whole"]
    imageUrl: str
    forParts: List[str]


class DepEdge(TypedDict):
    src: str                    # partId that has the dependency
    dst: str                    # partId / assetId it depends on
    kind: DependencyKind


class DependencyGraph(TypedDict, total=False):
    nodes: List[str]            # partIds
    edges: List[DepEdge]        # prior-answer / shared-context edges between parts
    sharedAssetEdges: List[dict]  # {"asset": assetId, "parts": [partId,...]}


class PartLevelQuestion(TypedDict, total=False):
    # --- existing flat fields (unchanged, retained for back-compat) ---
    id: str
    subject: str
    paperType: str
    paperCode: str
    year: int
    isSpecimen: bool
    originalQuestionNumber: int
    marks: int
    difficulty: str
    calculatorStatus: str
    questionImageUrl: str       # whole-question image (kept as fallback)
    markSchemeText: str         # full MS blob (kept for AI marking)
    topic: str                  # DEPRECATED broad bucket, retained
    # --- new part-level model ---
    schemaVersion: int          # == 2
    syllabusCodes: List[str]    # UNION of all sub-part codes (question-level)
    subParts: List[SubPart]
    sharedAssets: List[SharedAsset]
    imageAssets: List[ImageAsset]
    dependencyGraph: DependencyGraph
    extractionStatus: ExtractionStatus
    extractionNotes: str
    tagMismatch: bool           # Part 3.3 — old broad topic disagreed with new part tags


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def subpart_id(question_id: str, path: List[str]) -> str:
    """Deterministic, stable sub-part id: joins the path with underscores."""
    return f"{question_id}_" + "_".join(path)


def question_syllabus_codes(q: PartLevelQuestion) -> List[str]:
    """Sorted union of every sub-part's syllabus codes."""
    codes: set[str] = set()
    for sp in q.get("subParts", []) or []:
        codes.update(sp.get("syllabusCodes", []) or [])
    return sorted(codes)


def build_dependency_graph(q: PartLevelQuestion) -> DependencyGraph:
    """Derive the explicit adjacency (Part 4.2) from sub-parts + shared assets."""
    parts = q.get("subParts", []) or []
    nodes = [sp["partId"] for sp in parts]
    edges: List[DepEdge] = []
    for sp in parts:
        for dep in sp.get("dependsOnParts", []) or []:
            # kind: prefer a prior_answer edge if that's why it depends
            kinds = sp.get("dependencyKind", []) or []
            kind = "prior_answer" if "prior_answer" in kinds else (
                kinds[0] if kinds else "shared_context")
            edges.append({"src": sp["partId"], "dst": dep, "kind": kind})  # type: ignore
    shared_edges = [
        {"asset": a["assetId"], "parts": a.get("usedByParts", [])}
        for a in q.get("sharedAssets", []) or []
    ]
    return {"nodes": nodes, "edges": edges, "sharedAssetEdges": shared_edges}


def validate(q: PartLevelQuestion, valid_codes: Optional[set] = None) -> List[str]:
    """Return a list of human-readable problems; empty list == valid.

    Checks the invariants the rest of the pipeline relies on:
      * sub-part marks sum to the question total
      * every sub-part code exists in the syllabus taxonomy (if provided)
      * every dependsOnParts / usedByParts reference resolves to a real partId
      * a part that owns a shared asset is not marked swappable
    """
    problems: List[str] = []
    parts = q.get("subParts", []) or []
    part_ids = {sp.get("partId") for sp in parts}

    if parts:
        s = sum(int(sp.get("marks", 0) or 0) for sp in parts)
        if s != int(q.get("marks", 0) or 0):
            problems.append(f"{q.get('id')}: sub-part marks {s} != question marks {q.get('marks')}")

    for sp in parts:
        if not sp.get("syllabusCodes"):
            problems.append(f"{sp.get('partId')}: no syllabusCodes")
        if valid_codes is not None:
            for c in sp.get("syllabusCodes", []) or []:
                if c not in valid_codes:
                    problems.append(f"{sp.get('partId')}: code {c!r} not in syllabus taxonomy")
        for dep in sp.get("dependsOnParts", []) or []:
            if dep not in part_ids:
                problems.append(f"{sp.get('partId')}: dependsOnParts -> unknown part {dep!r}")

    for a in q.get("sharedAssets", []) or []:
        for p in a.get("usedByParts", []) or []:
            if p not in part_ids:
                problems.append(f"{a.get('assetId')}: usedByParts -> unknown part {p!r}")
        # a part that uses a shared asset must not be independently swappable
        for p in a.get("usedByParts", []) or []:
            for sp in parts:
                if sp.get("partId") == p and sp.get("swappable"):
                    problems.append(f"{p}: marked swappable but shares asset {a.get('assetId')}")
    return problems
