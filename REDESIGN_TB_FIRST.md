# REDESIGN — TB-first spine, GL as reconciling breakdown layer

> **Status:** Major input-model revision, informed by accounting-team review (Abhishek, accounting). Does **not** discard Track 1 — it **recasts** the GL→notes engine we built as the *breakdown layer* and adds a Trial-Balance spine in front of it.
> **Read alongside** the existing DEVELOPMENT_PLAN. Where they conflict on input flow, this document wins; where this is silent, the existing plan's principles (deterministic/AI boundary, flag-don't-absorb, prominence, the clarification loop, the R-series decisions) all still hold unchanged.
> **Nothing is coded from this doc until green-lit.** This is the spec for the reshape.

---

## 1. The core inversion

We built **bottom-up**: GL postings → trial balance → hierarchy → notes. The real accounting workflow is **top-down**:

**Trial Balance → mapping → face statements (Balance Sheet + P&L) + face-level notes → then, per note, GL → breakdown that must reconcile back to the TB line.**

The TB is the **canonical, primary input**. The GL is a **secondary, per-note drill-down** used only to explode a specific line into its sub-detail. The pieces we built mostly survive — hierarchy, mapping table, note modules, reconciliation discipline, gap report, clarification loop — but the **spine becomes the TB**, and the **GL→notes work becomes the breakdown layer hanging off a TB line.**

---

## 2. What the Trial Balance actually is (from the real template)

The TB arrives **already structured as the hierarchy**, not as a flat list. Confirmed from `Trial_Balance.xlsx` / `TB_With_Mappings.xlsx`:

- **Levels L0–L4** (note: their numbering, offset from our L1–L4 — reconcile the naming):
  - **L0** = statement section: Asset / Liability / Equity / Income / Expense (7 rows)
  - **L1** = face grouping (e.g. Non-Current Assets), with a natural-account **range** `11000000 – 11999999`
  - **L2** = sub-caption (e.g. PP&E at cost), range `11010000 – 11019999`
  - **L3** = note-level (e.g. PP&E), range `11010100 – 11010199`
  - **L4** = the actual leaf GL accounts (8-digit codes), carrying amounts
- **Account Type**: `P` = parent/scaffold row (carries a range, no amount); `C` = child/leaf (carries the amount).
- **Level placement is deterministic from the account code's range** — this is the routing rule (see §5), and it's the same mechanism as R2 (classify from account-code structure), except the ranges are explicit in the file.
- **Amount columns**: `Amount (as per TB)` → `Amount (Other adjustment)` → `Total (Other adjustment)` → **`Final amount`**. The sheet instructs: *"Finance team to update Column F and Column G only."* So **Final = TB amount + adjustments**, finance edits only the raw + adjustment columns, the rest computes.
- **The accountant's mapping work = one column: "Actual mapping"** — assigns each leaf to one of ~38 FS line items (Property/plant/equipment, Cost of sales, Revenue, Prepaid expenses, Trade payables, …). **This column is our Phase 3 mapping table** (account → face_caption/note_ref). Built top-down here instead of bottom-up.
- **Data cleanliness is already messy:** one natural-account cell has a stray leading tab (`\t52020201`); "Actual mapping" can carry a sub-designation more specific than a plain caption ("Other income – Government grant for Right-of-use"). Ingestion must tolerate this.

> The sample TB is a **near-empty skeleton** — 268 leaves, only **8 non-zero** (Land 1,000; Motor Vehicles 22,000; Procurement cost −120; Donations −20; Imported Wheat 500; Imported Grains 400; Bank Deposits 10; Government Grants 3,300). Treat it as a **structure/mapping fixture**, not a data test. A populated TB is needed to exercise note magnitudes.

---

## 3. Face statements: Balance Sheet AND P&L, both from the TB

The TB's L0 sections split into the two primary statements:

- **Balance Sheet (SoFP)** ← L0 = **Asset / Liability / Equity** (a position).
- **P&L (income statement)** ← L0 = **Income / Expense** (performance over the period; signs are P&L signs — revenue positive, expenses negative).

Both fall out of the **same** mapping by grouping L0 differently. "Produce the face" means **both** statements. Notes attach to **both** balance-sheet lines (Investments, PP&E, Prepayments) **and** P&L lines (Revenue, Cost of sales, G&A — each can be broken down from the GL too).

