# Master-FS export (phase 1) — detailed PDF / Excel of the master-FS output

> The detailed export of the phase-one master-FS engine. **NOT just reusing the old `FS_statements`
> exporter as-is** — that was built for the old derived-TB / three-notes flow. **Reuse its honesty
> machinery; point it at the NEW master-FS content.** Engine + CLI + tests, **no UI.**
> ~~No code until reviewed~~ — **✅ BUILT (2026-06-11)** to this plan with the four refinements
> (illustrative round numbers, no banner, small conditional NOT-FINAL footnote, comparative-column
> honesty) and the live-mapping framing. **LIVE path confirmed** (gpt-5.1-2025-11-13 responded);
> mapped live once, confirmed-and-stored, export replays the store. All 22 suites green.

## Result (what to look at)
- `scripts/master_fs_live_map.py` — the **LIVE** call: 21 representative-TB lines → master concepts via
  `gpt-5.1-2025-11-13` (labels-only, detailed `_MASTER_FS_SYSTEM`), reviewed → 19 confirmed, **1
  AI-assumed** (Salaries → Other G&A, medium), **1 declined→unmapped** (Sundry suspense) → stored to
  `exports/master_fs_live.json`. `scripts/master_fs_export.py` **replays the store** (no live call) →
  `exports/Master_FS.xlsx` (BS/IS/OCI + Mappings-applied + Findings) and `exports/Master_FS.pdf`
  (statements, provenance page, findings page, small conditional NOT-FINAL footnote, "notes are a later
  phase" line).
- Honesty in the document: AI-assumed renders amber "AI assumption" in **both** the statement line and
  the provenance view; the one-period-only Goodwill line shows **current 600,000 · prior —**
  (present-where-present); illustrative round numbers (no real figures, no banner). Guarded by
  `test_master_fs.test_export_model_is_honest` (deterministic).

## The defining property (drives every decision)
**The export is a faithful mirror of the master-FS engine output — it never claims more certainty than
the engine assigned.** A line resting on an AI-assumed mapping renders as AI-assumed (not settled);
populated-vs-unpopulated is visible; what isn't built yet (note-by-note breakdowns) is shown as a later
phase, not faked. Same discipline as the GUI guard, applied to the PDF/Excel.

## Reuse vs new (explicit)
- **REUSE — the honesty machinery** (from `reporting/statement_export.py` + `reporting/`): the
  **NOT-FINAL stamp** on every PDF page while anything's provisional; the **provenance rendering**
  (preparer / AI-proposed-confirmed / AI-assumed, with AI labelled UNCONFIRMED in red, never shown
  settled); the **assumptions/open-findings page** pattern (`build_findings`-shaped); per-line status
  colours; the "status/caveat as prominent as the figures" rule; the bytes-helpers for download.
- **NEW — the master-FS content** (consumes `master_fs.render` + the stores, NOT a `StatementView`):
  the **three face statements from the master** (BS / P&L / OCI), **populated lines only, master order,
  client's own labels, comparative columns** (current + prior from the two same-client TBs); the
  **mappings-applied / provenance view** (each account → its master concept + provenance); and the
  master-FS **findings** (unmapped / flagged / unsure items). A new `export_master_fs_excel/pdf(...)`
  sibling — same honesty helpers, new shape.

## What the export contains
### 1. The three face statements (the headline)
- `render_comparative(...)` per statement → BS, P&L, OCI, each: sections → **only populated lines** in
  **master order**, the **client's own label** per line, and **two amount columns (current · prior)**
  from the two same-client TBs. Section subtotals (Total Assets / Liabilities / Equity, etc.).
- A line whose mapping provenance is **AI-assumed** carries an **"AI assumption" tag** on the line
  (amber) — its figure is shown but the line is **not** presented as settled. Preparer / AI-confirmed
  lines render normally. (The status vocabulary is the master-FS analog of `LINE_*`.)

### 2. The mappings-applied / provenance view (the auditable classification surface)
- A standalone sheet (Excel) / page (PDF), **always present**: every populated account → its **master
  concept** (canonical) → **provenance** (`preparer-provided` / `AI-proposed (confidence X) · confirmed
  by human` / `AI-assumed (unconfirmed)`). **An AI-assumed row renders as AI-assumed (red/amber),
  never as human-confirmed.** So a reader can verify the account→line classification and **who decided
  it**, without trusting the numbers — the honest core, carried from slice-9/10.

### 3. The assumptions / open-findings page
- The unmapped / flagged / unsure items surfaced in full: the **unmatched preparer captions** (e.g.
  "Customer deposits"), any **unsure AI mappings left unmapped**, each with what it is and why it's
  open — **none silently auto-answered.** Same transparency surface as the FS_statements findings page,
  fed from the master-FS mapping store (the flagged `MappingRecord`s) instead of the clarification queue.

## What is explicitly NOT in it yet — and the export says so honestly
- **Note-by-note breakdowns are PARKED** (the note modules plug into master lines in a later phase).
  So where a master line would later drill down to a note, the phase-one export shows the **face line
  only.** **Do NOT render empty/placeholder notes as if they exist** — no "Breakdown — …" page with
  nothing in it. Instead, a single honest statement on the document: *"Note-by-note breakdowns are a
  later phase; this export shows the face statements only."* Faces shown; drill-downs left for when the
  modules plug in.

## The honesty rule carried into the document
- An **AI-assumed** line/mapping renders with its AI-assumed provenance, never settled — in BOTH the
  statement line AND the provenance view.
- **Populated-vs-unpopulated** is visible (only populated lines render; the findings page shows what's
  unmapped).
- **NOT-FINAL is conditional on REAL state, rendered QUIETLY (refinement):** it appears only when the
  output is genuinely provisional (any AI-assumed line, any unmapped/flagged item, any unconfirmed
  mapping) and is absent when nothing is provisional — never always-on, never always-off. **Only the
  rendering changes: a small plain footnote** ("Draft — not final: contains provisional/unconfirmed
  lines"), **not a large red banner.** The engine logic is untouched; the provenance view and per-line
  AI-assumed marking stay exactly as accurate — this is only the page-level stamp's size/colour.
- **NO "illustrative / not-real-data" banner (refinement):** the audience knows the figures are
  representative; the **clearly-illustrative round numbers (below) are what keep it honest, not a
  label.** No banner, no footnote version.

## Who does what (live-mapping framing)
- **Claude (this environment) generates ONLY the representative TB fixture** — the raw two-period
  numbers + captions. **It does NOT hand-map the TB into the master.**
- **The mapping is the GPT-5.1 proposer's job — a LIVE call**, pinned `gpt-5.1-2025-11-13`, labels-only.
  **Live path confirmed** (key + egress + model verified; reported, not silently assumed). A detailed
  system prompt is used (shown to the reviewer) — labels/captions only, never amounts.
- **Run-live-once-then-replay-confirmed:** the live call maps the TB → the proposals are reviewed,
  confirmed, and **stored** (propose-confirm-store) → **the export replays the STORED confirmed
  mappings.** So the output is "mapped live by real GPT-5.1" (validated) AND stable for presentation
  (no live re-call mid-demo, no timeout exposure in the room). The live proposals + confidences (and
  any 'unsure') are shown to the reviewer.

## The fixture + the artifacts to produce
- **The master/seed is the REAL approved one** (GATE 0 already proved it faithful).
- **The client TB:** we have **no real Bank AlJazira / SAAB TB**. Claude generates a **representative
  bank TB** — bank-captioned, two periods (current + prior) — with **obviously illustrative round-ish
  numbers** that populate the structure meaningfully but **cannot be mistaken for the bank's actual
  filing.** **It must NOT use AlJazira's real published figures** (real data wearing a representative
  label is worse than illustrative). It deliberately includes: a line **populated in one period but not
  the other** (added/dropped — real for banks), and an account whose mapping the human accepts as an
  **AI-assumed** (to exercise that rendering).
- Produce an actual **`exports/Master_FS.xlsx`** (BS / P&L / OCI sheets + mappings-applied sheet +
  findings sheet) and **`exports/Master_FS.pdf`** (statements, provenance page, findings page, the small
  NOT-FINAL footnote, the "notes are a later phase" line) via `scripts/master_fs_export.py`, on the real
  seed + the illustrative representative TB (mapped from the stored live result), and show them.

## Guards (tested)
1. **Faithful statuses:** an AI-assumed mapping renders as AI-assumed in BOTH the statement line and
   the provenance view — never settled, never human-confirmed; provenance label correct per row.
2. **Populated-only + comparative-column honesty (tightening):** the export renders exactly the
   populated master lines, in master order, with the client's labels and both period columns; unmapped
   accounts appear in findings, not in a line. **A line populated in ONE period but not the other shows
   its figure where it exists and a blank/dash where it doesn't — no carry-across, no dropped line, no
   fabricated zero.** Present-where-present, absent-where-absent.
3. **No placeholder notes:** the document contains the "notes are a later phase" statement and **no**
   empty note/drill-down page.
4. **Findings present:** the unmatched/flagged items (e.g. "Customer deposits") appear on the findings
   page; none silently dropped.
5. **NOT-FINAL + provenance discipline:** NOT-FINAL stamped while provisional; the mappings-applied
   view is always present; the model/labels-only discipline is untouched (no amount in any payload —
   the export sends nothing to a model anyway).

## Explicitly OUT
- **Note modules / note drill-downs** (parked — shown as a later phase). **Slice 10 GUI** (parked —
  this is the export, engine+CLI). **Matcher**, **independent sign-off** (external/parked).
- **No new engine logic** — the export only *surfaces* the master-FS engine output; a wrong status is
  an engine bug, never smoothed in the document.

## Sequencing
Reuse the honesty helpers → new `export_master_fs_excel/pdf` over the master-FS render + provenance +
findings → `scripts/master_fs_export.py` on the real seed + representative TB → produce + show the
`.xlsx` and `.pdf`. The discipline locked: **the master-FS document mirrors the engine's honesty —
populated lines, provenance on every classification, AI guesses never settled, and what isn't built
yet (the notes) marked as a later phase, not faked.**
