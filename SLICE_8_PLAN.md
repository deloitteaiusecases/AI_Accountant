# Slice 8 — make the GL path a first-class citizen (region detection + recompile anchor)

> Two related engine follow-ups that finish the TB-first architecture **before** anything sits on top.
> Both make the **GL path** first-class: (A) route GL ingestion through the slice-4 parsing front-end
> (region detection + confirm-gate), and (B) thread the FaceTB anchor through `recompute()` so the R8
> loop reconciles to the TB line.
> ~~No code until reviewed~~ — **✅ BUILT (2026-06-10)** after the literals-grep came back clean
> (engine has no entity amount). All 31 suites green.

## Result (what to look at)
- **Part A** — `ingest_workbook` now routes through the front-end: `propose_regions(kind="GL")` (a
  GL-aware row classifier carrying R14: a posting stands on a gl_account / transactional id; an
  amount-only row is a footer) → `confirm_region` (the gate). For GL the boundary's job is **finding
  the real header (skipping a title/preamble block) + the confidence gate**; the row disposition below
  the header (footers→control totals, orphans, continuations, column-shifts) stays with
  `_region_to_postings`'s R14, **unchanged** → clean GLs ingest **byte-identical**.
  - **No-regression:** the three real GLs unmoved (Investments 4,256,555,000 / Prepayments
    833,702,945.67 / PP&E 929m/−221m, orphans −59,130,178.49) — proven by every existing suite still
    passing.
  - **New guard** (`tests/test_gl_messy_region.py`): a messy GL with a **title block above the header**
    → header found below it, data extracted (region=sheet would have failed); **footer → control
    total** (not a posting); an **interior subtotal → `region_needs_review`, NOT extracted** (R24).
  - Fixed mid-build: the side-by-side-table heuristic false-fired on wide SAP GLs — rebased on the
    header's width + a substantial-share threshold (not one stray cell / not the resolved columns).
- **Part B** — `recompute(..., facetb=...)` threads the FaceTB anchor (slice-5 contract reaches the R8
  loop). `tests/test_recompute_anchor.py`: clean case → **BUILT**; no-facetb → PARTIAL (back-compat);
  **held-out reinstatement → BLOCK-with-a-question** — closing moves to 774,572,767.18, gap is the
  held-out **−59,130,178.49** (−59,130.18 SAR'000 at the TB's stored precision), status **BLOCKED**,
  question queued. A tie here would be the bug.
- **The literals discipline held:** engine has **none** of `59130178` / `774572767` / `833702945`;
  the held-out gap is computed (closing − TB line); those amounts live only in tests as fixture pins.

## Honest current state (corrected — confirm, don't assume)
The slice-4 parsing front-end (`parsing/`: file-kind, structure-agnostic region detection, the
confirm-gate, conservatism/no-silent-extract) is **built and tested but wired into NEITHER ingestion
path.** What each path actually does today:
- **GL path** (`gl/ingest.py` → `gl/regions.detect_regions`): **region = sheet v1**, header = first
  non-empty row. The weakest detection — a messy GL sheet (title block, instruction row, footer
  subtotals, side notes) gets no boundary protection and no confirm-gate.
- **TB path** (`face_tb/ingest.py` `ingest_tb`): **max-score header row** (skips a title block) —
  more robust than the GL path, but still a single whole-sheet parse, **no confirm-gate, no
  multi-region, none of the messy-fixture guards.**

So the asymmetry is real but slightly different from "TB uses the new parser, GL doesn't": **neither
does.** The GL path is on the weakest tier and is the one a messy real GL will hit first, so it goes
first. (Whether to also route `ingest_tb` through the front-end is a flagged scope question below.)

---

## Part A — route GL ingestion through the parsing front-end
Replace the `detect_regions` (region=sheet) call in `ingest_workbook` with the slice-4 front-end:
**structure-agnostic region detection → confirm-gate → extract → `_region_to_postings`.** The GL path
then gets the same protection the messy-TB fixture proved: title/instruction/blank/footer rows
excluded, an internal blank not ending the table, **a low-confidence boundary cannot silently extract**
(conservatism / R24).

### What's genuinely new here
- **GL-aware row classification in the detector.** `parsing/detect.py` classifies rows by the TB
  shape (Level / Account-Type / code). A GL data row is different — it stands on a **transactional
  identity** (gl_account + amount + a document/posting-date/reference). **Reuse the R14 disposition
  already in `gl/ingest.py`** (`blank_account_disposition`: continuation / subtotal / orphan) as the
  GL row classifier, so footer subtotals and annotation rows are excluded the same flag-don't-absorb
  way they are at the row level today — now also at the region-boundary level.
