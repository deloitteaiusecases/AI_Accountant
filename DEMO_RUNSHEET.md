# Demo run-sheet — the happy path (most capability, least risk)

> Reconciliations are presented as working; **independent sign-off is the next validation step** (noted,
> not claimed). The matcher and independent sign-off are out of scope for this demo.

## Before you start
- Launch: `streamlit run fsgen_app.py`
- Pre-generated artifacts to show if you'd rather not click-export live:
  `exports/FS_statements.xlsx` and `exports/FS_statements.pdf` (run `python scripts/demo_export.py` to refresh).

## The click path
1. **Step 1 · Data** — pick **"Bundled sample (derived TB + GLs)"** → **Load data**.
   *Say:* the app detects the input case — here **TB + GL**, so it can reconcile breakdowns to the TB lines.
2. **Step 2 · Confirm table regions (GATE)** — check the box.
   *Say:* every confirm step is a **gate** — nothing downstream runs until confirmed, because a
   mis-detected boundary silently corrupts numbers (no needs-review flags here → clean).
3. **Step 3 · Confirm account → note mapping (GATE)** — check the box.
   *Say:* unmapped accounts are **excluded, flagged — never guessed**.
4. **Step 4 · Balance sheet & P&L** — set the unit to **SAR'000** (figures are *withheld* until you do — R11).
   - **Statements are primary.** Point to the per-line **status**:
     - **Investments — BUILT (reconciled)** · 4,256,555
     - **Property, plant & equipment — BUILT (reconciled)** · 708,000 (NBV)
     - **Prepayments — PARTIAL** · 833,702.95 *(reconciles to the line, but has open items — this is the
       honesty travelling: a clean figure with an honest "not final")*
     - **Trade payables / Share capital / Revenue / Cost of sales — "GL not provided"** *(TB-only lines;
       the three-case story on one screen)*
   - Point to the **Balance keystone: BALANCES** — say it's a **separate claim**: balancing does NOT
     mean every line reconciled (and the app warns if any line is BLOCKED).
   - **Drill down** one line: expand **"Breakdown — Investments, Net"** → FVIS / FVOCI / AC with
     Domestic / International, status BUILT. Optionally expand **PP&E** → cost − accumulated depreciation
     → NBV per class.
5. **Export** — click **Download Excel** and **Download PDF**.
   *Say:* the downloads are statement-first and **carry every status + the NOT-FINAL stamp** — there is
   no clean path that drops the caveats. (Open the `.xlsx`: BS/P&L sheets + a sheet per note; the `.pdf`
   is stamped NOT FINAL on every page.)
6. **Assumptions & findings — the rigour act (present red as a STRENGTH).** In the export (the
   "Assumptions & findings" sheet / PDF page) or Step 5's open questions, show the **open items the tool
   surfaces** — none silently auto-answered. **Star exhibit: the two held-out rows (net −59,130,178.49)**
   — *"the tool found two misaligned rows, held them out rather than absorbing them, and asks whether
   they belong; reinstating them moves the closing to the control total and BLOCKS the line until a
   human decides."* Also visible: the 774.6M control total, a 45M single-posting magnitude query. *Say:*
   every figure traces to a question; **the AI never silently turns a line green** — a clean line is
   clean because it reconciled, not because a question was hidden.
7. **Close** on the caveat line under the statements: *"Derived TB reconciles by construction → proves
   breakdown↔line; **independent sign-off is the next validation step**."*

## Not hardcoded — say it plainly if asked
The path is **upload the real fixture → the engine computes → the export reflects live output.** Proof:
edit any TB/GL value and the figure moves *and* the status responds (nudging the TB Investments line
flips it **BUILT → BLOCKED** because the GL no longer reconciles). **No demo-only shortcut, no pre-baked
result** — the figures come out because the engine produces them.

## Second act (no-mappings) — DEFERRED, do not attempt live
The **AI-mapping loop is NOT wired into the app** (proven in the engine, not GUI-wired). So the
**no-mappings upload path and the "mappings applied" front page are the scoped NEXT build** (they ship
together with wiring the loop). For this demo, **use only `Derived_TB_From_GLs_XYZ.xlsx` (mappings
provided by preparer)** — do not upload the no-mappings TB.

## What to AVOID clicking (rough edges / risk)
- **Don't skip setting the unit** — figures read **WITHHELD** until you pick SAR'000 (it's the R11
  honesty gate, but set it immediately for a smooth demo; export is disabled until then).
- **Step 5 · Open questions** works (answering **recomputes** the FS, R8) — show it once if you like,
  but **don't click "reinstate" on a held-out row** unless you intend to demonstrate a **BLOCK**: it
  moves Prepayments to the control total (774.6M), which disagrees with the TB line by the held-out
  amount and turns the line **BLOCKED with its question** (a powerful honesty moment, but only if you
  mean to show it).
- **Use the bundled sample, not an arbitrary upload** — the bundled TB+GLs are the verified path.
- The confirm gates are **checkboxes** (real gates — they block). The editable-boundary contract is
  built and tested in the engine, but the live UI surfaces confirmation as a gate, not a drag-the-
  boundary widget — don't promise live boundary-dragging.

## The honest framing (if asked)
- Investments & PP&E reconcile **BUILT** to their TB lines; Prepayments reconciles but is **PARTIAL**
  (real open items). Figures: Investments **4,256,555,000** · Prepayments **833,702,945.67** · PP&E NBV
  **708,000,000**.
- These prove **breakdown ↔ TB line** on a derived TB; **independent sign-off (finance's own TB) is the
  next step** — and the screen says so.
