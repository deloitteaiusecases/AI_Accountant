# Slice 9 — the output layer: BS + P&L as first-class statements (the presentation finale)

> **A different kind of slice than 3–8.** Those had a number to reconcile against; this one does not.
> Its job is to faithfully **surface what the engine already computed and statused**, and its risk is
> **misrepresentation** — showing a PARTIAL as BUILT, hiding a BLOCKED reconciliation behind a clean
> statement, presenting a magnitude-unverified figure without its caveat. The honesty discipline that
> survived eight slices (flag-don't-absorb; the derived-TB and independent-sign-off caveats) has to
> carry into the presentation layer — that's what the accountant reads.
> ~~No code until reviewed~~ — **✅ BUILT (2026-06-10)** to this plan with the three tightenings folded
> in (composition-and-placement guard, edited-boundary-still-gated, re-verified R11/R8). All 32 suites
> green. **This completes the TB-first build** — only the two external items (matcher, independent
> sign-off) remain parked.

## Result (what to look at)
- **The honest core is a PURE model** (`reporting/statement_view.py` `build_statement_view`) the app
  renders verbatim, so the load-bearing guard is deterministic, not Streamlit-flaky:
  `tests/test_statement_view.py` (8 guards) — per-line status mirrors the engine; **(a)** BLOCKED
  shows AT the face line with its question; **(b)** keystone BALANCES *and* a line is BLOCKED, shown as
  separate claims (balancing ≠ all reconciled); **(c)** reconciled-BUILT visibly distinct from
  face-only; **R11** figures withheld until unit set; **R8** the view moves with the recomputed figure;
  **edited-boundary-still-gated** (`apply_boundary_edit` → unconfirmed, still needs override).
- **The app** (`fsgen_app.py`, rebuilt around the TB-first flow): TB upload → `assemble_face` → **BS +
  P&L first-class** with each line drilling down to its note; **three-case** detection/label
  (TB-only / TB+GL / GL-only); the keystone shown as its own claim with a "balancing ≠ all reconciled"
  warning when any line is BLOCKED; figures withheld until the unit is set; questions recompute (R8,
  `facetb` threaded into `recompute()`). `tests/test_fsgen_app.py` (AppTest) confirms the app surfaces
  it: gates block, statements render, withheld figures, the three-case render, keystone-not-masking.
- `renderable()` extended for the PP&E note (two-layer cost/dep → NBV) so its drill-down renders.

## The defining property (drives every decision)
**THE SCREEN NEVER CLAIMS MORE CERTAINTY THAN THE ENGINE ASSIGNED.** Every note status (BUILT /
PARTIAL / BLOCKED / magnitude-unverified) and every caveat (derived-TB-reconciles-by-construction,
independent-sign-off-pending) is visible and accurate in the presentation, never smoothed. A BLOCKED
note with a queued question must **look blocked, with its question shown.** A GUI that makes a BLOCKED
note look done would undo the reconciliation engine's whole point. This is the load-bearing guard, and
it is **testable** (below) — the GUI's analog of the engine guards.

## Where it starts from (honest — budget it as the large slice it is)
The current `fsgen_app.py` is the **Phase-5, GL→notes, pre-redesign** app: it ships **notes alone**,
with checkbox confirm-gates, status chips, and magnitude-unverified caveats. It predates the TB-first
redesign — **no TB upload, no BS/P&L face statements, no three-input-cases, no anchored reconciliation
status.** So this is a **real rebuild around the TB-first flow, not a re-wire.**

- **Salvage (keep, it already respects honesty):** the status-chip vocabulary (`BUILT`/`PARTIAL`/
  `BLOCKED` green/amber/red, "NOT FINAL"), the `renderable(note)` model, **figures withheld until the
  unit is confirmed (R11)**, the **`recompute()`-driven recomputation (R8)** (an answer never patches
  a number), and the gap-report / clarification-queue / exports tabs.
- **Genuinely new (the rebuild):** TB upload → `FaceStatements`; **BS + P&L presented as first-class
  statements with notes as per-line drill-downs**; the **three-case** rendering; the parsing
  confirm-steps as **visible, editable boundary gates** (slice-4 contract) replacing rubber-stamp
  checkboxes; and the **anchored reconciliation status** surfaced (slice-5/-8: the `LineRecon` gap, the
  held-out BLOCK-with-a-question), by threading the FaceTB into `recompute()` (slice-8 `facetb=`).

## 1. BS + P&L as first-class statements (Abhishek's headline deliverable)
The information architecture **inverts**: the **statements are the primary view**, notes are their
drill-downs — not notes shipped alone.
- Render `FaceStatements.balance_sheet` and `.income_statement` as two statements (sections →
  face lines → section subtotals; the **balance keystone** Assets = L+E+(I−Exp) shown with its
  BALANCES / DOES-NOT-BALANCE / CANNOT-RUN verdict).
- **Each face line is expandable to its note** — the reconciled breakdown for that TB line (Investments,
  Prepayments, PP&E, …), carrying the note's own status. A line with no note module yet shows the
  face figure and "no breakdown module."
- TB-side honesty already in the engine, surfaced: `unmapped` leaves (excluded, flagged, never
  guessed), `unknown_section`, `near_duplicate_mappings`, `adjustment_mismatches` — shown, not hidden.

## 2. The three input cases — surfaced honestly (not a mode switch)
- **TB-only** → the **full FS** (BS + P&L from the FaceTB), notes at **face level only**, **no
  breakdowns** ("breakdown not provided — upload the GL to reconcile this line").
- **TB+GL** → **reconciled breakdowns where GL was provided** (the note drill-down shows the breakdown
  + its BUILT/PARTIAL/BLOCKED reconciliation to the line); **face-only where not** ("GL not provided"
  on that line). Per-line, never all-or-nothing.
- **GL-only** → **note only, magnitude-unverified** (no TB line to anchor to → the slice-5
  magnitude-unverified caveat, shown; no claim of a verified face figure).
The app **detects** which case each line is in and shows the maximum that input supports, labelling the
rest — the detect-and-maximize contract, made visible.

## 3. Parsing confirm-steps as REAL human-in-the-loop gates
This is where a user's messy upload meets the engine, so the slice-4 confirm contract is wired in
**properly**, not as a rubber-stamp checkbox:
- **file-kind** (GL / TB / unsure-asks), **region boundary**, **header row**, **field mapping** — each
  shown as the engine detected it (`DetectedRegion.describe()`: "rows 7–432 = table, row 6 = headers,
  these columns = …; excluded …; confidence …"), and **editable** (the human can move `data_start` /
  `data_end` / `header_row` / remap a column) before confirming.
- **Nothing downstream runs until confirmed** (R22 + R24): a **needs_review** boundary cannot be
  confirmed without an explicit override; the gate **stops** the pipeline (the existing `st.stop()`
  pattern, now over a real editable boundary instead of a checkbox).
- **Edited-boundary-still-gated (tightening).** Editing a low-confidence boundary must **not silently
  clear `needs_review`** — a user-edited boundary is still subject to confirmation, and if it is still
  low-confidence it still requires the explicit override. **Editing changes WHAT the boundary is, not
  the certainty that it's right.** (Re-detect/re-score the edited boundary; the gate re-applies.)

## 4. The load-bearing guard — tested, not asserted
Drive the app **headlessly** (Streamlit `AppTest`, as `test_fsgen_app.py` already does) and assert the
**rendered surface matches the engine's verdict exactly**:
- a **BUILT** note renders BUILT/green; a **PARTIAL** renders PARTIAL/amber with "NOT FINAL"; a
  **BLOCKED** note (e.g. the held-out reinstatement) renders **BLOCKED/red with its queued question
  shown** — never green, never without the question;
- a **magnitude-unverified** note shows its caveat (red), never a bare figure;
- figures are **WITHHELD** until the unit is confirmed (R11);
- the **derived-TB caveat** ("reconciles by construction → breakdown↔line, not independent sign-off")
  and **independent-sign-off-pending** are visible where they apply;
- the negative: **no path renders a not-BUILT note as done.** A test feeds each status and asserts the
  screen's class/text — the presentation can never smooth a status.

### Composition-and-placement guard (tightening — the important one)
Per-status class mapping is necessary but NOT sufficient: misrepresentation also hides in **layout and
composition**, where each status is individually correct but the *arrangement* misleads. The AppTest
guard must additionally assert the three places it hides:
- **(a) status visible at the face line, not only in the drill-down.** A BLOCKED note's BLOCKED status
  shows **on the primary statement line**, not only inside its expanded breakdown — a user who never
  drills down must still see the line is not certain.
- **(b) the keystone does not visually mask a BLOCKED note beneath it.** A balancing keystone
  ("BALANCES ✓") must **not imply "every line reconciled"** — a statement can foot/balance while a line
  beneath it is BLOCKED. The balance verdict and the per-line reconciliation status are **separate
  claims**, shown separately; "BALANCES" never reads as "all lines reconciled."
- **(c) reconciled-BUILT vs face-only are visibly distinct.** A line whose breakdown reconciled (BUILT)
  is visibly different from a face-only "GL not provided" line — the second is **not** dressed to look
  as settled as the first.

**Correctness test:** *a user on the primary statement view cannot be misled about a line's certainty
without drilling down.* The AppTest asserts (a)/(b)/(c) on a fixture that deliberately combines a
balancing keystone with a BLOCKED line and a face-only line.

### Re-verify the salvaged guards in the NEW flow (tightening)
R11 (figures withheld until the unit is confirmed) and R8 (recompute-driven; an answer never patches a
number) are **re-run as guards in the BS/P&L-first context** — not inherited from the notes-alone
Phase-5 app, where the withheld/recomputed figure was a **note total**, not a **face line on a
statement**. Assert: a BS/P&L face figure is WITHHELD until the unit is confirmed, and answering a
question **recomputes the statement** (the face line moves because the recomputation moved it), never a
written-over number.

## Explicitly OUT of slice 9
- **The matcher (Bucket B)** and **independent keystone sign-off** — external/parked, unchanged.
- **The legacy `app.py` / `engine.py` / `ai_accountant/ui.py`** (the old Note-5 cascade UI) — not
  revived; this rebuilds `fsgen_app.py` around the TB-first flow.
- **New reconciliation logic** — none. The GUI only *surfaces* engine output; if a status is wrong,
  that's an engine bug fixed in the engine, never smoothed in the view.

## Sequencing
This is the **finale** of the TB-first build: parse (guarded front-end) → face (BS + P&L) → anchored,
reconciled notes → an honest presentation. After it, the parked externals (matcher, independent
sign-off) remain the only open threads, each waiting on an answer outside the code.

The discipline this slice locks: **the presentation is a faithful mirror of the engine's honesty —
every status and caveat carried through, nothing claimed beyond what was computed and reconciled.**
