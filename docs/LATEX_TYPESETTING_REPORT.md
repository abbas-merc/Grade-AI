# LaTeX paper typesetting with Century Gothic — final report

Replaces both previous paper-generation paths — plain PDF-extracted text (which
mangled maths notation and lost layout) and whole-question screenshots (not
editable, wrong font) — with a real XeLaTeX typesetting pipeline.

Everything below was verified by running it. Where something could **not** be
verified in this environment, that is stated explicitly rather than assumed.

---

## 1. Is LaTeX viable in the deployment environment? (Part 0.1)

**Yes — at ~75 MB, not gigabytes.**

| Route | Installed size | Verdict |
|---|---|---|
| Full TeX Live | ~5 GB | rejected |
| `apt install texlive-xetex texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended` | ~1.5–2 GB | rejected |
| **Tectonic binary + pre-warmed resource cache** | **~30 MB binary + 45 MB cache (measured)** | **chosen** |

[Tectonic](https://tectonic-typesetting.github.io) is the real XeTeX engine plus
`xdvipdfmx` in one statically-linked executable. It fetches the individual
`.sty` / `.otf` files a document needs from a signed bundle and caches them, so
you pay for what you use instead of installing a distribution.

**Engine: XeLaTeX**, not LuaLaTeX. Tectonic wraps XeTeX only, and XeTeX's
`fontspec` + `unicode-math` support is exactly what loading an arbitrary system
font requires. Going LuaLaTeX would have meant a full TeX Live install for no
functional gain.

**Packages actually needed** (all pulled automatically from the bundle):
`fontspec`, `unicode-math`, `amsmath`, `geometry`, `graphicx`, `enumitem`,
`needspace`, `array`, `longtable`, `xcolor`, `fancyhdr`, plus the fonts
`latinmodern-math.otf` and the TeX Gyre Adventor family. No `tikz` — every
diagram is an extracted image, so nothing is drawn in-document.

### What was changed to make it work

* `backend/Dockerfile` — installs the engine and **pre-warms the resource cache
  at build time** with a document that loads every package the templates use, so
  a cold container performs no network I/O to render a paper. This matters
  because Railway's filesystem is ephemeral: an un-warmed cache would re-download
  on every restart.
* `backend/railway.toml` — builder switched from `nixpacks` to `dockerfile`.
  nixpacks has no clean hook for installing and warming a binary like this.
* `backend/scripts/install_tectonic.py` — the same install + warm step for local
  development (`python scripts/install_tectonic.py`). The binary lands in
  `backend/tools/` and is git-ignored.

### ⚠️ What was NOT verified

**The Railway deployment itself has not been built or deployed from here.** This
machine has no Docker daemon and no Railway CLI credentials. The engine, the
bundle, the fonts, the templates and every compile below were verified locally
against the *same* Tectonic 0.17.0 and the *same* bundle the Dockerfile
installs — but the first `docker build` is still unrun. Expect to confirm two
things on the first deploy:

1. the build has outbound network access to `github.com` and the Tectonic bundle
   CDN (it does on Railway's default builder, but confirm);
2. `GET /api/generate-paper/typesetting-status` reports `engine.available: true`
   — that endpoint exists precisely so this is a one-request check.

If the Docker build turns out not to be an option, the fallback is unchanged and
already wired: set `GA_PDF_ENGINE=images` and the previous reportlab renderer
serves the same endpoints with the same response shape.

---

## 2. Century Gothic licensing — and what font is in the PDF right now (Part 0.2)

**Century Gothic is a commercial Monotype typeface.** It is not free, not
redistributable, and not in any TeX distribution. It *is* present on this
development machine (`C:\Windows\Fonts\GOTHIC.TTF`, from Microsoft Office) and is
what the verification PDFs are typeset in.

**A Windows/Office font licence does not permit copying that file into a Linux
server image.** So the resolver (`backend/utils/latex/fonts.py`) picks in this
order and always says which it used:

| Order | Source | mode | Licence action needed |
|---|---|---|---|
| 1 | `GA_CENTURY_GOTHIC_DIR` | `licensed` | confirm the school's licence covers server-side embedding |
| 2 | `backend/fonts/century_gothic/` | `licensed` | same |
| 3 | OS font directory | `system` | **yes** — dev only |
| 4 | **TeX Gyre Adventor** (GUST Font Licence — the URW Gothic revival, the standard open stand-in for Century Gothic) | `fallback` | none |

Right now, locally, mode is **`system`** — real Century Gothic, flagged. On a
fresh Railway container with no font supplied it will be **`fallback`** — TeX
Gyre Adventor, also flagged.

Which one went into a given PDF is reported three ways, so nobody has to guess:
the `X-GradeAI-Paper-Font` response header, the
`GET /api/generate-paper/typesetting-status` endpoint, and the test harness,
which reads the embedded font names back out of the produced PDF.

**Action for the school:** supply licensed Century Gothic files and point
`GA_CENTURY_GOTHIC_DIR` at them (see
`backend/fonts/century_gothic/README.md`). Until then, papers render in TeX Gyre
Adventor in production.

Maths, incidentally, is *also* in the document font: `unicode-math` maps Latin
letters and digits back to Century Gothic, leaving only the symbol glyphs
(√ ⩽ ∩ × −) — which Century Gothic does not contain — to Latin Modern Math. Left
alone, LaTeX would have set every formula in Computer Modern, and a paper with
Century Gothic prose and Computer Modern algebra fails the font requirement just
as surely as the old screenshots did.

---

## 3. Extraction accuracy (Parts 1.1–1.3)

The extraction (`backend/scripts/latex_extractor.py`, driven by
`backend/scripts/build_latex_extraction.py`) sends every sub-part's crop —
plus the question stem, plus each letter part's own introduction — in one call
per question, and returns LaTeX under a JSON schema.

**Tested on 32 real bank questions → 69 sub-parts → 311 LaTeX fragments**
(question text, mark-scheme answers and every individual mark point).

| Result | Count |
|---|---|
| Fragments compile-checked against the real document preamble | **311** |
| **Compile failures** | **0** |
| Sub-parts flagged for human review | **0** |
| Medium-confidence tags (model inferred a character) | 11 |
| Low-confidence tags | 0 |
| Sub-parts with no LaTeX at all | 0 |
| "Plain text" suspects (prose with no notation) | 2 — both genuinely have none |

Coverage spans pure algebra, geometry with angle notation, trigonometry,
vectors (column vectors + magnitude), probability with set notation, statistics
with a cumulative-frequency graph, and long Paper-4 questions with nested
`(d)(i)/(ii)` sub-parts.

Notation verified in the rendered output: `\frac`, `\dfrac`, `\sqrt[n]`,
super/subscripts, `\begin{pmatrix}` column vectors, `\overrightarrow{AB}` and
bold `\mathbf{a}` (both exactly as the 0580 syllabus prints them),
`\leqslant`/`\geqslant`, `\in`/`\notin`/`\cup`/`\cap`/`\emptyset`,
`\mathcal{E}` for the universal set, `\mathrm{P}(A\cap B)`,
`\mathrm{f}^{-1}(x)`, standard form `1.5\times10^{-3}`, degrees `47^\circ`, and
units as `8.4\,\text{cm}`.

### How "0 failures" is actually enforced

Three gates, in order — none of them trusts the model:

1. **Sanitiser** (`latexify.sanitize_fragment`) strips preamble-only and
   filesystem-touching commands (`\input`, `\usepackage`, `\write`, …).
2. **Deterministic repair.** Models reliably wrap `$w=158$, $x=76$` but just as
   reliably return a bare `3x^{3}+5x^{2}-34x-24`, which is correct maths and a
   hard error in text mode. `ensure_math_wrapped` fixes that structurally
   instead of hoping the prompt is obeyed. This is idempotent and re-runs over
   already-stored data, so tightening it improves earlier extractions for free.
   It caught the only two real failures in the first run.
3. **Real compile probe.** Every fragment is compiled against the actual
   document preamble, in batches, bisecting on failure so a bad fragment is
   attributed exactly. Anything that fails lands in
   `scripts/part_extraction/latex_review.json`, not in a paper.

### Cost, and what is left to extract

| | |
|---|---|
| Model | `claude-opus-5` (override with `GA_LATEX_EXTRACT_MODEL`) |
| Measured | $0.031–$0.074 per question, mean ≈ $0.045 |
| Questions extracted so far | 32 of 538 |
| Projected cost for the remaining 506 | **≈ $23** |

The script is resumable and takes `--paper` / `--ids` / `--limit`, so the rest of
the bank can be done incrementally.

### ⚠️ 10 questions are pending re-extraction

Adding letter-part introductions (see §5) changed what the extractor is fed for
questions whose `(b)` carries its own stem, so those 10 stored questions were
cleared to be redone — and **the Anthropic API credit balance ran out
mid-re-extraction**, so they are currently absent from
`part_latex.json`:

```
058021_s25_Q17  058021_s25_Q21  058041_2024_Q4   058042_s24_Q10  058042_s24_Q11
058042_s24_Q3   058042_s24_Q4   058042_s24_Q7    058042_s24_Q9   0580_2_SP_2025_Q16
```

Recovery is one command once credits are topped up (it is resumable, so it will
only do these ten):

```
python scripts/build_latex_extraction.py --ids 058021_s25_Q17,058021_s25_Q21,058041_2024_Q4,058042_s24_Q10,058042_s24_Q11,058042_s24_Q3,058042_s24_Q4,058042_s24_Q7,058042_s24_Q9,0580_2_SP_2025_Q16
```

A paper containing a question with no extraction still generates — it falls back
to raw-text LaTeX (correct symbols, no reconstructed notation) — and every such
sub-part is counted and reported in the `X-GradeAI-Latex-Fallbacks` header
rather than passed off as a real conversion.

---

## 4. End-to-end test results (Part 5)

`python scripts/test_latex_paper.py` — **all checks pass**. It does not settle
for "the compiler didn't complain"; it reads the produced PDFs back.

```
PART 0    LaTeX engine available            Tectonic 0.17.0
PART 5.1  9 coverage questions assembled, question paper compiled (1.9 s)
          no sub-part fell back to raw-text LaTeX (0 fallbacks)
PART 5.2  embedded fonts: CenturyGothic, CenturyGothic-Bold,
          CenturyGothic-Italic, LatinModernMath-Regular
          document font really is Century Gothic     PASS
          no Computer Modern fallback in body text   PASS
          every non-maths font is the document font  PASS
PART 5.3  1 mark  ->  2 ruled lines (17 mm)
          2 marks ->  4 ruled lines (34 mm)
          3 marks ->  6 ruled lines (51 mm)
          4 marks ->  8 ruled lines (68 mm)
          rendered ruled-line count == template intent (114 == 114)
          21 mark indicators, right-aligned to within 0.00 pt
PART 5.4  mark scheme compiled (1.4 s), same font,
          Question | Answer | Marks | Partial marks columns present,
          Cambridge codes present: A1 B1 B2 M1 M2 M3 SC1
PART 2.1  letter-part introduction printed above its roman children  PASS
PART 3.1  malformed LaTeX -> HTTP 422, blames the exact sub-part       PASS
PART 3.2  compile timeout configured (120 s) and enforced (-> HTTP 504)
PART 5.5  question paper 12 pages, mark scheme 2 pages, PNGs written
```

### 5.2 — the font check, specifically

`fontspec` substitutes silently, so "it compiled" proves nothing. The test opens
the PDF, lists every embedded font, normalises the names and asserts that the
document font matches what the resolver said it chose — and separately asserts
that **no** Computer Modern face appears in the body text, which is the exact
signature of a silent fallback. Both pass.

### 5.3 — answer space, measured not assumed

`ANSWER_LINES_PER_MARK = 2` (configurable via `GA_LATEX_ANSWER_LINES_PER_MARK`),
clamped to `[2, 12]`, at an `8.5 mm` pitch — Cambridge's own writing-line
spacing. The test counts the ruled lines *rendered in the PDF* (filtering by
width, so the cover sheet's dot leaders don't inflate the count) and compares
them with what the template intended: 114 vs 114.

### 5.5 — what was visually checked

Every page of the verification paper and mark scheme was rendered to PNG and
inspected. Confirmed by eye:

* cover sheet: school name, candidate/centre grid, instructions block, the
  calculator line following the paper type, the total-mark line;
* `1` / `(a)` / `(i)` numbering sharing one line, Cambridge-style, with the body
  hanging at a consistent indent;
* diagrams anchored inside the sub-part that needs them, centred, at sane size —
  the cumulative-frequency graph, the probability tree, the angle diagram, the
  kite figure;
* fractions, surds, indices, column vectors and set notation set as real maths;
* ruled answer space with the mark indicator right-aligned on the final line;
* the mark scheme as a four-column Cambridge table with `M1`/`A1`/`B1` codes and
  properly typeset working;
* running footer (paper code, page number, school) on every page.

Output: `backend/scripts/part_extraction/latex_test_output/`
(`question_paper.pdf`, `mark_scheme.pdf`, and per-page PNGs).

---

## 5. What was built

| File | Purpose |
|---|---|
| `backend/utils/latex/config.py` | every tunable constant; all overridable with a `GA_LATEX_` env var |
| `backend/utils/latex/fonts.py` | font resolution + honest licence reporting |
| `backend/utils/latex/latexify.py` | escaping, Symbol-font PUA repair, sanitiser, validator, bare-maths repair |
| `backend/utils/latex/templates.py` | paper dict → `.tex` (question paper + mark scheme) |
| `backend/utils/latex/engine.py` | bounded compile + error attribution + batch fragment probe |
| `backend/utils/latex/assemble.py` | generator response → the structured paper dict |
| `backend/utils/latex/service.py` | the one call the routers make; typed failures |
| `backend/scripts/latex_extractor.py` | Part 1 — vision extraction that emits LaTeX |
| `backend/scripts/build_latex_extraction.py` | batch driver + compile probe + review lists |
| `backend/scripts/build_part_figures.py` | diagram-only crops, question stems, letter-part stems |
| `backend/scripts/publish_latex_assets.py` | copy those crops into `static/` |
| `backend/scripts/install_tectonic.py` | install + warm the engine |
| `backend/scripts/test_latex_paper.py` | Part 5 end-to-end verification |
| `backend/Dockerfile`, `.dockerignore`, `railway.toml` | deployment |

### Two problems found in the existing extraction, and fixed

**The stem was missing entirely.** `build_leaves` assigns the band above the
first `(a)` to no sub-part, so "On any day the probability that it rains is ⅓…"
was never in the extraction input — the generated question would have started at
"(a) In a period of 60 days…" with no scenario. Now extracted as a question
stem, and separately as a **letter-part introduction** where a `(b)` carries its
own scenario for its roman children (46 questions in the bank do). Fixing this
turned up the pipeline's only low-confidence flag, which is what pointed at it.

**The existing shared-figure crops are mostly whole-question screenshots.**
`_figures_in_regions` treats Cambridge's full-height page-edge registration bar
as a drawing; because it spans every question on the page, the "figure" band
stretched from the top of the question to the bottom of its answer space. Using
those crops would have printed each question's text twice. `build_part_figures.py`
does its own stricter detection — content-column filter, height guard,
full-width-rule filter, and a pass that trims the source paper's own question
number out of the top padding. `build_part_extraction.py` is untouched, so the
existing bank is unaffected.

### API surface (Part 3.3 — nothing downstream changes)

The app's existing calls are unchanged: same paths, same POST body, same raw-PDF
response with a `Content-Disposition` attachment header.

| Endpoint | Change |
|---|---|
| `POST /api/generate-paper/download-question-paper` | now typeset with LaTeX; `?engine=images` reverts |
| `POST /api/generate-paper/download-mark-scheme` | same |
| `POST /api/generate-paper/partlevel/download-question-paper` | **new** — the topic-safe paper, LaTeX only (an assembled paper has no single screenshot) |
| `POST /api/generate-paper/partlevel/download-mark-scheme` | **new** |
| `GET  /api/generate-paper/typesetting-status` | **new** — engine + font readiness |

New response headers on a LaTeX render: `X-GradeAI-Paper-Engine`,
`X-GradeAI-Paper-Font`, `X-GradeAI-Latex-Fallbacks`, `X-GradeAI-Compile-Seconds`.

Failure modes are typed, never a crash: **422** malformed LaTeX (naming the
sub-part), **503** engine missing (naming the install step), **504** compile
timeout.

`GA_PDF_ENGINE=images` reverts everything to the previous renderer without a
redeploy.

---

## 6. Known limitations and edge cases

1. **Long sub-part text is handled, but not free.** A block whose estimated
   height fits within 82 % of the text block is emitted inside a `minipage`,
   which LaTeX physically cannot split — that is the guarantee that text,
   diagram and answer space stay together. A block taller than that cannot be
   kept whole by any mechanism; it falls back to flowing text with a
   `\needspace` guard, so it starts with room for its opening lines but can
   break. This affects a small number of very long Paper-4 sub-parts.
2. **Atomic blocks can leave whitespace at a page foot.** Correct behaviour, but
   a 10-mark sub-part that doesn't fit pushes to the next page and leaves a gap.
   Real Cambridge papers do the same; tune with
   `GA_LATEX_ANSWER_LINES_PER_MARK` if a school wants tighter papers.
3. **Data tables inside a question are transcribed as LaTeX `tabular`, not
   cropped.** Verified compiling in the sample, but a wide or unusual table is
   the most likely thing to overflow the column. Worth a look when the rest of
   the bank is extracted.
4. **Graph-paper answer grids are not reproduced.** A question that says "draw
   the graph on the grid" gets ruled answer lines instead of a grid. The grid
   image exists in `question_figures` when it was detected as a figure, but
   there is no "answer grid" answer style yet.
5. **`ANSWER_LINES_MAX = 12` clamps the biggest questions.** A 12-mark part gets
   the same space as a 6-mark one. Deliberate — a full page of dots per question
   is worse — but it is a cap, not a proportional allocation.
6. **10 questions await re-extraction** (§3) and any question with no extraction
   renders via the raw-text fallback: correct symbols, no reconstructed
   notation, counted and reported.
7. **`latexByQuestion` on the request body is trusted content.** It exists for
   callers that already hold extraction output and for the test harness. It is
   sanitised and validated like everything else (no `\input`, no shell escape,
   and Tectonic runs without shell-escape), but it is not a public input path.
8. **Not verified on Railway** (§1).

---

## 7. Honest assessment: is this demo-ready?

**Yes for a demo generated on a machine that has the engine and the font —
which is what a demo is. Not yet for unattended production.**

Ready now:

* the pipeline produces papers and mark schemes that look like real Cambridge
  papers, in Century Gothic, with real maths notation and real answer space;
* 311 fragments compile with zero failures and zero review flags;
* failures are typed, attributed and non-fatal to the worker;
* the previous renderer is one env var away if anything goes wrong.

Needed before it runs unattended:

1. **Build and deploy the Docker image once** and check
   `/api/generate-paper/typesetting-status`. This is the single largest unknown.
2. **Get the licensed Century Gothic files from the school**, or accept TeX Gyre
   Adventor in production. Right now production would silently be Adventor —
   silently only in the sense that nobody reads headers; the pipeline does say so.
3. **Finish the extraction** — 32 of 538 questions are done. Until the rest are,
   most generated papers will contain raw-text fallbacks. ≈ $23 and one resumable
   command.
4. **Re-extract the 10 cleared questions** (blocked on API credit).

The order matters: (1) is a yes/no that gates everything, (3) is the bulk of the
remaining work, and (2) is a decision for the school rather than an engineering
task.
