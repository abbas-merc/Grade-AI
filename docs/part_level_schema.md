# Part-level question schema (v2)

Authoritative code definitions: `backend/scripts/partlevel_schema.py`
(TypedDicts + `validate()`). This document is the prose specification.

## Why

The old schema tagged each **whole question** with one broad topic bucket
(`geometry`, `algebra`, …). Real IGCSE questions mix syllabus points across
sub-parts (part (a) geometry, part (b) trigonometry), so a broad tag cannot tell
a teacher "this question is safe if I haven't taught trig". v2 moves the topic
signal down to the **sub-part**, keyed to the canonical Cambridge codes in
`syllabus_codes.json`, and records the **dependencies** between sub-parts so a
paper generator can safely include, swap, or exclude individual sub-parts.

## Backward compatibility

v2 is **additive**. Every existing flat field is retained so the current app and
`paper_generator.py` keep working during migration:
`id, subject, paperType, paperCode, year, isSpecimen, originalQuestionNumber,
marks, difficulty, calculatorStatus, questionImageUrl, markSchemeText, topic`.

`topic` is kept but **DEPRECATED** — superseded by sub-part `syllabusCodes`.
`schemaVersion: 2` flags a migrated document.

## Question document (Firestore `questions`)

| Field | Type | Meaning |
|---|---|---|
| `schemaVersion` | int | `2` for migrated docs |
| `syllabusCodes` | string[] | **Union** of all sub-part codes — cheap question-level filter |
| `subParts` | SubPart[] | Ordered list of sub-parts (see below) |
| `sharedAssets` | SharedAsset[] | Diagrams/tables referenced by **>1** sub-part |
| `imageAssets` | ImageAsset[] | Registry of every crop this question owns |
| `dependencyGraph` | object | Derived adjacency (Part 4.2) |
| `extractionStatus` | `extracted` \| `partial` \| `needs_manual_rescan` | Part 2.3 |
| `extractionNotes` | string | Why a re-scan is needed, etc. |
| `tagMismatch` | bool | Old broad topic disagreed with new part tags (Part 3.3) |

### SubPart

| Field | Type | Meaning |
|---|---|---|
| `partId` | string | Stable id `"<questionId>_<a\|b_i\|…>"` |
| `label` | string | Display label exactly as printed, e.g. `"(b)(ii)"` |
| `path` | string[] | Structural path, e.g. `["b","ii"]` (ordering/nesting) |
| `marks` | int | Marks for **this** sub-part; sums to question `marks` |
| `syllabusCodes` | string[] | 1+ codes from `syllabus_codes.json` (a part can touch >1 topic) |
| `codeConfidence` | `high`\|`medium`\|`low` | How directly the MS maps to the code (Part 3.2) |
| `codeReason` | string | MS phrase → code justification |
| `markSchemeText` | string | MS text scoped to this sub-part |
| `questionText` | string | QP text scoped to this sub-part (if extractable) |
| `imageRefs` | string[] | assetIds needed to render it (own crop + shared assets) |
| `dependsOnParts` | string[] | partIds this part needs to stand alone (Part 4.1) |
| `dependencyKind` | `prior_answer`\|`shared_diagram`\|`shared_table`\|`shared_context`[] | why |
| `dependencyConfidence` | `high`\|`medium`\|`low` | Part 4.3 |
| `selfContained` | bool | No prior-answer / shared-context dependency |
| `swappable` | bool | `selfContained` **and** owns no shared asset ⇒ independently swappable |

### SharedAsset (Part 2.2)

A diagram/table used by more than one sub-part is a **distinct reusable asset**,
never cropped into only the first sub-part that mentions it.

| Field | Type | Meaning |
|---|---|---|
| `assetId` | string | `"<questionId>_fig1"` |
| `kind` | `diagram`\|`table`\|`figure`\|`graph` | |
| `imageUrl` | string | `/question_assets/<assetId>.png` |
| `usedByParts` | string[] | **Every** dependent partId (not just the first) |
| `label` | string | `"Fig. 7.1"` / `"the diagram above"` anchor text |

### ImageAsset registry

Each crop the question owns: sub-part crops (`type:"subpart"`), shared assets
(`type:"shared"`), and the legacy whole-question image (`type:"whole"`).

## Dependency graph (Part 4.2)

`dependencyGraph = { nodes: partId[], edges: {src,dst,kind}[], sharedAssetEdges: {asset,parts[]}[] }`

* A sub-part with **zero** in/out edges and no shared asset ⇒ `swappable:true`
  (independently substitutable).
* A sub-part with edges can only be included **with everything it depends on**,
  or excluded entirely — never partially (enforced in Stage 5/6).

## Invariants (enforced by `validate()`)

1. Sub-part marks sum to the question total.
2. Every sub-part code exists in `syllabus_codes.json`.
3. Every `dependsOnParts` / `usedByParts` reference resolves to a real `partId`.
4. A part that uses a shared asset is **not** marked `swappable`.
