# Slice 5 — the note-contract inversion (breakdown reconciles to the TB line)

> The piece that connects what Bucket C proved (a breakdown can reconcile to a TB line) to the actual
> note modules, which still own their own total the old way. Engine + CLI + tests, **no UI.**
> ~~No code until this plan is reviewed~~ — **✅ BUILT (2026-06-10)** to this plan after review, with
> the two review additions folded in: the **two-magnitude lie test** and the **real PARTIAL→BUILT
> recompile transition**. All 27 suites green.

## Result against the real fixtures (what to look at)
- `tests/test_note_inversion.py` — 6 guards: Investments anchored → **BUILT** (gap 0.00); the
  internal-tie-that-lies → **BLOCKED at two magnitudes** (a clean planted **−300 TB'000 / 300,000 SAR**
  small gap AND a 1bn large gap, both above `tol=0.005`, both BLOCK while the breakdown ties
  internally); recon-to-raw **no false gap** (raw≠Final, bridge shown); **partial coverage** → PARTIAL
  to the covered subtotal; **no-anchor → magnitude-unverified, never BUILT**; and the **PARTIAL→BUILT**
  recompile transition (unit unconfirmed → answer → BUILT).
- `python scripts/note_inversion_check.py` — shows both notes: Investments BUILT, the small lie
  BLOCKED with the Δ named, and the status transition.
- **The flip:** `tie_ok` now = "reconciles to the TB line" (reusing `LineRecon`, one path); the old
  internal tie is `internal_tie_ok` / `internal_structural_ties_ok`; a reconciliation BLOCK overrides
  any internal pass. `magnitude_verified` = `anchor.reconciles`. The float `magnitude_anchor` is gone.
- **Caveat held:** reconciling to a derived TB proves breakdown↔line, **not** that the line is right —
  independent sign-off stays parked on finance's own TB.

## The defining property (drives every decision)
**The TB line owns the number; the note's breakdown reconciles UP to it.** Today a note is its own
authority (`account_total_sar` = the GL closing; `tie_ok` = "Σ my lines == my own total"). That is an
*internal* tie — and an internal tie can be perfectly consistent while disagreeing with the position
(the Prepayments double-count held a flawless internal tie). The inversion makes the note assert
against the **TB line**, not itself: `tie_ok` becomes **"the breakdown reconciles to its anchoring TB
line's raw amount."** Structure survives (gross/ECL/net, DOM/INT, the movement schedule); the
**contract and its tests change.**

This was designed-for since slice 1 — `raw_amount` kept separate from `final_amount`,
`note_level_subtotals()` exposed as the anchor, and the R16 `magnitude_anchor` hook already on
`InvestmentsNote`. The hooks exist; slice 5 wires the TB line into them.

## One reconciliation path, not two
The note does **not** grow a second comparison mechanism. It reuses the Bucket C keystone verbatim:
`LineRecon` (`face_tb/routing.py`) — `reconciles`, `status()`, `gap`, `tb_recon_covered`,
`adjustment_bridge`, `coverage_pct`. The caller routes GL → TB once (`route_gl_to_tb`); the relevant
`LineRecon` for the note's caption becomes the note's **anchor**. The note asks one question of it:
*does my breakdown reconcile to my TB line?* — never re-implements the check.

---

## The inverted contract, stated precisely

### 1. `tie_ok` flips to reconciliation
- **Before:** `InvestmentsNote.tie_ok = sections_sum_to_total AND movement.ties AND (per section
  gross−ECL=net AND DOM+INT=net)`. All internal.
