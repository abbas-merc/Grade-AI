# Part-level tagging, dependency-aware filtering & smart substitution — Final Report

Rebuilds GradeAI's question-bank tagging/extraction/filtering/assembly to be
**sub-part-level** and **syllabus-code-accurate**, so a teacher who selects a set
of topics never receives a question containing a hidden out-of-topic sub-part.

Authoritative taxonomy source: `docs/igcse_0580_syllabus_2025-2027.pdf`
(Cambridge IGCSE Mathematics 0580, Version 3, exams 2025–2027) — downloaded from
cambridgeinternational.org and parsed; **no code is invented**, every tag
references `backend/scripts/syllabus_codes.json`.

---

## Part 0 — Inventory (as-found)

| | |
|---|---|
| Questions in bank | **538** across 20 papers, all IGCSE Math 0580 (81 backfill + 457 batch expansion) |
| Old schema | flat Firestore `questions`; **one broad `topic` per whole question**, one whole-question PNG, one `markSchemeText` blob |
| Old selection | `routers/paper_generator.py` → `_fetch_pool` (subject+calc+broad-topic) → subset-sum over whole questions — the source of the bug |
| Source PDFs | all 24 present (20 in `backend/papers/`, 4 backfill in `~/Downloads`) |

---

## What was built

| File | Purpose |
|---|---|
| `backend/scripts/build_syllabus_codes.py` → `syllabus_codes.json` | Part 1.1 — parse the official PDF into the canonical taxonomy (9 sections, 59 subsections, 103 codes, 15 Extended-only) |
| `backend/scripts/partlevel_schema.py` + `docs/part_level_schema.md` | Part 1.2/1.3 — the schemaVersion-2 data model + validator |
| `backend/scripts/build_part_extraction.py` | Part 2 — per-sub-part structure, marks, text, image crops, shared-asset detection |
| `backend/scripts/tag_subparts.py` | Part 3 — AI tagging to syllabus codes with confidence |
| `backend/scripts/build_dependencies.py` | Part 4 — dependency detection + per-question graph |
| `backend/partlevel_selection.py` | Part 5 filter + Part 6 substitution (pure, tested) |
| `backend/routers/paper_generator.py` (`POST /api/generate-paper/partlevel`) | Part 5.1 — live topic-safe endpoint |
| `backend/scripts/build_partlevel_bank.py` → `part_level_questions.json` | merge everything into final docs |
| `backend/scripts/seed_partlevel_bank.py` | gated Firestore seed (dry-run by default) |
| `backend/scripts/test_partlevel.py` | Part 5.3 + Part 7 tests |

---

## Part 8 deliverables

### 1. Totals processed
- **538 questions**, **994 sub-part leaves** (the earlier ~992 was a heuristic; this is the real extracted count).
- **0 questions need manual re-scan** — every question's source PDF was present, so all were re-extractable (Part 2.3).
- **2 questions flagged `partial`** because per-part marks don't sum to the bank total (dropped/merged sub-part) — surfaced, not shipped silently:
  - `058023_s24_Q13` (Venn "shade the region" — part (a) label not emitted by the PDF)
  - `058043_s24_Q1` (a nested `(a)/(b)` answer-list inside part (a)(iv))
- Per-part marks reconcile to the authoritative bank total on **536/538** questions.

### 2. Sub-parts needing a human tag check (Part 3.2)
- **Low confidence: 0.** **Medium confidence: 35.** **Untagged: 3.**
- The 3 untagged are all zero-mark / empty container leaves (nothing to tag):
  `058042_m24_Q7_b`, `058042_s24_Q9_b_ii`, `058041_s25_Q14_b`.
- The 35 medium-confidence tags (examples): `058021_2024_Q1 (whole)→E7.4`,
  `058021_2024_Q7 (b)→E5.3,E6.1`, `058041_2024_Q7 (a)(ii)→E5.4`. Full list in
  `backend/scripts/part_extraction/review_lists.json`.

### 3. Questions with low-confidence dependency detection (Part 4.3)
- **Low confidence: 0.** **Medium confidence: 42** — all are the heuristic
  "mark-scheme `ft` / generic `hence` → previous sub-part" inferences (no explicit
  part label), e.g. `058041_2024_Q8_c`, `058041_2024_Q9_a_ii`. Explicit
  `"answer to part (a)"` references and shared-asset links are high-confidence.

### 4. Old broad tag vs new part-level reality (Part 3.3)
- **154 questions** where the old broad `topic` shares **no** syllabus section with the new part-level codes (the broad tag was simply wrong).
- **208 questions** have at least one sub-part outside the old broad bucket.
- **66 questions** have sub-parts genuinely spanning **≥2 syllabus sections** — the exact "geometry question with a trig sub-part" hazard, now detectable.

### 5. Test output (Part 7) — actual, not described
Run: `python scripts/test_partlevel.py` → **9 passed, 0 failed (exit 0)**.

- **Test 1 (5.3 / 7.1)** — exclude trigonometry. Real mix `058021_2024_Q7`
  (old topic "geometry") = `(a) E5.5` + `(b) E5.3,E6.1` (Pythagoras/trig).
  Excluding section 6 → classified `partial` → **`(b)` substituted with an
  E2.6 donor of equal 4 marks**. Generated a 60/60-mark paper: 4 questions,
  482 whole / 7 assembled / 49 excluded, **zero trig sub-parts leaked**.
- **Test 2 (7.2)** — `058041_2024_Q5`: `(a)(iii) [E5.3]` depends on
  `(a)(ii) [E7.3]`. Excluding E7.3 → **whole question EXCLUDED** ("kept (a)(iii)
  depends on excluded (a)(ii)"). The dependency is never split.
- **Test 3 (7.3)** — `058041_2024_Q4`: `ctx_a` shared by `(a)(i)(ii)(iii)`.
  All three link to the same asset; none is `swappable`. Excluding one member's
  section → **whole question EXCLUDED** ("shares an asset with a kept sub-part").
  The shared group is never partially broken / orphaned.

### 6. Automated & verified vs. still needs your review

**Fully automated and verified working**
- Syllabus taxonomy extraction (59 subsections, validated against the PDF).
- Per-sub-part structure + marks (536/538 reconcile) + per-part image crops
  (999 part crops + 242 shared-asset crops rendered) + shared-asset detection
  (verified visually on the Q3 shared table).
- Syllabus tagging of 994 sub-parts (957 high-confidence), cost ≈ $2.41.
- Dependency graph (52 prior-answer edges, 530 shared-asset links).
- Filter + substitution logic and the 3 Part-7 scenarios (9/9 assertions pass).
- Topic→codes mapping in the live endpoint (geometry admits E4.6, excludes E6.5).

**Needs your review before the DY Patil demo**
1. **Seed the part-level bank to Firestore** — `scripts/seed_partlevel_bank.py`
   is a dry-run; run with `--commit` after review. The new endpoint returns empty
   until then. (Left gated, matching the project's build-review-then-seed rule.)
2. **35 medium-confidence tags + 42 medium-confidence dependencies** — spot-check
   the lists in `review_lists.json` (auto-tags are ground truth only after this).
3. **2 partial-extraction questions** (`058023_s24_Q13`, `058043_s24_Q1`) — either
   accept them excluded from generation or hand-fix their sub-part split.
4. **PDF/app rendering of assembled papers** — the endpoint returns per-part
   `subParts` with image URLs; the existing PDF generator still renders one image
   per question. Rendering an assembled (substituted) question from its part crops
   is the remaining UI wiring; the data + selection are done.

Nothing above is marked complete without the test evidence in section 5.