**This turns on the real balance keystone** (previously deferred as "N/A — slice"): with a full TB the check is **Assets = Liabilities + Equity + (Income − Expense for the period)** — the P&L result flows into equity — not merely debits = credits. It only works once the engine knows which L0 sections are P&L vs balance sheet.

**Comparative periods:** real notes show current + comparatives (the real Investments note has three columns: 31 Mar 2025 / 31 Dec 2024 / 31 Mar 2024). Each column is its own TB. Multi-period is a real requirement, not just multi-note.

---

## 4. Three input cases — one detect-and-maximize pipeline, NOT three modes

Do not build a mode switch. Build: **detect what's present, produce the maximum that's supported, label what's missing.** The gap report already does exactly this — it just gets a richer state set.

**Mental model: the TB is the frame, the GL is the zoom.** TB = whole picture at face resolution. GL = high resolution on one tile. Frame-only: see everything, can't zoom. Tile-only: detail, but you don't know where it sits or whether it's the right size. Both: zoom *and* the detail is checked against the frame.

| Input | What you can produce | Status |
|---|---|---|
| **TB only** | Complete face statements (BS + P&L) + face-level notes (e.g. Investments 5.1: gross/allowance/net/total). Balance keystone runnable. **No** breakdowns. | Each breakdownable note: **BUILT at face level, PARTIAL for breakdown** ("GL not provided"). |
| **GL only** | The note(s) those accounts cover. **No** face statements, **no** balance keystone (slice), **no** independent magnitude anchor (the NEOM problem). | **PARTIAL — magnitude unverified.** (What we built today.) |
| **TB + GL** | Face + breakdown, **and the breakdown reconciles up to the TB line.** Magnitude anchored. | Reconciles → **BUILT.** Doesn't reconcile → **BLOCKED** (flag the difference — a real finding). |

The TB+GL case is the whole point: the **TB↔GL reconciliation** is a first-class keystone — the top-down successor to the footer-control-total check that caught the Prepayments 2× double-count. An *independent* magnitude anchor, available structurally whenever both inputs are present, not an accident of file format. **The breakdown must reconcile to the TB line, not merely sum to its own subtotal** (the internal-tie-that-lies failure, hit twice already).

---

## 5. GL routing (the app routes the GL — confirmed requirement)

The GL arrives **untagged**; the app must route each GL account to its TB line. This has a deterministic core and an AI-assisted fallback.

**Deterministic core — the TB already carries the routing rule.** Each GL account's code falls into a TB natural-account range (§2), and that range *is* its target line. Apply the mapping the accountant already built; don't invent one. The R2 account-range classification is literally the routing rule.

**The four ways routing goes wrong — each is a FINDING, never suppressed:**
1. **Orphan GL account** — code matches no TB range. The TB doesn't know it exists (chart-of-accounts/period mismatch, or genuinely unmapped). Flag "GL account X has no home in the TB" — flag-don't-absorb, one level up.
2. **Reconciliation gap** — routed GL accounts sum to a figure that ≠ the TB line. The difference is the headline finding ("GL Investments = 4.26B, TB line = 4.20B, diff 60M"). This is the TB↔GL keystone.
3. **Partial coverage** — GL covers some of a TB line's accounts, not all. Note states the covered fraction ("covers 80% of the TB line; 20% no GL detail"). **PARTIAL.** Guard: reconcile to the TB line, not the breakdown's own subtotal.
4. **Granularity mismatch** — GL at a different level than the TB line (one GL account feeding multiple TB lines, or sub-ledger detail below leaf). The Phase 1b "is this GL-level or below" question, in routing terms.

**Routing contract:** every GL account either routes to exactly one TB leaf (clean) or is flagged (orphan/ambiguous); every TB line receiving GL accounts gets a **coverage status + reconciliation result**. Output is not "breakdown built" but "breakdown built, covers X% of the TB line, reconciles to within Y." Feeds straight into the §4 gap-report states.

**The dependency risk to confirm with the team:** routing quality depends on the GL and TB **sharing a chart of accounts**. Same system/period → clean, deterministic lookup. Different entity/period/ERP with renumbered accounts → fuzzy-matching problem → AI proposes matches ("GL 11010105 Motor Vehicles ≈ which TB line?"), human confirms, store — the same propose/confirm/store pattern. So routing = deterministic core + AI-assisted fallback when codes don't cleanly match. **Confirm whether GL and TB will reliably share a chart of accounts.**