- **After:** `tie_ok = reconciles_to_tb AND <the internal structural ties>`, where
  `reconciles_to_tb = anchor.reconciles` (the `LineRecon` for this note's TB line). The internal ties
  stay — as **structural** checks (the schedule still has to add up) — but they are **no longer the
  authority.** The authority is the reconciliation to the TB line.
- The note keeps `sections_sum_to_total` etc. as named *internal-consistency* properties, demoted
  from "the tie" to "a structural precondition." `tie_ok` without an anchor is **not** True-by-default
  — see status (it becomes magnitude-unverified, never silently BUILT).

### 2. Reconcile to the RAW TB amount, not Final (R23 carried through)
Because the anchor is a `LineRecon`, recon-to-raw is automatic: `tb_recon_covered` already uses
`recon_amount` (raw when a breakdown exists, else Final), and `adjustment_bridge` is the visible
`Final − raw` itemization — **never a tolerance.** A note over an *adjusted* TB line (raw ≠ Final)
reconciles to **raw** and shows the bridge; it must **not** display a false gap. (Asserted on a
raw≠Final fixture, mirroring the slice-3 recon-to-raw guard.)

### 3. The internal-tie-that-lies guard (the whole point of the inversion) — explicit
A breakdown whose **own subtotal ties** but **differs from the TB line** is **BLOCKED, not BUILT.**
This is the lesson paid for twice. Stated as a direct assertion: a note with `sections_sum_to_total
== True` (internally consistent) but `anchor.gap != 0` comes out **BLOCKED**, and the reason names it
— *"internally consistent but does not reconcile to the TB line (Δ = …)."* The reconciliation BLOCK
**overrides** an internal pass; internal consistency can never upgrade a failed reconciliation.

### 4. Status composes correctly
The note's `status()` now depends on **both** its own build **and** the reconciliation — and on GL
coverage of the line, reusing `LineRecon.status()`:
- `anchor.status() == "BLOCKED"` (gap) → note **BLOCKED** (the lie guard; overrides everything).
- `anchor.status() == "PARTIAL"` (GL covers some leaves) → note **PARTIAL**, reconciled to the
  **covered subtotal** (not the whole line) — carrying A3/partial-coverage through.
- `anchor.status() == "BUILT"` (reconciles, full coverage) **AND** internal structural ties hold
  **AND** presentation confirmed (R11) **AND** nothing else provisional → note **BUILT.**
- **No anchor at all** (GL-only, Track 1) → note **PARTIAL**, labelled **magnitude-unverified** (R16)
  — never BUILT. The inversion does not make a homeless breakdown pass.
- Wire through the **existing gap report + recompile loop (R8):** answering a clarification re-runs
  and the note's status recomputes deterministically — same loop, no parallel path.

### 5. What `magnitude_verified` means now (and the caveat that stays)
`magnitude_verified` flips from "an external figure was supplied and matched" to **"the breakdown
reconciles to its anchoring TB line."** The TB line is the anchor. **Caveat preserved:** reconciling
to a *derived* TB (one built from the same GLs) proves the breakdown matches the position, **not** that
the position is independently right — that is the **independent keystone sign-off**, still parked on
finance's own (non-derived) TB. Slice 5 verifies *breakdown ↔ line*; it does **not** close that.

---

## Mechanical shape (minimal, additive — for review)
- The caller routes once: `result = route_gl_to_tb(facetb, gl_closings_in_tb_units)`. Each note's
  **anchor** is the `LineRecon` whose `caption` is that note's TB mapping (e.g. "Investments",
  "Prepayments").
- `build_investments_note(...)` / `build_prepayments_note(...)` gain an **`anchor: LineRecon | None`**
  parameter (replacing the ad-hoc `magnitude_anchor: float`). The note stores it; `reconciles_to_tb`,
  the composed `status()`, and `tie_ok` read from it.