- **File-kind detection on the GL workbook** (already built) selects the GL classifier path.

### The no-regression proof (the discipline from slice 7, applied to ingestion)
Re-wiring must not move a single real number. The three real GLs **ingest byte-identically** after the
rewire: same postings, same closings, same exceptions — **Investments Σ 4,256,555,000 / Prepayments
10400001 = 833,702,945.67 / PP&E cost 929m, accum dep −221m** unmoved, the two planted malformed rows
still the −59,130,178.49 orphans. Assert old `ingest_workbook` output == new, per account.

### The new guard (the reason the slice exists)
A **deliberately messy GL fixture** (a GL sheet with a title row, an `(in SAR)` subheader, a
"Finance to update" instruction row, blank separators, **footer control totals**, and a stray
side-annotation) → the front-end finds the exact posting region, **excludes** the footer control
totals (the 1.6B-double-count shape, at the GL boundary now), and a low-confidence boundary is
**needs_review, not silently extracted.** The region=sheet v1 would have swept the footer into
postings; the new path must not.

---

## Part B — thread the FaceTB anchor through `recompute()`
Today the GL-only `recompute()` orchestrator passes **no anchor**, so every recomputed note is
magnitude-unverified / PARTIAL (correct, but it can never reach BUILT). Thread a **FaceTB** (the
position) into `recompute()` so each note gets its `LineRecon` anchor (slice-5 contract) and the R8
loop can reconcile to the TB line — closing the slice-5 recorded follow-up.

### The held-out-rows finding — a BLOCK-WITH-A-QUESTION, state it so nobody forces it green
Threading the anchor hits the held-out question head-on, and **the correct outcome is a block, not a
tie:**
- Without reinstatement, Prepayments reconciles **BUILT** (closing 833,702,945.67 == TB raw
  833,702,945.67).
- **Reinstating** the two malformed rows (R10) moves the closing to the sheet **control total
  774,572,767.18** — while the TB line stays **833,702,945.67**. So the anchored recompute must
  produce a reconciliation **gap of exactly the held-out −59,130,178.49 → BLOCKED**, surfacing the real
  finance question: ***"are these two rows part of this TB line, or do they belong elsewhere?"*** The
  control total and the TB raw genuinely disagree by exactly the held-out amount.
- **Success here is BLOCKED + the question, not a clean tie.** A reconciliation that ties after
  reinstatement would be the bug — it would mean a −59.1M disagreement got absorbed. The guard asserts
  the gap is **exactly −59,130,178.49** and the status is **BLOCKED**, with the question queued.

---

## Why both in one slice
They are the same goal: **make the GL path a first-class citizen of the TB-first architecture** — the
GL ingests through the same guarded front-end as everything else (A), and the GL-derived breakdown
reconciles to the TB line through the same one path the notes use (B). Doing them together means the GL
path is fully settled before any surface is built over it.

## Guards (summary)
1. **No-regression:** the three real GLs ingest byte-identically through the new front-end (figures
   unmoved, orphans intact).
2. **Messy GL fixture:** exact posting region found, footer control totals excluded, low-confidence →
   needs_review (no silent extract).
3. **Anchored recompute, clean case:** a note with a reconciling anchor recomputes to **BUILT**.
4. **Anchored recompute, held-out case:** after reinstatement, Prepayments is **BLOCKED with gap
   exactly −59,130,178.49** and the "do these rows belong to this line?" question queued — not tied.

## Explicitly OUT of slice 8
- **The GUI / output slice** (the finale) — present **BS + P&L as first-class statements** with notes
  as drill-downs, the three input cases, the parsing confirm-steps, the reconciled note statuses. Its
  own real slice; the engine (GL path included) must be settled first so the surface isn't revised
  underneath. (Logged scope; not pulled forward.)
- **Routing `ingest_tb` (the TB path) through the front-end** — FLAGGED for your call. The TB path's
  max-score header detection already handles the known TB messiness; routing it through the front-end
  for confirm-gate symmetry is a *separate* decision. Recommend **deferring** it (don't expand slice 8
  beyond the GL gap) unless you want the symmetry now.
- **The matcher (Bucket B)** — waits on the renumbering answer. **Independent keystone sign-off** —
  finance's own TB.

## Sequencing
1. **Slice 8** — GL path through the front-end (A) + recompute anchor (B). [this]
2. **The output/GUI slice** — BS + P&L as first-class statements with notes hanging off their lines.

The discipline this slice locks: the GL path earns the **same boundary protection and the same one
reconciliation path** as the rest of the TB-first engine — proven by a byte-identical no-regression
pass on the real GLs and an honest **BLOCK-with-a-question** where the data genuinely disagrees.