---

## 6. The adjustments layer (new input surface)

`Final = TB amount + Other adjustment`. This is a **human-entered** layer between the raw TB and the face figure — the one place a human *legitimately* moves a number (in named, auditable columns). It is neither TB-as-received nor GL.

- Decide with the team: are adjustments an **upload**, an **in-app edit**, or **out of scope for v1**?
- It does **not** violate "AI never moves a number" — a *human* moves it, in a named column, auditable. But it's a new surface and must be modelled explicitly, not folded silently into "the TB."
- The face figure is the **adjusted Final**, not the raw TB amount.

---

## 7. What carries over vs what's new

**Carries over (recast, not rebuilt):**
- The GL→notes engine → becomes the **breakdown layer** hanging off a TB line.
- Hierarchy (L4→L1 node table) → becomes the **TB level scaffold** (re-map L0–L4 ↔ our levels).
- Mapping table → **is** the "Actual mapping" column.
- Note modules (Investments 4b, Prepayments 4a) → breakdown modules, now anchored to a TB line.
- Gap report → same engine, **richer state set** (§4) — already does detect-and-maximize.
- Clarification loop, deterministic/AI boundary, flag-don't-absorb, prominence, the R-series guards, the synthetic overfitting fixture → **all unchanged**.

**New work:**
1. **TB ingestion** — parse the L0–L4 + ranges + Account Type P/C + amount/adjustment/Final columns; tolerate the known mess (stray tabs, sub-designation mappings).
2. **Face-statement assembly** — group mapped Final amounts → BS (Asset/Liability/Equity) + P&L (Income/Expense).
3. **The real balance keystone** — Assets = Liabilities + Equity + (Income − Expense); P&L result into equity.
4. **GL routing + the TB↔GL reconciliation keystone** (§5) — the core new capability.
5. **The adjustments layer** (§6) — pending team decision on form.
6. **Comparative periods** (§3) — multi-column notes, each column its own TB.
7. **Detect-and-maximize input handling** for the three cases (§4).

---

## 8. Sector note

The **engine is sector-agnostic**; only the **Investments note (4b)** is finance-sector-flavoured (IFRS 9 FVIS/FVOCI/AC + ECL — confirmed it mirrors a real published bank note, so its *structure* is correct, not overfitted). This new entity is **commercial/industrial** (wheat/grain trading: Inventory, Cost of sales, Trade payables, EOSB, Revenue) and needs a **different note set** (PP&E, Intangibles, ROU assets, CWIP, Inventory, Provisions, EOSB, Revenue, Cost of sales) — built as **modules on the same engine**, not an engine rewrite. The synthetic fixture proved the *ingestion/TB* engine generalizes; note-building on a non-financial entity is **still unverified** until the first non-bank note is built. This TB is the thing that would test it.

---

## 9. Open items to confirm with the team before/while reshaping

1. **Chart-of-accounts consistency** between GL and TB (§5) — determines whether routing is a lookup or a matching problem. Highest-leverage question.
2. **Adjustments layer** (§6) — upload, in-app edit, or out of scope for v1?
3. **Level-naming reconciliation** — adopt the accountants' L0–L4 (section→leaf) so we don't get crossed wires vs our old L1–L4.
4. **Comparative periods** — how many, and does each arrive as a separate TB file/column?
5. **P&L scope** — Abhishek mentioned P&L; confirm whether it's just "produce the income statement" or also P&L-line note breakdowns (model already covers both; just confirming intent).
6. A **populated** TB (and a matching GL) to exercise magnitude, not just structure.

---

## 10. Sequencing note (not a hard plan yet)

The cheapest order that de-risks the most:
1. TB ingestion + face-statement assembly (TB-only case → a complete face FS). Proves the spine.
2. The balance keystone on the full TB.
3. GL routing + TB↔GL reconciliation (TB+GL case → BUILT/BLOCKED). The core new keystone.
4. Recast the existing note modules as breakdown layers anchored to TB lines.
5. Adjustments, comparatives, and the non-bank note set, per team answers.

Carry every existing guard forward; add new guards for the new silent-failure surfaces (routing orphans, TB↔GL reconciliation, unit-label-matches-figures from the bug fix).