- `RollForwardTB` stays the **movement/breakdown** source (opening → movements → closing, DOM/INT,
  reference-coded schedule). It is no longer the *authority on the total* — it is the breakdown that
  reconciles to the FaceTB line. (Recast, not discard — exactly the redesign's intent.)
- The two internal-tie properties remain but are renamed in role (docstring), not deleted: they are
  the structural preconditions, surfaced in `provisional_reasons()` if they fail.

---

## Guards / tests — on the REAL fixtures (the inversion proven on real magnitudes)
Use the corrected `TB/Derived_TB_From_GLs_XYZ.xlsx` + the two GLs (same set Bucket C signed off):
1. **Investments reconciles → BUILT.** The Investments note, anchored to its TB line, reconciles
   (`anchor.gap == 0` at tight `tol=0.005`) and ties internally → `status() == "BUILT"`,
   `reconciles_to_tb == True`. The inversion working on real numbers.
2. **The lie comes out BLOCKED — at TWO magnitudes.** A deliberately-mismatched variant where the
   breakdown ties internally but ≠ the TB line (perturb one TB-line raw, leaving the GL breakdown
   internally consistent) → `sections_sum_to_total == True` **and** `status() == "BLOCKED"`, reason
   naming the Δ. Test it at **two magnitudes**, because the lies this build actually hit were not
   always obviously material (the double-count was a 2× factor; the continuation-row gap was 3.27M on
   an 833M line — small relative to the line):
   - a **large** perturbation (the obvious lie), AND
   - a **small** one — a few hundred thousand on an ~800M line, **well above `tol=0.005`** but small
     relative to the line — and assert it **still BLOCKs** and is **not absorbed by any downstream
     tolerance.** The false-gap (recon-to-raw, #3) and this small-real-gap are mirror images: a test
     on each side proves `tol=0.005` is tight enough that **nothing quietly swallows a small real
     gap**, and loose enough that a true raw-vs-Final bridge is **not** a false gap.
3. **Recon-to-raw, no false gap.** A note over a raw≠Final TB line reconciles to raw, the bridge is
   shown, gap == 0 — a manufactured "Final" gap would (wrongly) BLOCK it.
4. **PARTIAL coverage.** GL covers some of the line's leaves → note PARTIAL, reconciled to the covered
   subtotal, uncovered leaves listed (not silently dropped).
5. **Recompile — a real status TRANSITION, not just a re-run.** Assert that answering a question
   **flips the note across a status boundary**: a note **BLOCKED** (or PARTIAL) on an unconfirmed unit
   / unanswered window → the human answers → it recomputes to **BUILT**. A recompile that re-runs but
   never crosses BLOCKED/PARTIAL/BUILT doesn't prove the inverted contract participates in the R8
   loop; the boundary crossing does. (Idempotent, reusing the existing loop — no parallel path.)

Skip cleanly if the real fixtures are absent (same pattern as `test_bucket_c.py`); a synthetic
anchored note + a synthetic lie cover the contract when they're not.

---

## Recorded follow-ups (named, not silently assumed)
- **Thread the FaceTB anchor through the `recompute()` ORCHESTRATOR.** The note *builder* takes the
  anchor now (the deterministic recompute unit), and the PARTIAL→BUILT transition is proven there. The
  GL-only `recompute()` orchestrator has no FaceTB, so notes recomputed through it are correctly
  **magnitude-unverified (PARTIAL)** — never silently BUILT. Wiring a FaceTB into the orchestrator is
  the follow-up; it will also surface a real finding (reinstating held-out rows moves the Prepayments
  closing to the *control total* 774.6M, which then must reconcile against the TB raw 833.7M — a
  genuine reconciliation question, exactly what the inversion is for).
- The float `magnitude_anchor` (a resolution-supplied external figure) is **superseded** by the
  LineRecon anchor and removed from the note API.

## Explicitly OUT of slice 5
- **The GUI** — still deferred. Wire it after the contract is locked *and* the first non-bank note
  exists, when there is a complete reconciled flow worth showing.
- **The matcher (Bucket B)** — waits on the renumbering-vs-different-account-set answer.
- **The first non-bank note** — its own slice, *after* this (the generality checkpoint).
Slice 5 is the **contract flip on the existing two notes** (Investments 4b, Prepayments 4a), engine +
CLI + tests, no UI.

## Sequencing (after slice 5, per direction)
1. **Slice 5** — the note-contract inversion (this).
2. **First non-bank note** — the generality checkpoint (does the TB-anchored contract hold off-bank?).
3. **Close the GL-path region-detection gap** — re-wire GL `ingest_workbook` onto confirmed regions
   (the slice-4 recorded follow-up), so GL ingestion is structure-agnostic too.
4. **The GUI** — once there's a complete reconciled flow (parse → face → anchored, reconciled note).

Every silent-failure surface keeps its assertion (R21). The new surface here is the **internal tie
that lies** — a note that adds up to itself but not to the position — and the guard is: reconciliation
to the TB line is the authority, and a reconciliation BLOCK can never be upgraded by internal
consistency.
