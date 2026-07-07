# AI Accountant — Documentation Log

> **Living document.** Updated as we move through development. It records what we've done,
> why, decisions made, and current status. Newest entries at the top of the Changelog.

> ## 🔀 DIRECTION CHANGE (2026-06-09): pivot to FS-Gen (GL-driven)
> The project has pivoted from the **Note-5 cascade** (over synthetic `Holding_ID` tables) to
> **FS-Gen** — a GL-driven IFRS financial-statement-note generator per **`PRD.md`** and
> **`2_DEVELOPMENT_PLAN.md`** (the now-authoritative plan; `DEVELOPMENT_PLAN.md` is legacy).
> New architecture: **raw GL postings → canonical trial balance → account→hierarchy mapping →
> deterministic note modules → FS notes + exceptions/gap report.** First target = two real notes
> (**Investments, Net** + **Prepayments**) from real SAP GL exports in `GL/`. The old Note-5
> cascade (`ai_accountant/ui.py`, `compute/`, etc.) is **legacy**; new `ai_accountant/gl/…`
> modules must not import from it. New UI comes in Phase 5; until then we drive via CLI/scripts.

## Project at a glance (legacy — Note-5 cascade)
AI-assisted tool that turns raw transactional data (**L4**) into **Financial Statement notes**,
starting with **Note 5: Investments, Net**. The LLM only ever sees file *profiles* (headers +
sample rows); local Pandas does the heavy compute. Target model: **OpenAI GPT-5.1**.

See `PROJECT_UNDERSTANDING.md` for full context. `2_DEVELOPMENT_PLAN.md` is the current plan.

---

## How ingestion works (multi-table, multi-sheet, any level, foreign columns)

This is the heart of the "go through everything and figure out what each table is" capability.

### 1. Splitting many tables out of one sheet — `ingestion/table_detect.py`
A single sheet can stack many tables of different shapes (the sample CSV has 18). The detector
(`detect_tables`) uses three structural signals:
- **Blank rows end a table.** It gathers a *block* of consecutive non-empty rows; a blank line
  starts a new block.
- **Each block's first row is that table's own header.** Every table is parsed against its *own*
  columns — Table A can be `Holding_ID, ISIN, Carrying_Value_000` and Table B right after it can
  be `Txn_ID, Trade_Date, Total_Cost_000`. They share nothing.
- **Banners/titles are peeled off** (`===== L3: ... =====`, `5.1 ...`) and attached to the table
  that follows, not treated as data.
It also trims trailing empty columns, pads short rows, and drops single-cell annotation lines.

### 2. Adjacent tables with NO blank line — mid-block segmentation (hardened)
`_segment_block` splits a block further when a later row **looks like a new header** — i.e. it is
almost all text (numeric fraction ≤ 0.15) with ≥2 cells and differs from the current header. The
0.15 threshold is deliberately conservative so text-heavy *data* rows (e.g. equity holdings with
~0.21 numeric) are never mistaken for headers. So two tables jammed together with no gap still
split correctly.

### 3. Foreign column names → canonical fields — `ingestion/normalize.py`
Real files label the same concept many ways. `normalize_tables` renames recognized aliases to
canonical names (e.g. `Acquisition Cost` / `Cost` / `Total_Cost_000` → `Total_Cost_000`;
`Carrying Value` → `Carrying_Value_000`; `Asset Class` → `Classification`). Matching is on a
normalized form (lowercase, punctuation collapsed). Canonical names map to themselves and only
exact alias matches are renamed, so existing/foreign columns are never clobbered.
For genuinely unknown schemas, `routing.ai_normalize_tables` (key-gated) asks GPT-5.1 to map a
table's headers onto canonical fields (profiles only) — applied as a pre-pass before compute.

### 4. Level + role classification — `routing/router.py`
`detect_level` infers L1–L4 from column signatures (when banners are absent); `detect_role`
labels each table (purchases, holdings, movement schedule, …). `build_routing_map` produces the
reviewable map shown in the UI. Tables sharing a role-signature are then **merged across files/
sheets** (`cascade._collect_by_cols`) before aggregation — so data split anywhere recombines.

### Known limits (tracked)
- A header-less table can't be keyed by column name (needs the AI mapper or positional rules).
- Extremely irregular layouts may still need the LLM boundary/mapping fallback.
- Large-file (1M+ row) streaming not yet implemented (whole tables are read into memory today).

## Decisions log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-03 | Target model = **GPT-5.1** | User direction; replaces hardcoded `gpt-4o` in `engine.py`. |
| 2026-06-03 | **Thin end-to-end slice first** | Fastest path to real, demoable Note 5 numbers before scaling to messy inputs. |
| 2026-06-03 | **Lightweight in-process sandbox** now; harden later | Enough safety for a local POC; full isolation deferred to pre-deployment. |
| 2026-06-03 | **Restructure into clean modules** | Better foundation for a multi-phase app; existing code folded in, not discarded. |
| 2026-06-03 | **Local desktop only** for now | Simplest secrets handling (.env / UI entry); revisit deployment later. |
| 2026-06-03 | **Claude build workflow:** Opus drives; delegate only LARGE/parallel routine batches to Sonnet sub-agents | Most token volume stays on Opus for quality; Sonnet used only where its lower rate beats delegation overhead. No manual toggling. |
| 2026-06-03 | **Compute as a cascade: L4 → L3 → L2 → L1** | Build the final tables level-by-level (raw txns → sub-ledger → note tables → FS face); validate each level against ground truth for auditability. |
| 2026-06-03 | **Users can upload data at ANY level (L1/L2/L3/L4)** | System detects each table's level, computes only the missing higher levels upward, cross-validates where levels overlap. |
| 2026-06-03 | **Conflict rule: uploaded level wins over computed** | If a user uploads a level directly, that figure is authoritative; computed-vs-uploaded variance is shown as a flag, not auto-corrected. |
| 2026-06-03 | **Move sample CSV → `sample_data/`** | Cleaner project layout during restructure (Phase 0). |
| 2026-06-03 | Execution approach: **constrained hybrid** (AI code-gen, fenced + validated) | Scales to 1M+ rows while staying auditable. |
| 2026-06-10 | **Master FS = one human-approved structure store**, union of Bank AlJazira + SAAB face lines; STRUCTURE ONLY (no amount field) | One master serves all banks; each client renders only the concepts its TB populates. GATE 0 proves the JSON faithfully represents the approved xlsx (alias pairing included). |
| 2026-06-10 | **AI maps LEAVES only** (labels-only, pinned `gpt-5.1-2025-11-13`); a line matching no concept is PROPOSED, never invented | The AI never sees amounts and never authors structure; unsure → unmapped → finding (no forced guess). |
| 2026-06-10 | **Provenance honesty:** `preparer` / `ai_confirmed` / `ai_assumed`; auto-APPLY is fine, auto-APPROVE (relabel unreviewed AI as human-confirmed) is rejected | The laundering failure the project exists to avoid. Unreviewed AI maps render amber `ai_assumed`; NOT-FINAL footnote conditional on real state. |
| 2026-06-11 | **Subtotals/totals/net-lines are DERIVED by the engine** from human-authored signed formulas (`Formulas/master_fs_rollups_authored.json`); the AI never authors them | The AI/arithmetic boundary: mapping is judgment (AI), roll-ups are arithmetic (deterministic). Derived lines render neutral, never amber. |
| 2026-06-11 | **Two guards:** orphan-leaf (every populated leaf in a total's transitive closure) + balance-check (assets vs L&E) | Both surface as findings, never block or auto-correct — a wrong total can't be born silently; an unbalanced TB's difference is signal pointing at what's unmapped. |
| 2026-06-14 | **The seed declares its own structural roles** (statements/sections/coverage_totals/balance_check/memo_leaves/placement/prompts in an `engine` block); the engine reads them, never literals | A new archetype is a new seed, not an engine change. Proven byte-identical for the bank + a telecom stub that runs with zero engine edits. |
| 2026-06-14 | **Seed registry + one orchestrator entry point** (`generate_master_fs(..., seed_id=…)`); `seed_id` explicit in Slice A | Scripts and the future GUI share one flow; `seed_id` is the slot where Slice-B archetype detection will plug in. |
| 2026-06-14 | **Stores carry `master_id`; mappings scoped to `(master_id, client_id)`** (DB-ready shape, no DB) | A mapping references a concept_id meaningful only within its master; scoping makes cross-archetype leakage impossible (a client spanning masters raises). |
| 2026-06-14 | **Mapper targets INPUT LEAVES only; a bad target BLOCKS (finding), never absorbs** | A TB amount must never land on a computed total or a carry-leaf; blocking-with-a-finding keeps a wrong total from being born and never silently drops the amount. |
| 2026-06-14 | **Carry-leaves are seed-declared and engine-populated** (`engine.carry_leaves`), e.g. OCI net income ← P&L total | Net income into OCI is deterministic arithmetic, not a mapped/AI line; declaring it per-seed keeps the engine archetype-agnostic and fixed the silent Total-CI understatement in BOTH seeds. |
| 2026-06-14 | **Model pin stays a HARD literal in `config.py`** (dated snapshot, exempt from de-hardcoding) | A floating alias is a reproducibility hole (silent behaviour drift); the dated pin is a framework invariant — see the changelog rationale. |
| 2026-06-14 | **Archetype detection = LLM per-label fit + DETERMINISTIC verdict; conservative (unsure is the easy landing)** | A confident WRONG archetype is the worst outcome; the score is a grounded discriminating-label fraction, never a model confidence number, and a winner needs high-top + clear-margin + weak-runner-up. Detection PROPOSES; a human confirms via the existing gate. |
| 2026-06-14 | **Detection thresholds live in the registry (`detect_thresholds`), not engine code** | Calibrated on N=2 seeds and provisional; a new seed/TB set must re-tune them without an engine edit (same de-hardcoding rule as concept_ids/sections). |

---

## Phase status
| Phase | Title | Status |
|-------|-------|--------|
| 0 | Foundation & scaffolding | ✅ Complete (live GPT-5.1 JSON call verified) |
| 1 | Thin end-to-end slice (real Note 5) | ✅ Core complete — cascade computes & reconciles; UI redesigned; tests pass |
| 2 | Robust heterogeneous ingestion | ✅ Complete — Excel/multi-sheet/multi-file, level detection, cross-source merge, routing map, adjacent-table splitting, foreign-column normalization (+AI), robust prompts, large-file streaming, opening-balance inputs |
| 3 | Policy enforcement & accounting rules | ✅ Complete — classification engine (policy → IFRS 9 fallback), explainable decisions, wired through UI |
| 4 | Validation harness & audit trail | ✅ Core complete — multi-level reconciliation + audit drill-down (editable routing map still deferred) |
| 5 | Exports (Excel/PDF) | ✅ Complete |
| 6 | Generalize to more notes + polish | 🟡 In progress — note-definition framework done; per-note compute logic + 2nd note (needs data) pending |
| 7 | Hardening (pre-deployment) | Deferred |
| **M1** | **Master-FS face-statement generator** (see section below) | ✅ Demo-complete — TB → map-into-master → derived faces (BS/P&L/OCI) for BOTH banks, live GPT-5.1; presentation-complete (subtotals/totals/net-lines/OCI buckets/SAR'000+dates); two guards; honesty rendering. Slice-10 interactive human-confirm GUI parked. |

---

## Open questions / to confirm
- _(none blocking right now)_
- Phase 2: precise table-boundary detection heuristics — to validate on fixtures.
- Phase 3: which IFRS 9 default rules to encode for the no-policy fallback.
- Phase 6: which note to build second.

---

## Overfitting audit — config vs engine (the standing question at every phase)

The test is not "does it work on the two real files" but "what happens when a different file hits
it." `tests/test_synthetic_gl.py` is a permanent fixture built to be unlike both real files
(7xxx accounts, 12-col layout, EUR doc currency, foreign descriptions/reference codes).

**General (engine) — proven on the synthetic file or by changing no number when generalized:**
- Field resolution by *meaning* (the 12-col foreign layout resolved; `REQUIRED_FIELDS` validated).
- Blank-account disposition: continuation (own transactional id) / subtotal / orphan (R14).
- Column-shift quarantine; dedup guardrail (no line field → flag, never drop — R6).
- Control-total capture + the reconciliation keystone (closing + held-out == Σ controls — R14).
- Unmapped-account flagging (surfaced, never absorbed); unknown reference-code → "Unclassified
  movement", in closing, flagged (R3).
- Period split / roll-forward / telescoping; held-out breaks the tie (R9); gross−ECL netting **via
  sign + tree roll-up** (the mechanism is general).

**Data-shaped (config — seeded, per-source, swappable without touching the engine):**
- `field_resolver._HEADER_MAP` (SAP header aliases); `SEED_TAXONOMY` (prepayment keywords — now an
  injectable `PrepaymentTaxonomy` object, not baked into `classify_label`); `reference_codes._REF_TO_LINE`
  (movement codes); `seed.py` (account→measurement-type `1101→FVIS…`, the `…9900` allowance
  convention, account→note mapping, note layout).

**Honest caveats (data-shaped facts that still live IN the engine, or availability that isn't
guaranteed):**
- **Sheet-name parsing** (`"ACCT GL - COMPANY"`) in `gl/ingest.py` is SAP-export-shaped — a
  different naming convention would need config. (The synthetic file reused the convention, so this
  is *not* yet proven general — flagged, not hidden.)
- **`is_brought_forward` keywords** (take-on/migration vocabulary) are SAP-migration-shaped.
- **The `…9900` allowance identification** is NEOM's coding convention (the *netting* is general).
- **The footer keystone exists for Prepayments but not Investments** — magnitude verification depends
  on the file carrying an independent total; it is not an engine guarantee (R16).
- On another entity the keyword taxonomy will match less and "Other" will balloon — **safe** (it
  ties, it's surfaced), but it confirms the taxonomy is a per-source starting point, not general.

## Master-FS face-statement generator (M1 — current focus)

Turns a client trial balance into the three **face statements** (Balance Sheet, Income Statement,
Statement of Comprehensive Income) against one shared, human-approved **master structure** — proven on
representative TBs for **both** Bank AlJazira and Saudi Awwal Bank (SAAB). Faces only; note-by-note
breakdowns are a later phase (the document says so and renders no placeholder note).

**Pipeline:** TB (raw or pre-mapped) → map each leaf into a master concept → derive the subtotal/total
spine → render the populated faces in the client's own labels → provenance view + findings page.

**Modules** (`ai_accountant/master_fs/`): `model.py` (the three DB-ready stores: MasterStructureStore /
ClientMappingStore / ProvenanceStore; `MasterConcept` carries `kind`+`components`, no amount field);
`seed.py` (load), `validate.py` (**GATE 0** JSON↔xlsx↔CSV + `validate_rollups` authored-formula fidelity),
`mapping.py` (live `gpt-5.1-2025-11-13` propose / propose-addition, labels-only), `derive.py` (topological
derive pass + orphan guard + balance check), `render.py` (section-blocked, populated-only + spine).
Export: `reporting/master_fs_export.py` (Excel + PDF; one statement per page). Seeds:
`seeds/master_fs_structure_seed.{json,csv}` (64 concepts) + the approved xlsx; authored roll-ups in
`Formulas/master_fs_rollups_authored.json`. Demos: `scripts/master_fs_demo.py` (AlJazira),
`scripts/master_fs_saab_demo.py` (SAAB). Tests: `tests/test_master_fs.py` (18). Artifacts in `exports/`.

**Invariants (all enforced + tested):** master = union, STRUCTURE ONLY; AI maps leaves only and never
authors formulas or amounts; subtotals/totals/net-lines are deterministic arithmetic (neutral render);
`ai_assumed` (unreviewed AI) renders amber and is **never** relabelled human-confirmed; orphan-leaf and
balance guards surface as findings, never block/auto-correct; comparatives present-where-present.

**Interactive per-line human-confirm GUI — DONE (Slice G1, `fsgen_mfs.py`):** the master-FS confirm chain is
now on screen as a view coexisting with the GL pipeline — detect → CONFIRM archetype (no default) → per-line
CONFIRM mapping (`ai_assumed → ai_confirmed`, unreviewed stays amber) → unit → generate → notes → CONFIRM
split → bytes export, each gate a real human stop, every figure engine-computed. Demo-driven by the
bank/telecom/ambiguous fixtures through an OFFLINE fenced stand-in (`_DemoLLM` — proves wiring, not accuracy);
a real `LLMClient` + live multi-file xlsx ingestion is the next GUI slice. **Real-input flag:** the roll-up
signs assume the TB stores expenses/zakat/tax negative — a client storing them positive must record that at
confirm, never assumed.

## Changelog
### 2026-06-26 — Slice SL-1c.1-gui: wire the register capability into the app (the U5 discover→confirm gate)
The register engine (SL-1c.1/c.2) is now reachable from the app: upload the multi-sheet workbook → the app
DISCOVERS which sheets are the registers (propose → confirm) → feeds them → the enriched notes render. GUI wiring
only, bounded by the B2b BS-split second-sheet precedent.
- **The user-facing answer (which sheet is which, no literal, no silent guess):** after the TB + archetype are
  confirmed (so the store is loaded), a new **post-store U5 gate** iterates ONLY the register-declaring concepts
  (`master_store.notes()` where `mechanism=="register"` → `bs_investments`, `bs_loans`) and, for each, **proposes**
  which remaining sheet is its register — `propose_register_sheets` runs Layer 0 scored name/header match (no
  model; both resolve here on the real file) → Layer 1 headers-only AI on a miss. The user **confirms** via a
  per-register selectbox `["(none)"] + other_sheets` (the U4 pattern); '(none)' or unmatched → the **coarse TB
  note** (the existing `notes.py:526` register-presence pick). The 13 non-register sheets are untouched.
- **Lighter register column-confirm (the headers-only firewall into the GUI):** the register does NOT reuse U2/U4's
  `propose_column_roles` (which sends sample rows → attribute values to the model). `read_register`'s LOCAL
  heuristic picks the tie column (shown for transparency on confirm); only HEADERS ever reach a proposer
  (`propose_register_sheets`/`propose_register_amount_cols`). Everything else auto-carries as an attribute.
- **Feed (one line):** `fsgen_mfs.py:849` — for an upload, `payloads = ss.get("mfs_reg_payloads", {})` (the
  confirmed registers, read via `read_register`) → `build_master_fs_export(..., gl=payloads)`. **Show:** the screen
  `render_mfs_note` N-column branch + the PDF/Excel emitters already render the table (SL-1c.1/c.2) — no new render.
- **State:** new `ss.mfs_reg_*` keys (proposal, payloads, done) mirror the BS-split's `ss.mfs_bs_*`; added to
  `_restart_downstream`. Multi-sheet read reuses the retained workbook bytes (no new upload machinery); per-line
  mapping volume is unchanged (register rows are carried, not mapped).
- **Proof:** `tests/test_sub_ledger_register_gui.py` (6 — Layer-0 discovery on the real file, register-declaring-
  concepts-only, Layer-1 AI on a differently-named sheet, headers-only firewall, feed→both enriched notes render,
  graceful '(none)'→coarse). **22 suites green**, the existing AppTests unaffected (single-sheet upload → no
  `other_sheets` → U5 dormant), frozen-replay byte-identical, grep-clean (scored + AI + user confirm — no sheet
  literal). **Out:** FAR/PP&E (movement), Financing-Working (cross-tab).

### 2026-06-26 — Slice SL-1c.2: register enrichment (Financing-net) — the reuse proof on a real second register
The headline is REUSE: SL-1c.1's machinery carries a second, differently-shaped register with **zero render-code
change**. SL-1c.2 touched only the seed + `attach_register_note` — `render_model.py`/`excel_writer.py`/the PDF
emitters are untouched, yet Financing's columns (gross/allowance/net + Segment/Sector/Stage) render on screen,
PDF, and Excel. The column-list-driven design, proven on a synthetic in SL-1c.1, is now proven on **real** data.
- **Reused unchanged:** the render (`renderable_register` + the N-column emitters + `columns`/`cells`), the tie
  firewall, the layered association (the "Financing" sheet → `bs_loans` at Layer 0, no model), the register-
  presence pick (`notes.py:526`), the faithful-carry guard. The amount-column preference already picks
  **`Financing, net 2025` as the tie column** (gross/allowance carried as attributes) — no new detection code.
- **New (the only content):** seed `{concept:"bs_loans", mechanism:"register", caption}`; a **per-row
  `gross + allowance == net` cross-check** (`attach_register_note`, the contra-as-COLUMN case — Investment's was
  a row): header-detected (runs only when gross + allowance columns exist for the current period; Investment
  skips it), the engine reads those numbers for a PROOF and never re-derives net — a mismatch BLOCKS *even when
  the net sum ties* (proven). Plus the **honest prior-not-tied flag** (below).
- **The prior-year honest finding (faithful-carry under pressure):** the register has **no prior net** — only
  current gross/allowance/net + prior GROSS. The prior tie is genuinely unachievable (TB `bs_loans` prior
  96,912,496 net ≠ register Gross 2024 99,441,503; no prior allowance to derive from). So the **current-year tie
  holds** (Σ Net 2025 = 110,862,169 = the face) and the **prior tie is SKIPPED, not faked** (`has_prior=False`,
  the existing graceful path — no invented prior). Prior Gross 2024 is carried as a displayed attribute + a
  *"prior carried but NOT reconciled — the register provides no prior net"* **caveat** (surfaced, BUT the note
  stays BUILT — the current year ties). It is NOT presented as a both-years-tied note.
- **Proof:** `tests/test_sub_ledger_register_financing.py` (6 — net-tie/no-prior/segments, current-tie BUILT +
  prior-not-tied, the reuse render on real columns, broken-sum BLOCK, per-row cross-check flags-when-sum-ties,
  coarse-vs-enriched + Layer-0 association + Investment-still-ties regression). **21 suites green**, frozen-replay
  byte-identical (additive), grep-clean holds. **Out (unchanged):** FAR/PP&E (movement), Financing-Working
  (IFRS-9 cross-tab), SL-1c.1-gui.

### 2026-06-26 — Slice SL-1c.1: register enrichment (Investment) — carry the securities register, tie to the face
Phase 2 begins: take a note from TB-granularity to full REGISTER-granularity by reading a sub-ledger register,
carrying its rows + WHATEVER attribute columns it has VERBATIM, and tying the register's amount-sum to the TB
face concept (the control-total firewall). Investment end-to-end, proven on the real `Draft Data` register.
- **Read (`tb_ingest/register.py:read_register`):** reuses `grid.py`; a local column split identifies the amount
  column(s) (Carrying Value 2025/2024 — preferring a *closing* header over an allowance/face/nominal sub-column
  that shares a year) and carries **everything else as an attribute, verbatim**. Section rows (`A) HELD AT FVIS`)
  group the rows; repeated per-section header rows are skipped; a zero-carrying (redeemed) security is kept. The
  contra rows (`Less: Allowance`, negative carrying) net into the sum — no `"Less:"` literal.
- **Associate (no literal):** a new seed `mechanism:"register"` on `bs_investments` (alongside `static_breakdown`).
  Layered sheet→concept proposer (`propose_register_concept`): **Layer 0** token/prefix match of the sheet name +
  headers against the concept *label* (the real "Investment" sheet resolves here, no model); **Layer 1** live AI
  (headers + candidate labels only) on a miss; human confirms; unsure → flag. Candidates are seed data.
- **Tie firewall (`notes.py:attach_register_note`):** `Σ register == bs_investments face` (= the mapped TB leaves,
  `_concept_mapped`), **both years independently**, BLOCK on mismatch — the register is EXTERNAL, so the tie is
  genuinely non-tautological. Section sub-totals foot to the grand total. A broken register (a dropped/altered
  row) → BLOCKED, never shown reconciled. The **existing register-presence pick** (`notes.py:526`) selects
  enriched-vs-coarse (register present → enriched writes; absent → the SL-1 coarse static note, byte-identical) —
  no new selection code.
- **Render — NET-NEW, column-LIST driven (built once, reused by SL-1c.2):** `RenderableNote` gained an optional
  `columns` and `RenderRow` a `cells` (existing emitters ignore them → label+amount notes byte-identical).
  `renderable_register` + new N-column emitters: **screen** (`render_mfs_note`), **PDF** (`_register_table` beside
  `_note_page`), **Excel** (`_write_register_sheet`). Carries WHATEVER columns the register has — a synthetic
  different-columns register renders with no code change.
- **Faithful-carry firewall:** attribute VALUES ("Aa3", "Stage 1") are pure pass-through — they appear VERBATIM in
  the PDF/Excel output; only HEADERS reach a model (`propose_register_concept`/`propose_register_amount_cols` are
  headers-only — **not** `propose_column_roles`' sample-rows). The **attribute-values-never-sent** test walks every
  model payload (association, amount-col) and asserts no value/amount leaks — the new Phase-2 guard.
- **Proof:** `tests/test_sub_ledger_register.py` (9 — read/tie both years, BUILT, broken→BLOCKED, coarse-vs-
  enriched, PDF+Excel verbatim attributes, column-list synthetic, Layer-0/Layer-1 association, values-never-sent).
  **20 suites green**, frozen-replay byte-identical (register additive; absent → coarse identical), grep-clean
  holds. **Out (separate slices):** the GUI register-upload step (SL-1c.1-gui), FAR/PP&E (movement), Financing
  ECL staging (cross-tab); Financing-net (SL-1c.2) reuses the column-list render unchanged.

### 2026-06-26 — Slice SL-1d: three GUI-trustworthiness fixes (a correct engine that no longer misleads)
SL-1b balanced the real TB, but a user trusting the defaults could still be misled. Three fixes:
- **Fix 1 — the expense-sign proposal (a silent failure with no arithmetic anchor).** `propose_tb_sign` lumped
  income+expense into one `result` side and applied the income rule (flip iff net<0) to both — but expense's
  presentation TARGET is NEGATIVE, the opposite. A positive-stored expense section proposed `as_is` → the P&L
  footed to the WRONG net income (~19.4M vs ~1.5M), and the SOFP balanced anyway (the balance-check never sees the
  P&L), so nothing screamed. Fix in `tb_ingest/sign.py`: `_side_of` now splits **expense vs income**, and the
  proposal reads each section's stored net against its **target sign** (asset → as_is; income/liability/equity
  target + → flip iff net<0; **expense target − → flip iff net>0**). Data-driven, the **same detection serves both
  conventions** — a negative-stored expense (`bank_synthetic`) proposes `as_is`, a positive-stored one
  (Draft_Data) proposes `flip` — NOT a hardcoded flip. The real TB now foots the P&L to **1,505,544 by default**.
  Plus a **consequence-shown confirm** at U3 (the only guard where no anchor exists): it shows the income/expense
  sections netted under the current signs (~1.8M right vs ~19.7M wrong), live, so a wrong pick is visible.
- **Fix 2 — the residual marker read the wrong KIND.** `render_mfs_faces` hardcoded `:violet[MANAGEMENT JUDGMENT
  (split)]` for every judgment line, so the estimated residual looked like a current/non-current *split*. Now the
  build carries `MfsExport.judgment_kinds` (the marker's kind per concept: `"split"` from the maturity path, a
  seed-declared `caveat_kind` e.g. `"estimated residual"` from the caveat hook), and the face renders the line's
  **own** kind (`:violet[ESTIMATED RESIDUAL]`). Finding-type-driven; the specific label is SEED data (new
  `caveat_kind` field), no per-concept literal in `master_fs_export.py` (grep-clean).
- **Fix 3 — the Source cross-check is now surfaced.** `fsgen_mfs.py` imports `source_routing_audit` and runs it at
  G2 on the resolved proposals; a Source-tag-vs-resolution conflict (or a concept carrying several tags) shows as
  an **advisory warning** (no auto-route, no balance impact) — the human resolves at the per-line gate.
- **Proof/regression:** `tests/test_sub_ledger_gui_trust.py` (6 — both expense conventions, the distinct sides,
  the residual kind, the Source conflict); `test_sub_ledger_full_balance.py` updated to drop the manual
  `Expense=flip` (now the default) and assert it. **18 suites green**, frozen-replay byte-identical (proposal/tag/
  GUI changes, not derive arithmetic), grep-clean holds.

### 2026-06-26 — Slice SL-1b: route P&L/OCI + the cheap gaps → the full faces balance on the real bank TB
The end-to-end milestone: the real `Draft Data for working.xlsx` bank TB ingests → routes → the **SOFP balances
both years**, the income statement foots, and OCI foots for the aliasable movements. Three separable milestones,
held distinct:
- **SOFP balances (the headline)** — needed only two rows beyond SL-1: a **PP&E alias** (the TB L2 adds
  "intangibles" + uses "right-of-use" hyphens) so the 3 PP&E rows route and PP&E builds its coarse TB-granularity
  note; and the **equity "combined balancing residual"** (gl 1068, Source "ESTIMATED"). Per the approved option
  (b): a NEW seed concept `bs_equity_residual` (verbatim caption; `bs_statutory`/`bs_retained`/`bs_treasury` stay
  separate — the plug is NOT absorbed) added to the `bs_total_equity` roll-up. A seed-declared `caveat` on the
  concept drives a **face-visible** marker — a `caveat:bs_equity_residual` finding + a persistent judgment marker
  on the line + `not_final` — so equity balances *and the statement shows it's an estimated plug* (the line between
  honest-residual and quiet-plug). New `MasterConcept.caveat` field; build hook on a populated caveat-leaf.
- **The router fixes that made the full TB resolve (the real work):** routing the whole TB exposed a
  **cross-statement** bug — a P&L row whose instrument label ("Financing", "Customers' deposits") uniquely matches
  a BS concept alias mis-routed onto the balance sheet (inflating assets 7M+). Fixes in `resolve.py`: (1)
  `_statement_from_levels` now treats **L0 as authoritative** (an `FVOCI` investment or an equity "…OCI…" reserve
  stays on the balance sheet; only Income/Expense rows split into IS vs OCI — and `oci` matches as a WORD, not
  inside `FVOCI`); (2) `resolve_concept` applies the **statement filter even to a lone match** (a P&L row never
  maps to a BS concept); (3) `resolve_row` tries a **combined "L2 - L3" key** (last, additive) so an ambiguous OCI
  movement ("Net change in fair value" under both FVOCI-debt and -equity) disambiguates by its reserve.
- **P&L/OCI routing (aliases, router otherwise unchanged):** `pl_fvis` ("Net gain on FVIS…"), `pl_impairment`
  (the real-estate impairment *reversal* — surfaced at the per-line confirm to override), and 5 OCI combined-key
  aliases. The **3 genuinely-conceptless** OCI movements (FVOCI-equity transfer-to-retained, employee-share-based
  ×2) **FLAG** — never forced into a near-miss concept (graceful degradation on the P&L side). 135/138 routed.
- **Sign-confirm note:** the deterministic `propose_tb_sign` proposes `Expense=as_is` for this TB, but it stores
  expenses POSITIVE and the engine wants them negative — so the income statement foots to the right net income
  only with the **human Expense=flip** confirm (the SOFP balance is unaffected by the P&L sign). The proposal is a
  starting point the human corrects; tightening the expense-sign heuristic is a separate follow-up.
- **Seed-fidelity:** `bs_equity_residual` is `presence:"draft_only"` — `validate_seed` now skips draft-only
  concepts (a draft plug isn't in the published-FS xlsx); the CSV flat-copy + the authored equity rollup DO carry
  it (JSON↔CSV in sync, the formula authored). **18 suites green; frozen-replay (17 static + SL-1 BS baselines)
  byte-identical; grep-clean holds** (aliases + residual caption are seed data).

**KNOWN LIMITATION — the current/prior global-swap (recorded, not fixed):** the SOFP balance-check cannot catch a
*consistent global* current↔prior column swap — both years balance either way, so the arithmetic is blind to it.
The only guard is SL-1's **values-shown column confirm** (`column_amount_audit` + the `period_ambiguous` gate);
there is no internal anchor. A future anchor would be a **known published prior figure or a separate prior-period
TB**. Until then, a swap on a year-less-header TB is caught only by the human reading the shown column sums.

### 2026-06-25 — Slice SL-1: TB-spine note generation (route → build every TB-granularity note → tie)
The TB carries each note's reconciling line structure (e.g. `Customers' deposit` L2 → Demand/Saving/Time/Other
L3, each a row). SL-1 builds those notes on the EXISTING static path, degrading to the granularity the TB
supports — never inventing the finer detail a gold-standard note shows, never refusing.
- **Routing (no Source dependency):** the existing layered `resolve.py:resolve_row`/`resolve_concept` resolves
  each row to a concept via its L2 level (Layer 0 alias → Layer 1 strip → Layer 2 live-AI → flag); the note is
  the concept's seed-declared static_breakdown. Proven Source-ABSENT (`test_sub_ledger_tb_spine.py`).
- **Seed (data only):** declared `static_breakdown` notes for `bs_deposits`/`bs_due_to`/`bs_due_from`/
  `bs_other_assets`/`bs_other_liab`/`bs_cash` (the `aljazira` aliases already match the real bank TB wording).
- **Build + tie + graceful degradation:** rides `attach_static_breakdown` + its partition firewall (Σ==face,
  both years, `notes.py:427-432`). N13 builds the 4 TB lines (Demand/…), NOT the gold Retail/Corporate split —
  BUILT + tied, never refused. No new build path, no new firewall, no new renderer.
- **Risk-1 (the silent-failure guard) — `columns.py`:** the real TB has FOUR identical `Balance '000 SAR (..)`
  headers + two `Adjustment` columns. Added an `adjustment` role; the raw balance before an adjustment is
  DEMOTED (the post-adjustment balance is read); when two amount columns carry no year, `period_ambiguous`
  flags the positional current/prior guess and the upload gate forces an explicit, values-shown confirm
  (`column_amount_audit` shows each chosen column's Σ). Honest cross-check finding: the SOFP balance-check
  catches an INCONSISTENT pick but NOT a consistent global current/prior swap (both years still balance) — so
  the explicit confirm-with-values is the only guard for the swap; the raw-vs-adjusted silent failure IS now
  caught structurally. `test_sub_ledger_columns.py`.
- **Source = OPAQUE accelerator (`source_route` role + `source_route.py`):** a preparer `Source` tag ("Note 13",
  compound "Note 15, 30", sub "Note 15(a)") is parsed to opaque group keys (never matched against a note
  literal) and CROSS-CHECKS concept-resolution (conflict/split surfaced, never auto-routed). No-dependency
  proven: byte-identical notes built with the Source column present AND absent. `test_sub_ledger_source.py`.
- **Real-file run (`Draft Data for working.xlsx`):** ingest → Risk-1 picks the adjusted 2025/2024 columns →
  route (122/138 rows; 16 flagged) → the 7 BS-side notes build + foot. **Honest scope boundary:** the full
  SOFP/P&L does NOT yet balance — the 16 unrouted rows are 12 P&L/OCI (deferred to SL-1b), 1 equity "combined
  balancing residual" (a synthetic non-concept row, correctly flagged), and 3 PP&E (an alias gap). BS-side
  NOTES are the SL-1 deliverable; full face balance needs SL-1b (P&L routing) + the equity-residual case.
- **Frozen-replay:** existing 17 static notes byte-identical; the 6 new bank notes added to the baseline (the
  regen aborts if any existing note changed). **17 suites green; grep-clean holds.** Phase 2 (register join +
  N-attribute table render) and SL-1b (P&L) NOT built here.

### 2026-06-24 — Remove the legacy GL "statement-first" pipeline (the app is seed-driven ONLY)
The UI had a `View` toggle between a legacy "GL pipeline (statement-first)" flow and the "Master-FS (seed-driven)"
flow. The GL pipeline — and its whole backend — was removed; `fsgen_app.py` now boots straight into
`fsgen_mfs.render_master_fs` (no toggle). The seed engine, however, was BUILT ON the GL-era note libraries, so the
removal was a 4-slice disentanglement, each guarded by the full suite (and a frozen-replay for the note machinery):
- **Slice 1 — frontend + truly-orphaned modules.** `fsgen_app.py` → a 15-line shim. Deleted `reporting/statement_view.py`,
  `reporting/statement_export.py`, the GL-frontend tests (`test_fsgen_app`, `test_recompute`, `test_recompute_anchor`,
  `test_statement_view`), `scripts/demo_export.py`; trimmed `reporting/__init__.py`. `ai_accountant/recompute.py` was
  deleted and its one live use (the `Resolution` record) inlined into `face_tb/recompute.py`.
- **Slice 2 — relocate the note machinery GL-free** into `ai_accountant/master_fs/notelib/`: `note.Presentation`,
  `reference_codes` (movement configs), `MovementSchedule` + `build_movement_note` (the generic two-layer roll-forward),
  and `build_ppe_note`. The former GL coupling — the `clarify` ClarificationQueue — was only ever used to raise
  questions the seed engine **discarded** (it consumes `build_…(…)[0]`), so it was dropped; the builder returns
  `(note, None)`. Proven byte-identical by `tests/test_notelib_frozen_replay.py` (the telecom notes: intangibles
  BUILT, tc_ppe PARTIAL — 12 notes, full row grid).
- **Slice 3 — relocate the proposers + reconciliation types GL-free.** `notelib/propose.py` (`FaceMappingProposal`,
  `propose_seed_mapping`, `ConfirmedPPEAccount` — the 3 symbols the seed path used; `confirm_seed_mapping`, the only
  `hierarchy`-dependent one, was NOT on the path and is gone). `notelib/recon.py` (`TBAccount`, `LineRecon`, a minimal
  `FaceTB` — `face_tb.classification` lived on `FaceTB`, not `TBAccount`, so it dropped out). After this the seed path
  imports ZERO GL packages directly.
- **Slice 4 — delete the GL backend.** Severed the last transitive reach (`reporting/gap_report.py → clarify`: kept the
  GL-free `note_status`/`NoteStatus`, removed the CLI `GapReport`). Deleted **7 packages** — `gl`, `face_tb`, `fs_notes`,
  `clarify`, `hierarchy`, `trial_balance`, `parsing` — plus 17 GL-only test suites and 15 legacy GL dev scripts.
  `ai_accountant/` is now 4 packages: `master_fs`, `tb_ingest`, `reporting`, `llm`.
- **Result:** suite **34 → 14 suites green** (−4 GL-frontend −17 GL-backend +1 frozen-replay); grep-clean still passes;
  the relocated mechanism (`notelib/movement.py`) carries no note vocabulary (its existing guard was repointed).

### 2026-06-21 — Slice S6a: deterministic balance-failure sign-diagnosis (fixes Issue 2, NO AI, NO key)
The reversed AlJazira run left equity off by **−166,380**: the seed's `bs_total_equity` formula SUBTRACTS
`bs_treasury` (`["-", "bs_treasury"]`), but that TB stored treasury **already negative** (−83,190), so the
roll-up double-negated it (`−×− = +`) — off by exactly **2×83,190**. The bank fixture stores treasury **+200**
under the SAME formula and balances, so the fix is a **per-TB** correction, never a global flip. S6a diagnoses
and proposes; the human confirms; the EXISTING balance-check RE-PROVES. No AI, no model, no concept literal.
- **`derive.py:derive_statement(..., sign_overrides=)`** — a per-TB `{component_id -> '+'/'-'}` correction to a
  component's ROLL-UP sign only: `total = Σ _sign(sign_overrides.get(dep, sgn))·values[dep]`. The leaf AMOUNT is
  untouched — the line still presents its stored sign; only the total's sign is corrected. Threaded through
  `render_statement`/`render_comparative` (both periods) and the export's balance-check (it RE-PROVES with the
  override applied). Default `{}` → byte-identical to before (regression guarantee).
- **`derive.py:diagnose_balance(...)`** — DETERMINISTIC detector: walk the seed's component graph for leaves
  carried with a SUBTRACTING (`'-'`) sign and a non-zero value (the double-negation signature); for each, re-derive
  with that one sign flipped and keep it ONLY if the balance re-derives to zero. Returns candidates carrying
  **structure + sign-flags + a small-int multiple — NO SAR amount** (so Slice S6b can hand it to the model without
  leaking magnitudes). Structural — no treasury literal, works for any contra.
- **The decision discipline — AI/code/human/firewall separation, intact:** the detector PROPOSES the **single**
  clean candidate, **DEFERS on >1** (never guesses), stays flagged on 0. The human CONFIRMS (`fsgen_mfs.py` gate,
  upload-only, single-candidate-only). Code APPLIES a per-TB `stored["sign_corrections"]`/`…_confirmed`. The
  unchanged balance-check is the FIREWALL — it re-derives and clears ONLY at true zero; a **wrong** correction
  (proven: flip `bs_share_cap`) stays flagged, an **unconfirmed** one is never applied.
- **Per-TB coexistence:** the correction lives in `stored[...]` keyed to that TB, so the +200 bank fixture
  (additive treasury) and the −83,190 AlJazira TB (corrected to additive) coexist with the same seed formula.
- **Tests — `tests/test_balance_sign_diagnosis.py` (7, no key):** Issue-2 fixed end-to-end (diagnose→confirm→
  RE-PROVEN, treasury line still −100, total corrected); wrong correction stays flagged; unconfirmed not applied;
  clean run → no diagnosis; **generality** (a non-treasury contra detected, no literal); **ambiguity** (two equal
  contras → BOTH returned → caller defers); 0-candidate honesty. Payload-carries-no-magnitude asserted on the
  candidate. **`test_bank_notes_demo` (treasury +200) stays green. 34 suites green.** Slice **S6b** (hand the
  no-magnitude candidate to the live AI for ambiguous/synonym cases) is a separate later slice — not built here.

### 2026-06-21 — Slice S5a-resolve: suffix-strip in the MAPPING resolver (symmetric with S5a)
The S5a anchor fix had a twin gap: `resolve.py:resolve_concept` (which decides WHICH concept an amount maps to)
used the same exact-match, so a suffix-variant leaf label only mapped via the live AI. S5a-resolve makes it
layered, reusing the S5a strip.
- **`notes.py`** — extracted `_strip_quals(t)`, the normalisation-agnostic qualifier-strip CORE; `_strip_qual(s) =
  _strip_quals(_norm_lbl(s))` (S5a unchanged). So the breakdown anchor and the resolver share ONE qualifier rule,
  each under its own normaliser (resolve's `_norm` folds dash variants) — no dash edge-case.
- **`resolve.py:resolve_concept`** — **Layer 0** (exact, UNCHANGED) → **Layer 1** (S5a-resolve): on a Layer-0 miss,
  rebuild `matches` via `_strip_quals` equality, then the EXISTING statement/maturity disambiguation (`:54-71`)
  runs unchanged. **Layer 2** (the B2c live-AI fallback) is untouched and fires only on a Layer-0+1 miss.
- **Heightened safety (a misplaced AMOUNT is worse than flat presentation) — all three guards, negative-tested:**
  (1) **over-match** — bounded equality, `"Other"` ≠ `"Other assets"`/`"…liabilities"`; (2) **maturity never
  stripped** — `"Contract costs"` does not strip-match `"Contract costs — non-current"` → stays unresolved, never
  silently mapped to the nc/c side; (3) **ambiguity → unresolved** — a strip-collision builds a multi-element
  `matches` and routes through the inherited disambiguation to `None` (never a guessed pick). Plus a **B2c
  AI-coverage assertion** — the slice's strip does NOT catch B2c's foreign labels, so the live-AI fallback stays
  exercised (it just fires less often).
- **Regression — purely additive via the Layer-0 short-circuit:** every existing TB resolves at Layer 0; Layer 1
  fires only on a miss → existing mappings byte-identical, B2c unchanged. **33 suites green.**
- **No-key AlJazira re-run (deterministic, no model):** investments maps via `resolve_row`→L2 `"Investments"`→Layer 1
  → `bs_investments` AND nests (S5a anchor) AND ties **36,710,809**; financing maps via Layer 1 (`"Loans /
  financing"`→`…, net`, **100,571,324**); deposits via Layer 0 (**109,644,328**). **Honest finding:** **cash did NOT
  map deterministically** — its TB level is `"Cash and balances with SAMA"`, a genuine SYNONYM ("SAMA" replaces
  "the central bank"), **not** a parenthetical/`, net` variant — so Layer 1 correctly leaves it for the live AI
  (S5b), which *validates* the over-match guard (a near-miss synonym is not force-mapped). So 3 of 4 map free; cash
  remains an AI case. Tests: `test_tb_ingest.py` (suffix-map, the three negatives, ambiguity→None, B2c-coverage).

### 2026-06-21 — Slice S5a: deterministic suffix-strip anchor (Layer 1) for the static breakdown
A reversed AlJazira bank TB ran end-to-end; the two-tier investments note rendered FLAT because
`derive_breakdown`'s anchor required the concept's canonical to appear verbatim in the level path, and the TB's
L2 was the short `"Investments"` vs canonical `"Investments, net"` → `idx=None` → no tiers → identity + leaf-label
merge. S5a makes the anchor LAYERED (no model, no gate):
- **`notes.py:derive_breakdown`** — **Layer 0** (today, UNCHANGED): exact `_norm_lbl(v) in names` — every existing
  note resolves here. **Layer 1** (new): on a Layer-0 miss, retry exact-match after `_strip_qual` on both sides.
- **`notes.py:_strip_qual`** strips a GENERIC set of trailing presentation qualifiers — a trailing parenthetical
  and `, net`/`, gross` — then compares for EQUALITY (not containment). Catches `"Investments"→"Investments, net"`,
  `"Loans / financing"→"…, net"`, `"Cash and balances…"→"…(SAMA)"`. **Does NOT over-match** (`"Other"` stays
  `"other"` ≠ `"other assets"`) and **does NOT strip the maturity suffix** (`— current`/`— non-current`, which
  disambiguates a pair). Anti-hardcoded: a fixed generic rule, no concept/AlJazira literal, no curated alias list.
- **Regression — purely additive via the Layer-0 short-circuit:** Layer 1 fires only on a Layer-0 miss, which never
  happens for telecom (levels == canonical today). `test_static_breakdown_nested.py::test_frozen_replay_…`
  (telecom + bank) stays **byte-identical**; no model is ever called.
- **Proof on the reversed AlJazira TB:** with the leaves mapped, the investments note now **NESTS** — tier-1
  classification subtotals (Held at FVIS 1,623,192 / FVOCI 13,813,923 / Amortised cost 21,273,694), tier-2
  Domestic/International sub-subtotals, contra allowances netting per class by sign, "Mutual funds" no longer merged
  across types — tying to **36,710,809**. (Honest scope note: `resolve.py:resolve_concept` also uses exact-match, so
  the leaves still need the live AI to *map* to `bs_investments` in a no-mapping-column TB — S5a fixes the *anchor*,
  not the *mapping*; the AI-anchor layer S5b and a resolve-side strip are separate, later steps.) New tests:
  `_strip_qual` safety (suffix match, over-match negative, maturity-survives), Layer-1 short-form nesting, and
  short-form == full-canonical identity. **33 suites green.**

### 2026-06-18 — Slice S4: two-tier (nested) static breakdown + nested partition firewall
Extends the static-breakdown mechanism from ONE tier level to TWO (classification → type → leaf) — the
prerequisite for the AlJazira investments note to render as-published. Mechanism-only (the reversed TB follows).
- **2-deep grouping + per-level collapse (`notes.py:derive_breakdown`):** groups by `(below[0], below[1])` into a
  RECURSIVE node (`{tier, children, lines}`, depth capped at 2; `below[2:]` flattens into the leaf). The S3a
  single-leaf collapse applies at EACH level (bottom-up): a tier-2 with one leaf collapses into its tier-1; a
  tier-1 with one leaf collapses to `tier=None`. Source labels at every level (`client_label`, never AI-renamed);
  contra nets by sign-summation at any level; AI/identity paths stay one-tier. n-level is a future derive-only step.
- **Nested firewall (`notes.py:attach_static_breakdown`):** subtotals computed BOTTOM-UP (never read from input);
  the leaf partition (orphan/doubled) recurses ALL leaf-lines at any depth; a **per-node subtotal == Σ children**
  assertion (`_nested_subtotal_findings`, both years) fires at EVERY internal node → a mid-level mismatch BLOCKS,
  not just top/bottom; grand == concept unchanged. **Honest limit (in code + docs):** this proves the ARITHMETIC
  at every level — it does NOT guarantee semantic tier membership under a confirmed/AI override (a mis-nested leaf
  with its parent still summing right is invisible to arithmetic); the human-confirm owns that, unchanged from one
  tier.
- **Render (`render_model.py:renderable_static` — the ONLY render edit):** recurses the tree — subtotal per
  internal node at `indent=depth`, leaves at `indent=2` (when any tier; the gap at 1 is filled by tier-2), tie on
  the grand total. `_note_page`/`write_note_sheet`/`render_mfs_note` unchanged (they already do indent + bold).
- **The mandatory frozen-replay (the real regression firewall):** every existing static note ALREADY enters the
  tier code (`max(len(below))==2`), so byte-identical rests entirely on the per-level collapse. Captured a
  PRE-change baseline (`tests/fixtures/regression/static_notes_baseline.json`, 17 notes — the telecom static set +
  the bank `_setup` notes + the fixture-path 3-line bank investments) and asserted byte-identical after. Only
  `tc_fin_other_assets_c` is unpopulated on the fixtures (named, excluded). All 17 replay byte-identical.
- **Anti-hardcoding ENFORCED:** structure-driven (level paths), no AlJazira/Mobily literal; `face_split.py`/
  `bs_split.py` already in the grep-clean `ENGINE_FILES` (B2c); `notes.py`/`render_model.py` stay grep-clean.
  `tests/test_static_breakdown_nested.py` (8 cases): two-level foots every level + ties, mid-level Σ-mismatch
  BLOCKs, single-leaf collapse per level, tier-2 contra by sign, both-years per node, degenerate depth-1, and the
  frozen-replay. **33 suites green.**

### 2026-06-18 — Slice B2c: live AI-fallback for BS-split label resolution (the dead param made real)
Verification found B2b's BS-line resolution was deterministic-ONLY — the `client=_real_client()` threaded into
`parse_bs_split` was **dead** (passed, never used); a foreign-labelled BS line just flagged. B2c wires the live
proposer in, behind the unchanged firewalls.
- **Deterministic-first → LIVE-AI-fallback → flag-floor** (`tb_ingest/bs_split.py:parse_bs_split`): a clean
  "… — current/non-current" label still resolves via `resolve_row` with **no model call** (Mobily path unchanged,
  free); a foreign label `resolve_row` can't place is routed to the **live** `propose_account_concepts` (the SAME
  proposer the TB account mapping uses, `fsgen_mfs.py:516`) — labels only, pinned model. The `client` param is now
  **used** (no capability-implying dead param).
- **Decision H — maturity-half restriction:** an AI proposal is accepted ONLY if it lands on a `maturity_pairs()`
  leaf; an off-pair guess is **flagged**, not silently mapped (which would be a no-op the reconcile ignores).
- **Flag-floor re-derived:** a line NEITHER deterministic NOR the live AI can confidently place (or "unsure") →
  `unmapped` (flagged at the gate), **never silently dropped**. With no key → `_real_client()` is `None` → the AI
  never fires → flag-floor catches it (never canned output; `_DemoLLM` stays fence-confined).
- **The firewalls stay in front (unchanged):** the AI proposes only WHICH concept a label maps to; the B2b reconcile
  (`reconcile_face_split`, both-years) still runs on the AMOUNTS afterward — a wrong AI concept-guess that doesn't
  reconcile **flags** (branch 2), never silently applies. The gate surfaces `⚙ AI-proposed: <label> → <concept>`;
  the human confirms; unconfirmed stays `not_final`. Balance guardrail and `stored["tb"]`-untouched unchanged.
- **Anti-hardcoding ENFORCED:** `tb_ingest/bs_split.py` and `master_fs/face_split.py` added to the grep-clean
  `ENGINE_FILES` (`test_engine_files_grep_clean`) — the no-Mobily-literal guarantee on the two newest modules is now
  checked every run, not by inspection (forced a rename of `bs_*` locals in `face_split.py` off the seed's `bs_`
  namespace). Provable on a non-Mobily BS sheet with foreign labels (the live AI proposes; the human confirms).
- **Closed the two B2b test gaps:** a **frozen-replay** (`tests/fixtures/regression/mobily_nobs_face.json`) asserts
  the TB-only/no-BS face is byte-identical; a **unit-mismatch** test (a ×1000 BS sheet → branch 2 flag, never
  silently scaled). `tests/test_bs_split.py` now 23 cases: foreign-label live fallback FIRES (fake proposer +
  live-if-key), deterministic resolves with NO model call (a client that raises if touched), AI-unsure/off-pair →
  flag, reconcile-still-gates an AI-proposed mapping, frozen-replay, unit-mismatch. **32 suites green.**

### 2026-06-18 — Slice B2b: read the balance-sheet split so the face ties to the published statement
The B2a "split undetermined" flag becomes a real, reconciled split — when the workbook carries a balance-sheet
face sheet with the current/non-current breakdown the coarse TB lumps. **Approach B (inject with reconcile):**
`stored["tb"]` is **never mutated** (it stays the reconcile anchor); the split is read into a provenanced
`stored["face_split"]`, reconciled, and applied as an **override layer**.
- **The reconcile firewall (load-bearing).** `master_fs/face_split.py:reconcile_face_split` (pure, 4-branch, over
  `maturity_pairs()`): (1) BS split present AND `nc+c == TB lumped total` in **BOTH** years → APPLY (balance-neutral,
  Σ == the anchor it replaces); (2) disagrees (either year off) → KEEP lumped + flag `split_undetermined` + a
  `maturity:` finding — **no half-apply** (one year tying doesn't apply that year and lump the other); (3) **no TB
  anchor** (concept absent from the TB) → INJECT but mark `uncorroborated` + a `face_only:` finding, **and** the
  balance check re-runs on the post-override totals so a BS-only injection that unbalances the SOFP is flagged loud
  (never auto-corrected); (4) no BS split → unchanged flag-don't-lump (B2a).
- **The override seam (one map, both consumers).** `render.py:apply_split_override` + `render_comparative(...,
  split_override=…)` layer the reconciled split over the lumped leaf amounts for the **face**; the same map is
  applied to `cur_leaf` for the **flag** — so face and `split_undetermined` can never diverge. `build_master_fs_export`
  computes the reconcile early and threads it; `MfsLine.uncorroborated` renders a loud "BS-ONLY · NOT RECONCILED"
  marker (PDF/Excel/screen), never green, never reading as tied.
- **Reading the second sheet (read-early / resolve-late).** `tb_ingest/grid.py:best_bs_sheet` (SCORED name heuristic,
  no `"BS"` literal, excludes the picked TB sheet) proposes the BS sheet; a `fsgen_mfs.py` U4 step reads it with a
  second `load_grid` + the **reused** column-role confirm; `tb_ingest/bs_split.py:parse_bs_split` resolves each BS row
  to a `_nc`/`_c` concept via the **existing** `resolve_concept` suffix routing (an unmapped line FLAGS, never
  mis-assigned). The resolve + reconcile run after G2 (they need the seed + mapping).
- **The visible-reconcile confirm gate.** Between G2 and the agenda gate (upload only): shows ✓ reconciled / ✗
  disagree (shown unsplit) / ⚠ BS-only (no anchor) per pair + unmapped lines, so the human sees the **check result**
  before applying. Confirm → applied; read-but-unconfirmed → `not_final` + a `face_split:pending` finding, not applied.
- **Anti-hardcoding / no-regression.** No Mobily literal (sheet name, BS layout, or concept label) — proven on a
  non-Mobily multi-sheet workbook with an amount-first layout. The grep-clean discipline forced a rename off the
  `bs_` prefix (the structure seed's concept namespace) → `face_split` / `uncorroborated` vocabulary in the engine.
  TB-only upload (no BS sheet) is byte-identical (B2a stands). **Riyal-tie proven** through the engine: contract
  costs 4,278 / 359,940; contract assets 89,959 / 1,003,495; financial-and-other-assets 304,722 / 696,921 — each
  reconciling to its TB lumped total, `split_undetermined` cleared, balance-neutral. `tests/test_bs_split.py`
  (16 cases incl. the pure 4-branch firewall, the both-years guard, reconcile-fail, no-anchor + balance guardrail,
  pending, and the bytes-path multi-sheet read). **32 suites green.**

### 2026-06-17 — Slice E1: export polish (PDF + Excel) — year labels, bracket negatives, reorder, dedupe
Reported as three asks on the generated FS; recon overturned the premise of the first one.
- **PREMISE-OVERTURN (#1 two-year notes).** The PDF/Excel notes ALREADY carried both years (verified on a real
  `TB_Test.xlsx` run — Cash 1,399,542 / 1,641,306); the gap was a **generic "Current/Prior" label**, not a
  missing column. The on-screen GUI render is single-year, but per the locked scope the **app screen is left
  untouched** — PDF + Excel only. So #1 became the year-label fix.
- **REAL YEAR LABELS.** The TB's own period header (e.g. `31 Dec 2024 (SAR 000s)`) is captured at parse
  (`tb_ingest/parse.py` → `ParsedTB.period_current/period_prior`, from the header cells at the current/prior
  column indices), threaded `fsgen_mfs` (`ss.mfs_period`) → `build_master_fs_export(period_current/period_prior)`
  → PDF `_note_page` + Excel `write_note_sheet`. Used **verbatim** (source-faithful, no rename) and **without**
  re-appending the unit (so no doubled `(SAR)`); the generic "Current/Prior (unit)" stays the fallback. The
  fixture path passes `None` → fallback unchanged.
- **BRACKET NEGATIVES `(1,234)`.** PDF: one `_acct(value, decimals)` helper — negative → `(…)`, `None` → em
  dash — at faces (0dp) and notes (2dp). **Excel stays NUMERIC (GUARD 2):** the cell holds the real negative
  number and a `number_format` (`#,##0;(#,##0)` faces / `#,##0.00;(#,##0.00)` notes) paints the brackets — never
  a `"(200)"` string, so footing/summability survive.
- **REORDER (PDF only).** The AI's working — proposed extensions, *Mappings applied*, *Open findings* — moved to
  **after** the per-note pages (was between faces and notes). New order: faces → notes → mappings → findings.
- **DEDUPE dual-declared notes (GUARD 1).** PP&E/intangibles/ROU (declared `roll_forward` + `static_breakdown`)
  rendered **twice**; `_build_note_views` now skips an already-seen concept. The surviving view is the BUILT one
  because `note_results[key]` already reflects the S3b **GL-presence pick** — proven both ways: the **bank** (GL)
  keeps its **roll-forward** movement (Opening row present), the **telecom** (TB-only) keeps the **static**
  composition. Dedupe drops no real note.
- **Proof:** real `TB_Test.xlsx` → 12 note views (was 15, dups gone), columns read `31 Dec 2024 … / 31 Dec 2023 …`,
  Acc-Dep prints `(564,681.00)` in PDF and a numeric `-564681` with bracket format in Excel, mappings/findings on
  pages after the notes. `tests/test_export_polish.py` (6 guards) + `test_bank_notes_demo` green; faces unchanged
  but for the bracket formatting; engine/firewall, on-screen render, and legacy GL-path renderers untouched.
  **31 suites green.**

### 2026-06-17 — Slice S3c: the AI SURVEY proposes the note agenda; the engine PROVES every number
The philosophy made concrete: *the AI proposes the agenda, the engine proves each item, the human confirms*
— maximum AI usefulness, zero AI authority over truth.
- **THE NO-MAGNITUDE BOUNDARY (the load-bearing guard).** `mapping.py:agenda_payload` builds one survey object
  per populated leaf concept: `{concept_id, label, leaf_count, leaves:[{label, sign}], levels:[tier labels]}`.
  The `sign` is a **flag** (`"+"`/`"-"` from the amount's sign) — **an amount is NEVER included**. The test
  `test_agenda_payload_carries_no_magnitude_enforced_every_run` STRUCTURALLY walks the constructed payload and
  raises if **any** float (or any int outside `leaf_count`) appears — not a one-time prompt scan, a structural
  assertion that fires every run. The model sees labels + structure + sign-flags ONLY.
- **THE PROPOSER (live, off the build path).** `mapping.py:propose_note_agenda(payload, client=None)` runs the
  LIVE `LLMClient` (pinned `_AGENDA_SYSTEM`: *"you NEVER compute, sum, or invent a figure"*) and returns
  `{buildable:[ids], not_buildable:[{concept_id, reason}], semantic_material:{id:bool}}`. The wrapper
  **sanitises** returned ids to the payload's ids — a hallucinated concept is dropped (proven by
  `test_proposer_sanitises_output_to_payload_ids`, a one-off `_Fake`, NOT `_DemoLLM`). The survey lives only in
  `mapping.py` (defn) + the `fsgen_mfs.py` gate — `notes.py`/`master_fs_export.py` never import it, and the
  deterministic build derives `client=None`, so **the AI is not on the build path** (grep-verified).
- **THE FIREWALL IS UNCHANGED — the agenda only names what to ATTEMPT.** `build_declared_notes(…, agenda=…)`:
  `None` → the **seed floor** (every seed-declared static note builds, as before); a confirmed agenda
  **supersedes** the floor (only the listed concepts are attempted). Each attempted concept still runs the S2
  both-columns partition firewall: a footing agenda concept → **BUILT** with the engine's OWN sum from the TB;
  a non-footing one → **BLOCKED** ("proposed but does not reconcile"); a hallucinated id → **not generated**
  (nothing to sum). The dual-mechanism GL-presence pick survives the agenda (a GL'd `bs_ppe` still builds the
  roll-forward MOVEMENT, not a static composition) — exactly one branch writes.
- **GUI agenda gate (`fsgen_mfs.py`, the `S` gate between G2-map and C1-close, upload path only).** Runs the
  live survey if a real client is present (else falls to the seed floor); shows the **AI map** (semantic-material
  flag + a code-computed **quantitative materiality %** = note total ÷ statement-coverage total) **next to the
  engine verdict per note**, ordered by (semantic, %). Neither the % nor the semantic flag gates correctness —
  they only ORDER the display; the firewall alone decides BUILT/BLOCKED. Confirm → `mfs_stored["agenda"]` feeds
  C2. Smoke-proven headless (gate renders AI-map-next-to-verdict, not_buildable reasons shown, confirm flows the
  agenda into the store).
- **Tests:** `tests/test_note_agenda.py` — the enforced no-magnitude payload walk, the deterministic firewall
  exercised with hand-written agendas (footing → BUILT, non-footing → BLOCKED, hallucinated → not generated),
  the seed-floor↔agenda reconciliation (None → floor, agenda supersedes, one-writes), the dual-mechanism survival,
  the wrapper sanitisation, and a live-if-key proposer (skipped without a key). 30 suites green; faces unchanged.

### 2026-06-17 — Slice S3b: two-layer static notes (PP&E/intangibles/ROU) + prior-year comparatives
Two separated threads, deterministic (no AI — survey is S3c), each with its own proof.
- **THREAD 1 — two-layer static, riding S2.** PP&E/intangibles/ROU carry per class a cost leaf (+) and an
  accumulated-depreciation leaf (−); the **class-tier subtotal IS NBV-by-class** and the total foots to the
  face NBV (18,851,032), purely via S2's tiered partition over signed leaves — **not** `build_movement_note`
  (the TB has no movement). Cost/contra is summation by sign, no `"Acc Dep -"` literal. A non-depreciated
  class (CWIP, Goodwill) has a **zero** acc-dep row the parse skips → single-account tier → the S3a collapse
  renders it flat — **no exempt-class code**.
  - **Dual-mechanism:** PP&E/intangibles/ROU now declare BOTH `roll_forward` and `static_breakdown`;
    `notes.py:build_declared_notes` picks by **GL presence** — the static branch's one new guard
    `if gl and gl.get(concept): continue` (GL → the `roll_forward` branch builds the movement; none → the
    static composition). Keyed by concept → exactly one branch writes.
  - **OMIT-DON'T-ZERO:** the static note shows closing balances only + a caveat *"closing balances only — the
    cost/accumulated-depreciation MOVEMENT (opening → … → closing) needs a GL and is not generated"* — **no
    zero movement rows** (`attach_static_breakdown(movement_pending=…)` → `renderable_static`).
  - **REGRESSION PROOF (the load-bearing one):** the bank `bs_ppe`/`bs_goodwill` `roll_forward` output is
    captured to `tests/fixtures/regression/bank_rollforward_baseline.json` **before** the edit and **replayed
    byte-identical** after — the working GL path proven untouched by replay, not just "tests pass" (the bank
    is dual-declared, so the GL-presence pick is genuinely exercised). `test_bank_notes_demo` stays green.
- **THREAD 2 — prior-year comparatives (all static note types).** The TB carries 2024 + 2023; every static
  note now shows **current | prior**. `attach_static_breakdown(prior_amounts=…)` sums each line/tier/total
  over both years; `RenderRow` gained optional prior fields (movement/split notes unaffected);
  `renderable_static` / `write_note_sheet` / `_note_page` render the prior column, withheld on the same R11
  rule.
  - **BOTH-COLUMNS FIREWALL:** `Σ current == leaf_amounts(cur)[concept]` AND `Σ prior == leaf_amounts(pri)`,
    each independently — either fails → BLOCKED. The prior column is **not a passenger**: dropping a leaf that
    is zero-current but nonzero-prior (current would still foot at 0) BLOCKS on the partition guard. A TB with
    **no** prior period → prior 0 == prior face 0, **no false block**, the column withheld (no phantom year).
  - Proven: Mobily PP&E prior NBV **19,011,971**, AR prior net **3,390,534**, each footing to the prior face.
- **Anti-hardcoding:** sign+level not literals; structure-only seed declarations; a **non-Mobily two-layer**
  with a **sign-only** contra (no contra word) → NBV-by-class foots. Faces byte-identical; S2/S3a notes gained
  only the prior column; grep-clean. 29 suites green.

### 2026-06-17 — Slice S3a: plain + contra static notes (pure S2 reuse, deterministic, no AI)
Built the static BS notes the Mobily TB supports that ride the existing S2 partition mechanism, with one
small structure-driven change. First of S3a → S3b (two-layer) → S3c (AI survey).
- **Contra rides the partition with ZERO special code.** A receivables/inventories/contract-assets note is
  gross + a NEGATIVE allowance leaf; `render.py:_amounts_by_concept` already sums it, so
  `leaf_amounts[tc_accounts_receivable]` is the **net** (3,929,559), and the partition firewall
  (`Σ components == leaf_amounts[concept]`) foots the net automatically by summation. **No contra branch, no
  allowance identification, no `"Less:"`/`"Acc Dep"` literal anywhere** — the netting is arithmetic and
  sign-driven, so a differently-labelled or sign-only contra works identically.
- **Single-leaf-tier collapse** (`master_fs/notes.py:derive_breakdown`, the one net-new change): a tier
  holding ONE account is not a real grouping (the concept name repeating at L2/L3 in a contra/plain note) →
  render it FLAT (`tier=None`). A **leaf-COUNT rule** (`len(accounts) > 1` keeps the tier), **never** a label
  rule — so Accounts receivable renders as two flat lines netting, while S2's genuine multi-account class
  tiers (financial-and-other-assets, 5 + 4 leaves) and PP&E's classes (S3b) are untouched.
- **Six structure-only seed declarations** (`seeds/master_fs_telecom_seed.json`): `static_breakdown` on
  `tc_cash`, `tc_contract_costs_nc`, `tc_due_from_rp`, `tc_accounts_receivable`, `tc_inventories`,
  `tc_contract_assets_nc` — capability + caption only, no leaf/class names. (S3c will let the AI *propose*
  these; S3a declares them so the slice is deterministic/headless — the firewall floor, not the only path.)
- **B2a + S3a coexistence proven** (not asserted): `tc_contract_costs_nc` / `tc_contract_assets_nc` are both
  B2a `split_undetermined` (the TB couldn't split nc/c) AND S3a breakdown concepts. The same face line shows
  the **SPLIT UNDETERMINED** marker **and** a **BUILT** breakdown footing to the lumped concept value —
  orthogonal (nc/c split across concepts vs composition within one), neither corrupting the other.
- **Anti-hardcoding proven on a non-Mobily synthetic** (`tests/test_static_breakdown.py`): different concept
  names + an `"Accumulated depreciation"` contra + a **sign-only** contra (a negative leaf with no contra
  word) — both net and foot, proving nothing keys on Mobily's literals.
- **Proven through the app:** the Mobily TB → Cash / Contract costs / Due-from-related-parties / Accounts
  receivable / Inventories / Contract assets all render **BUILT** (netting where contra), each tied to its
  face value, alongside the financial-and-other-assets two-tier. PP&E/intangibles/ROU stay "not generated"
  (S3b). Foot→BUILT / non-foot→BLOCKED firewall kept; faces byte-identical; S2 two-tier unchanged; 29 suites
  green.

### 2026-06-16 — Slice B2a: make the current/non-current split HONEST (flag-don't-lump)
Three telecom concepts (contract costs, contract assets, financial-&-other assets) rendered the **whole**
amount as non-current with the current side empty — a clean-footing WRONG split. Root cause (recon): the TB
`Mapping` sheet tags every one of those rows `L1="Non-Current Assets"` — **the split is genuinely not in the
TB** (it lives in Mobily's BS/Note 12-13); `resolve_concept` faithfully routed all to `_nc`. This slice makes
that **truthful, not tied** (tying to the published 304,722/696,921 is the named next slice — the data isn't
in this TB).
- **`MasterStructureStore.maturity_pairs()` (derived, gated on `current_non_current_split`):** a clean pair =
  one `… — non-current` leaf + one `… — current` leaf sharing a base; orphan/same-side/>2 → **ambiguous,
  surfaced** (never silently paired). Telecom → 7 clean pairs, 0 ambiguous; the bank (liquidity-presented) →
  no-op. Zero seed churn.
- **Build-time one-sided guard** (`reporting/master_fs_export.py`, alongside orphan/balance guards): for each
  pair, if only ONE side carries leaf amounts → a finding *"current/non-current split not determinable from
  this trial balance — disclosed in the BS/notes, not the TB"* + the face line marked `split_undetermined`.
  **Detection is ARITHMETIC** (does the other side carry an amount?); **money/totals/SOFP balance untouched**
  (total assets stays 38,515,028; no new balance-check finding). `not_final` follows. The four genuine
  two-sided liability pairs (borrowings, lease, contract, financial-&-other liabilities) are **not flagged**.
- **Killed the latent blank-hint silent default** (`tb_ingest/resolve.py`): the split tie-break now picks a
  side only on a genuine maturity signal ("current" in the hint — which both "Current …" and "Non-Current …"
  carry); a blank/ambiguous hint → `None` (undetermined), never a silent default to current.
- **AI-fallback pairing (demoted, hierarchy):** deterministic alias/base match first; when it can't cleanly
  pair, `mapping.py:propose_maturity_pairing` proposes the nc/c pairing **from labels only** (no amounts,
  pinned), a human confirms (C3 gate; AI_ASSUMED/not_final until confirmed), and a flag-floor catches the case
  the AI can't pair. The AI never reaches the deterministic build path (grep-clean); for Mobily it never runs
  (the deterministic match is clean).
- **Face marker** rendered like `ai_assumed`/`judgment_only` across screen, PDF, and Excel:
  *"SPLIT UNDETERMINED — total shown per the TB; breakdown is in the notes."* The total + comparatives are
  intact; only the split presentation + the finding change.
- **Proven** (`tests/test_maturity_split.py`, `tests/test_fsgen_mfs_app.py`): the three Mobily asset pairs flag
  + 3 findings (no AI runs — deterministic); the four liability pairs are unflagged; blank hint → None;
  ambiguous pairing surfaced; AI-fallback proposes + validates + flag-floor; an unconfirmed ambiguous pair is
  flagged while a confirmed one is honoured; total assets 38,515,028 unchanged, balance findings empty. 29
  suites green; faces total + static/roll-forward/split + bank (no-op) unchanged.
- **Cleared by the recon (stated, not fixed):** the "wrong mappings" (telecom-network-equipment → RoU,
  land-&-buildings on both PP&E and RoU) are **correct** — owned PP&E vs leased right-of-use sets, routed by
  L2 section. No mapping-review tightening here.
- **Named next slice (broad):** tie the face to the published split via multi-sheet ingestion (read the BS
  sheet's nc/c) OR a human maturity-classification confirm gate (reuse the N0.2 split machinery).

### 2026-06-16 — Slice S2: fix Bug 1 (static breakdown rendered BUILT while presentationally wrong)
A generated Mobily note rendered BUILT with **duplicate "Other assets" rows + an AI-invented "Advances"
caption**, footing perfectly — a silent presentation failure. Root cause + fixes:
- **The AI was renaming.** `propose_static_breakdown` took the LLM's caption (`str(c.get("label"))`) as the
  component label — the AI authoring presentation. **Fixed at the root:** the proposer now returns account
  **GROUPINGS ONLY** (no leaf labels ever); a leaf line's label is **always its own TB label**
  (`client_label`), and the builder **ignores any label on the payload** (rename-rejection). A multi-leaf AI
  group may *suggest* a caption, but it lands in C2 as a proposal a **human must confirm** — never auto-applied.
- **The TB already carries the note structure in its level hierarchy.** New `notes.py:derive_breakdown`
  reads it: `L2` concept → `L3` tier → `L4` leaf. Mobily's `Financial and other assets` (one published SOFP
  line spanning Note 13.1 *financial* + 13.2 *other*) now renders **two-tier** — "Financial assets" subtotal +
  its source leaves, "Other assets" subtotal + its source leaves — **the concept is NOT split** (the face
  stays one line, riyal-tied to the published SOFP). This also fixed a real bug: the old flat group-by-label
  **fused the two different-tier "Others"** (119,670 + 138,045 = 257,715) into one nonsense line; tier-scoping
  keeps them separate.
- **Grouping is a HIERARCHY (amendment): deterministic-from-levels first, AI-fallback, identity floor.** When
  the TB carries usable levels → deterministic (no AI). When it doesn't (flat/messy source — the AI's original
  scope) → the AI **proposes the grouping** (account sets only); else identity. The path
  (`levels`/`ai`/`identity`) is **recorded and surfaced in C2** so the human knows whether they're confirming
  source structure or an AI suggestion. The AI never reaches the deterministic build path (grep-clean).
- **Firewalls (both paths):** the partition stays (complete + disjoint, Σ == concept); **same-label-within-a-tier
  MERGES** (lossless); a BUILT note has distinct, source-faithful labels. An **un-accepted grouping** or an
  **unconfirmed AI caption** → `GROUPING_UNCONFIRMED`/not_final, never BUILT — C2 now **validates before it can
  accept** (a confirm that cannot fail is not a confirm).
- **Total shown tied to the face, on the page:** `render_model.py:renderable_static` prints tier subtotals +
  source leaf lines + a grand total **"Total — agrees to <face line> on the <statement>"** plus a caveat
  "Breakdown consolidates to X — the <line> face value." (PDF + Excel). The reader verifies the consolidation
  on the note itself.
- **Proven** (`tests/test_static_breakdown.py`, `tests/test_fsgen_mfs_app.py`): Mobily two-tier deterministic
  (source labels, two "Others" separate, total tied to face, BUILT only after a valid accept); AI-fallback path
  recorded + a payload leaf-rename **overridden** by the TB label + multi-leaf AI caption stays unconfirmed
  until human-confirmed; orphan/double-count → BLOCKED; bank `Investments` one-tier cross-archetype; faces +
  roll-forward + split byte-identical. 28 suites green.
- **Out of scope (next slice — Bug 2):** mapping quality + the current/non-current FACE misclassification
  (generated 1,001,643 non-current vs Mobily's published 304,722 / 696,921 — right total, wrong buckets). The
  Bug-2 test is face values matching the published SOFP to the riyal, not merely "confirmed". Not fixed here.

### 2026-06-16 — Slice S1: static-breakdown note mechanism (the third mechanism; no-GL, re-presents TB balances)
The third reconciliation mechanism: one face concept → N component lines whose amounts are the concept's
EXISTING per-leaf TB amounts, grouped into AI-proposed / human-confirmed component labels. No GL, no
movement — it re-presents what the TB already carries.
- **Partition firewall, NOT a GL recon (the load-bearing correction):** the components must PARTITION the
  concept's mapped leaves — every leaf in exactly one component, none orphaned (would understate), none
  double-counted (would overstate). Complete + disjoint ⇒ Σcomponents == concept BY CONSTRUCTION. This is the
  orphan-leaf-guard shape at note level (`master_fs/notes.py:attach_static_breakdown`), **not**
  `face_tb/routing.py:LineRecon` (whose GL-coverage semantics are meaningless with no GL). An orphan or
  double-count → BLOCKED **at build** (not load — the leaves are per-client TB accounts, can't live in the
  structure-only seed). Belt-and-suspenders: also asserts `total == leaf_amounts[concept]`.
- **AI proposes the GROUPING only, never amounts:** `mapping.py:propose_static_breakdown` (labels-only,
  pinned model) groups the concept's sub-account labels into components; CODE sums the leaf amounts.
  Deterministic base = group-by-identical-label; the LLM may merge/relabel but its output is accepted ONLY
  if it is a valid partition of exactly those accounts; conservative floor = identity (each leaf its own
  line) — never a grouping that doesn't foot, never a BLOCK on grouping.
- **Seed declares mechanism + caption + hints (Option A, per-client grouping):** `engine.notes` static entry
  `{concept, mechanism:"static_breakdown", caption, component_hints:[…]}` (telecom: financial-and-other-assets
  non-current/current; bank: bs_investments). `validate_engine_meta` validates the declaration's
  well-formedness at load (concept is a leaf, caption a non-empty string, hints a list); the PARTITION is the
  build-time firewall. (We deliberately did NOT use seed sub-concepts + load-time partition — it would force
  restructuring both seeds, re-authoring rollups, a face-suppression flag, and a render change; invasive, and
  the component leaves are genuinely per-client.)
- **C2 gate — visible + explicitly accepted (not silent):** the partition guarantees footing but NOT that the
  GROUPING is a meaningful presentation. So the app shows the proposed components (pre-filled, relabel = a
  LABEL edit, never a number); one click accepts. **An un-accepted grouping renders the note `not_final`**
  (`GROUPING_UNCONFIRMED`, amber) — an unreviewed presentation never reads as finished — and BUILT once
  accepted. Non-blocking (the fallback always foots).
- **Rendering:** `render_model.py:renderable_static` → the existing per-note page/sheet path unchanged
  (`write_note_sheet`, `_note_page`), status in WORDS via `status_caption`, colour reinforces. New
  `_build_note_views` branch for the `"static"` result key. `build_master_fs_export(notes_attempted)` now
  builds static breakdowns with NO GL; roll-forward concepts with no GL still render "not generated".
- **Split kept SEPARATE (no hybrid):** in the telecom seed current/non-current is already DISTINCT concepts,
  so a static breakdown attaches PER concept; the N0.2 maturity-split machinery is reused unchanged only for
  the one-total→N-concepts shape (lease liabilities).
- **Proven THROUGH THE APP, both archetypes:** Mobily `Financial and other assets` (upload path) → 8
  components footing to 1,001,643, GROUPING_UNCONFIRMED → BUILT on accept, while PP&E stays "not generated";
  bank `Investments` (fixture path, synthetic TB enriched into FVIS/FVOCI/amortised-cost sub-leaves summing
  to 22,000, hard gate green) → BUILT, 3 components, cross-archetype. Partition-failure BLOCKs (orphan +
  double-count), identity fallback, and the "not generated" boundary all guarded (`tests/test_static_breakdown.py`,
  `tests/test_fsgen_mfs_app.py`). 28 suites green; faces + roll-forward + split + N-series byte-identical.
- **Honest bound:** static breakdowns / pure TB re-presentations ONLY. Roll-forward (needs GL), ageing,
  contra/ECL stay "not generated". AlJazira's static list is honestly short (Q1 interim + synthetic TB) —
  built only where the leaves exist; never fabricated to hit an "all notes" target.

### 2026-06-16 — Slice I1: real TB ingestion (TB-only, single workbook, structure-agnostic) into the engine
An uploaded TB workbook (xlsx **or** csv), of ANY column layout, now flows through the app into the
master-FS engine with **no hand-written glue** — replacing the throwaway `scripts/fsgen_from_tb_test.py`
adapter. Parsing is a NET-NEW confirm-chain front-end (`ai_accountant/tb_ingest/`); everything from
archetype-detection onward is the existing engine, unchanged.
- **The front-end is itself a confirm chain** (`tb_ingest/`): `load_grid` (xlsx/csv → one grid) →
  `columns.py` proposes each column's role (account_code / label / amount_current / amount_prior / level /
  verbatim_mapping) keying off MEANING not position (heuristic-first, pinned-LLM for unfamiliar headers,
  **human confirms every column**) → `parse.py` extracts TWO periods into `ParsedTB` (a row with an amount
  but no account is FLAGGED into `bad_rows`, never dropped) → `sign.py` proposes the TB-presentation sign
  per section and the human CONFIRMS the flips. Then `resolve.py` does PREPARER-first concept resolution
  (a verbatim mapping that exact-matches a seed concept resolves deterministically — disambiguated by
  statement and maturity; AI mapper is the fallback) and a deterministic archetype-from-mapping.
- **G0 seam (`fsgen_mfs.py`):** a source radio (Fixture | Upload TB) — `_g0_upload` runs U1 (upload+parse)
  → U2 (confirm columns) → U3 (confirm sign), lands `(items, tb_rows)` in the existing `ss.mfs_*`, and
  G1→G6 run UNCHANGED on them (the fixture path is byte-identical; `_DemoLLM` stays fixture-only, the real
  `LLMClient` drives uploads — the fence holds).
- **TWO balances-while-wrong firewalls, both confirm-gated (never assumed):**
  - **TB-presentation sign** (`tb_ingest/sign.py`): a raw TB stores liabilities/equity/income as negative
    credits; a wrong whole-side flip BALANCES while inverted (the balance check can't catch it), so the
    human confirm IS the guard. AI proposes credit-negative-by-section, human confirms, code flips.
  - **Retained-close** (`master_fs/close.py`, seed-declared `engine.result_close`): closing the current-year
    result into retained is the one step that BALANCES WHILE WRONG (double-count a post-close TB).
    `detect_close_state` surfaces the evidence (imbalance X vs result Y); the human CONFIRMS pre/post; the
    close runs ONLY on a confirmed pre-close, writing a SINGLE audited synthetic row. "The result" = the
    derived `tc_total_ci` (net profit included once via the carry-leaf; OCI never on a BS equity leaf);
    post/unconfirmed/ambiguous → no close. Secondary catch: wrongly closing a clean post-close TB fails the
    SOFP by exactly the result, surfaced never auto-fixed.
- **Notes honestly absent:** TB-only → `build_master_fs_export(notes_attempted=True)` renders each declared
  roll-forward note as **"not generated — no movement data (TB carries no GL)"**, never fabricated (a TB has
  no opening/additions/disposals/depreciation). Faces-only default stays byte-identical. Static-breakdown
  notes are the next slice.
- **Proven on Abhishek's real `TB_Test.xlsx` THROUGH THE APP** (`tests/test_fsgen_mfs_app.py`): upload →
  confirm columns → confirm sign → detect+confirm pre-close → map (preparer) → confirm → generate → faces
  tie to the published Draft FS (assets 38,515,028; net profit 3,106,848; TCI 3,062,385; retained 11,198,161
  = opening 8,135,776 + result 3,062,385; SOFP balances 0). Plus `test_tb_ingest.py` (structure-agnostic
  across layouts + CSV, two-period, bad_rows surfaced, sign) and `test_tb_close.py` (pre/post detect +
  double-count firewall). 27 suites green; fixture path + fence + GL view unchanged.
- **Out of scope (named, next slices):** static-breakdown TB-only notes; GL movement data + multi-file +
  multi-sheet + streaming/millions-of-rows (built when a real GL exists, to verify on the real thing).

### 2026-06-16 — Slice G1: master-FS confirm chain wired into the GUI (coexisting with the GL view)
The master-FS flow (detect → map → derive → build notes → export) is now reachable from the app — previously
it was script/test-only. Added as a SECOND, clearly-labelled view that COEXISTS with the GL-pipeline
statement view, not a replacement.
- **Coexistence (no-regression):** `fsgen_app.py` gained a 4-line top branch — a sidebar `View` radio
  (default = GL pipeline) and `if view.startswith("Master-FS"): import fsgen_mfs; render; st.stop()`. The
  existing GL body is byte-identical below the branch; `test_fsgen_app.py` (which never touches the radio)
  stays green. ALL new code lives in `fsgen_mfs.py`.
- **Six confirm gates, each a real `st.stop()` human stop:** G0 data (fixtures) → G1 detect + CONFIRM
  archetype (radio with `index=None` — NO default; the ambiguous fixture lands on `unsure` and BLOCKS, a
  confident wrong archetype being the worst outcome) → G2 map PER LINE (✓ confirm / leave AI-assumed /
  override-to-a-concept; NOT a blanket confirm-all — a line left unreviewed stays `AI_ASSUMED`/amber and keeps
  `not_final` True) → G3 unit (every figure WITHHELD until set, R11) → G4 generate + build notes → G5 CONFIRM
  split (renders `JUDGMENT_UNCONFIRMED` until an explicit confirm → `JUDGMENT_CONFIRMED`, the persistent
  marker surviving; building never auto-confirms) → G6 export (PDF/Excel bytes, gated on the unit).
- **GUI calls the engine, authors no number.** It reuses `propose_archetype`/`confirm_archetype`,
  `propose_account_concepts`/`apply_mapping_decisions`, `propose_maturity_split`, `build_master_fs_export`,
  `export_master_fs_*_bytes` — re-implements no gate, adds no arithmetic. `not_final` stays ENGINE-derived
  (from mapping provenance / note status), so skipping a confirm leaves the line amber/not-final ON SCREEN
  and in the downloaded PDF/Excel — the screen can't claim more certainty than the engine assigned. The
  net-new `MfsExport`→Streamlit renderer reads each note's status as a WORD via the SAME
  `render_model.status_caption` the documents use (colour only reinforces), so screen + documents read
  identically. "Type your own" (override) edits a concept LABEL only — there is NO monetary-amount box on
  any reconciling line.
- **`_DemoLLM` — the one new boundary, fenced.** The proposers need an `LLMClient`; for an offline,
  AppTest-drivable demo, `_DemoLLM` returns canned JSON DERIVED FROM the fixture's known concepts, so the
  REAL proposers + the REAL deterministic verdict run unchanged on deterministic input. **It proves the GUI
  drives the engine and the gates hold — NOT that detection/mapping are accurate** (a real LLM on real labels
  is the untested hard part; same honesty as "synthetic ties prove mechanics, not real-data correctness"). An
  on-screen notice + the module docstring say so loudly. The stub is STRUCTURALLY confined: it lives only in
  `fsgen_mfs.py`, cannot be constructed without a `tests/fixtures` demo `_Fixture` (so it can't reach real
  client data), the `ai_accountant` engine package never imports it, and the production proposers default to
  the real `LLMClient` — a test (`test_demo_llm_is_structurally_confined_to_the_demo_module`) proves the fence.
- **Fixtures:** the existing `bank_demo` + a NEW `tests/fixtures/telecom_demo/` (synthetic balanced telecom
  TB + a lease-liabilities split GL that exercises G5 as a Case-B management judgment) + an in-module
  ambiguous (generic-label) fixture for the unsure-block demo.
- **Parked (named):** live multi-file / multi-sheet xlsx ingestion (the parsing + sheet→role-routing slice),
  a real `LLMClient` in the GUI, replacing the GL-pipeline view, new notes, Slice C.
- Proven by `tests/test_fsgen_mfs_app.py` (AppTest: the five auto-accept risks each forcing a human step +
  the fence). 25 suites green; GL view + engine unchanged.

### 2026-06-14 — Synthetic BANK demo: first ksa_bank run with notes (HARD GATE + honest ECL handling)
First time the bank archetype runs with note data through `generate_master_fs`. Created two NEW synthetic
fixtures from scratch — `tests/fixtures/bank_demo/bank_synthetic_tb.json` (a bank TB built on the ksa_bank
face structure) and `…/bank_synthetic_gl.json` (a detailed GL footing exactly to the TB). NOT real data,
NOT AlJazira — invented figures; the document states this up front.
- **HARD GATE first (`scripts/bank_notes_demo.py`):** before producing anything, confirm in code that the
  SOFP BALANCES (assets 113,000 == liab 98,000 + equity 15,000, diff 0) and the P&L is coherent (net income
  2,200 carrying into OCI → total CI 2,440). Aborts on broken data — never generates on a non-balancing TB.
- **Honest ECL handling:** the bank's Loans/financing + ECL note is the contra/ECL variant whose mechanism
  isn't built. New recognised-but-unbuilt mechanism **`contra_ecl`** (added to `validate._MECHANISMS`); a
  face concept may DECLARE it and the engine renders it **"not generated — mechanism 'contra_ecl' not yet
  built"** (never forced through `build_movement_note`, never a fabricated ECL breakdown). The face line
  stays correct from the TB. `build_declared_notes` builds ONLY `roll_forward`; other mechanisms → not
  generated with a mechanism-aware reason.
- **Two BUILT bank notes that foot exactly:** PP&E roll-forward (bs_ppe → NBV 3,000) and a Goodwill & other
  intangibles roll-forward (bs_goodwill → NBV 800, goodwill exempt). A per-note tally (note closing → TB
  line → match) prints Y/Y; the report names the not-generated note.
- **Demo styling (temporary) + honesty:** per-note status softened to a SUBTLE coloured footnote word (no
  bold banner fill) — the status TEXT stays (it carries the honesty). New `MfsExport.disclaimer` renders a
  prominent synthetic-data notice on the faces + PDF intro. `generate_master_fs(disclaimer=…)`.
- Deliverable: `exports/Master_FS_bank_synthetic_demo.{pdf,xlsx}` through the REAL path (ksa_bank archetype),
  faces balanced. 24 suites green (new `test_bank_notes_demo`); faces byte-identical when no notes/disclaimer.

### 2026-06-14 — Slice N2: per-note PDF page + Excel sheet, through the REAL orchestrator path
The engine built note breakdowns but the master-FS export rendered only the faces and said notes were "a
later phase"; worse, `generate_master_fs` never built notes at all. N2 closes both — notes now build
through the orchestrator from a supplied GL and render as their own pages/sheets, honestly.
- **Export rendering (mostly reuse):** `MfsExport` gains `note_results` (raw objects) + `note_views`
  (render-ready). `render_model.renderable()` generalized from PP&E-shaped to the **movement mechanism**
  (duck-typed; reads `contra_closing` + both `cost_movement`/`contra_movement` schedules) so it renders a
  generic `MovementNote` (intangibles) AND the per-layer roll-forward (opening + movement lines → closing),
  not just totals. A new `renderable_split()` adapts the split-result dict (N-concept table + Σ-check). The
  honest status block is REUSED — `excel_writer.write_note_sheet` (now with an optional `status_fill`, the
  note pipeline unchanged) and a PDF `_note_page` mirroring the note-pipeline banner.
- **PP&E voice preserved + byte-identical:** a `contra_label` (generic `"Accumulated contra"` in the
  mechanism; `PPENote` overrides to `"Accumulated depreciation"`) keeps the grep-clean. A **frozen
  `renderable()` PP&E baseline** (captured pre-edit) proves the pre-existing Cost/Accumulated-depreciation/
  NBV/total rows reproduce EXACTLY; the schedule rows are additive.
- **Status LOUD in WORDS, not colour alone (Amendment 1):** a `STATUS_COLOUR` map gives each state a
  distinct colour (BUILT/RECONCILED green, PARTIAL/SPLIT amber, JUDGMENT purple, BLOCKED red, not-generated
  grey) AND `status_caption()` writes the state as text on the page — "PARTIAL — covered subtotal only;
  uncovered: […]", "MANAGEMENT JUDGMENT — no independent verification", "BLOCKED — does not reconcile",
  "not generated — <reason>". Verified by eye on the produced files (colour-blind / B&W safe).
- **"Not generated" page:** every DECLARED note that did not build (no GL / unsupported) gets an explicit
  page/sheet, never silently absent; the face line stays correct. Faces-only run (no GL) → no note views →
  byte-identical to before (disclaimer kept).
- **Minimal orchestrator note-building (Part B):** `generate_master_fs(gl=…)` builds each declared note via
  the existing seam (`build_declared_notes` in `master_fs/notes.py`). Builder/configs are **seed-driven** —
  the note decl names `builder`/`cost_config`/`contra_config`; a `MOVEMENT_CONFIGS` registry +
  `movement_config(name)` in `reference_codes.py` resolves them (engine stays grep-clean, no concept
  literal). **Building ≠ confirming (Amendment 2):** the maturity split builds `JUDGMENT_UNCONFIRMED`
  (not_final) by DEFAULT; `confirm_split` fires ONLY on an explicit fixture confirmation (the fixture stands
  in for the human; the real path has none) — proven by two doc variants (unconfirmed vs confirmed).
- **Bytes wrappers:** `export_master_fs_excel_bytes` / `_pdf_bytes` (for the later GUI download; GUI wiring
  itself out of scope).
- **Deliverable:** `exports/Master_FS_telecom_notes_{unconfirmed,confirmed}.{pdf,xlsx}` produced through the
  REAL `generate_master_fs` path — faces + intangibles (BUILT, amortization schedule), tc_ppe (PARTIAL, P3
  uncovered, loud), lease split (JUDGMENT_UNCONFIRMED → CONFIRMED across the two variants, marker persists),
  tc_rou ("not generated"). 23 suites green; PP&E note-object + renderable replays byte-identical;
  grep-clean holds; note pipeline untouched. **OUT OF SCOPE (named):** multi-file/multi-sheet GL ingestion
  + parsing (sheet→role routing) — recorded in the roadmap as the input shape the parsing/GUI slice owns.

### 2026-06-14 — Slice N1: generic roll-forward builder (PP&E generalized; proven on intangibles)
The PP&E note builder was the only roll-forward in the repo and was PP&E-shaped (caption hardcoded, role
`accumulated_depreciation`, `is_land` exemption). Feeding intangibles through it as-is renders a note
captioned "Property, plant and equipment" and calls amortization "depreciation" — numbers tie but the
labels lie. So the mechanism was extracted ONCE into a generic builder; PP&E now rides it byte-identically,
and intangibles (telecom) is the second note proving reuse.
- **Generic builder `fs_notes/movement_note.py` (NEW):** `build_movement_note(leaves, confirmed, *,
  caption, exempt_classes, cost_config, contra_config, cost_role="cost", contra_role="accumulated_contra",
  …)` → `MovementNote`/`MovementSection` (`cost`/`contra_closing`/`nbv`/`has_contra`/`is_exempt`/
  `missing_contra`). It does ONLY the two-layer roll-forward + reconciliation and **carries NO
  note-specific vocabulary** — caption, the contra's charge name, the exempt class all arrive as
  params/config. New guard `test_movement_builder_carries_no_note_vocab` greps it clean of
  `depreciation`/`amortization`/`Land`/`Property, plant`/`PPE`/`goodwill` (same discipline as the engine
  carrying no archetype literals).
- **Mechanism-level contra role `accumulated_contra`:** the proposer/confirmed-structure/`_PPE_STORE`/N0
  fixtures move `accumulated_depreciation → accumulated_contra` (a grouping-key string — output-identical).
  The SPECIFIC contra (depreciation / amortization / later ECL) lives only in the per-note config caption
  ("Depreciation charge" vs "Amortization charge") and the note caption. `propose_movement_structure`
  recognises BOTH depreciation (tangible) and amortization (intangible) labels and **normalises** them to
  the one role; labels-only, pinned model, unsure-not-forced (`propose_ppe_structure` kept as an alias).
- **Exemption is config, not a class name:** `exempt_classes` param ({land} for PP&E, {goodwill} for
  intangibles — indefinite-life, not amortized); `is_exempt`/`missing_contra` replace `is_land`/
  `missing_depreciation` in the mechanism.
- **PP&E rides it byte-identically:** `build_ppe_note` is now a thin wrapper passing the PP&E caption +
  {land} + depreciation configs, returning a **`PPENote`/`PPEClassSection` adapter** (subclasses exposing
  `accum_dep`/`is_land`/`missing_depreciation`/`total_accum_dep` aliases + PP&E's own provisional-reasons /
  status-line wording) so the note pipeline (`recompute._ppe_note`, `test_ppe_note.py`) is UNCHANGED. PP&E
  keeps its correct "depreciation"/"Land"/"PP&E" voice — now in its config + wrapper, the mechanism's "seed".
- **Sign convention at the mechanism level:** `assert_sign_convention` reads `contra_closing`/`has_contra`,
  keyed on `accumulated_contra` (one contra-negative direction is correct for depreciation, amortization and
  any later contra); `record_sign_convention(accumulated_contra=…)`. Behaviour-preserving — it reads the
  contra AMOUNT, not the word.
- **Seam generalized:** `attach_movement_note(… caption, exempt_classes, cost_config, contra_config)` is the
  generic attach; `attach_ppe_note` is a thin wrapper over the SAME two-pass helper (per-leaf attribution →
  anchor → sign assertion), still building via the PP&E adapter. `note_findings`/the export carry the note's
  own caption. `validate_engine_meta` type-checks optional `caption` (non-empty string) + `exempt_classes`
  (list of strings) and BLOCKs on a bad one.
- **Proven on intangibles (telecom seed `tc_intangibles`):** synthetic GL with Software + Licences (cost +
  accumulated **amortization**) and **Goodwill (cost-only, exempt — the Land analog)**. BUILT + reconciles +
  captioned "Intangible assets" (not PP&E) + goodwill not flagged; failing cases kept — perturbed total →
  BLOCK, internal-tie break surfaced, amortization stored positive → the generic sign assertion BLOCKS.
- **Verification:** **PP&E byte-identical BY REPLAY** — a frozen `ppe_note_baseline.json` (single-leaf +
  both multi-leaf, captured on pre-edit code) replays through the generalized builder byte-for-byte (catches
  what the suite doesn't assert when migrating a shared grouping-key). All N0/N0.1/N0.2 + note-pipeline tests
  pass via the adapter; 22 suites green; grep-clean extended; faces byte-identical. Real-Mobily-Note-8
  (intangibles) verification is a named pending gate.

### 2026-06-14 — Slice N0.2: one note total → N concepts (current/non-current maturity split)
A movement note's ONE closing splits across two concepts (`tc_lease_liab_nc` + `tc_lease_liab_c`). The
split is an **IAS 1 presentation judgment**: the AI **proposes the classification (labels-only)**, **code
computes both halves**, a human **confirms**, **unsure → BLOCK** — the AI never authors the amount.
- **Branch on TB shape (detected, never chosen):** `detect_split_case` — **Case A** (every split concept
  independently populated in the TB) reconciles via **N `LineRecon`s + a Σ-check** (`note total == Σ
  concepts`) AND each computed portion **== the TB's value** (a GL-INDEPENDENT backstop) → `RECONCILED`,
  or **BLOCKED** on disagreement. **Case B** (TB-combined, disclosure-only) has **no backstop** →
  `JUDGMENT_*`, never `RECONCILED`. Statuses: `SPLIT_UNCONFIRMED`→`RECONCILED` (A); `JUDGMENT_UNCONFIRMED`
  →`JUDGMENT_CONFIRMED` (B).
- **Proposer** `propose_maturity_split` (labels-only sibling in `mapping.py`, pinned model, generic IAS 1/
  IFRS 9 frame — no archetype literal): classifies movement lines current/non-current; **weak/no signal →
  unsure → BLOCK** (no 50/50, no proportional default; code never manufactures a split).
- **Un-bypassable confirm gate:** `record_maturity_split` records the classification `AI_ASSUMED` (not an
  amount); `confirm_split` flips `AI_ASSUMED → AI_CONFIRMED`. The firewall is in the ENGINE — an ai_assumed
  split emits a finding so `not_final` is True; it's derived from the record's provenance, not a GUI flag.
- **JUDGMENT_CONFIRMED stays visible on the STATEMENT SURFACE** (the N0.1 lesson): after confirm `not_final`
  clears, but `MfsExport.judgment_markers[concept]` + `MfsLine.judgment_only` carry a PERSISTENT
  marker — the rendered line tags "MANAGEMENT JUDGMENT (split — no independent verification)" (amber) in
  xlsx/pdf. A confirmed judgment and a reconciled line look different to whoever reads the statement.
- **Seed-declared splits:** `engine.notes` gains `{note, mechanism, splits:[{concept, maturity}]}` (telecom
  lease liabilities); `validate_engine_meta` checks each split concept exists + is a leaf and the maturity
  ∈ {current, non_current}, ≥2 distinct. No engine literals (the current/non-current binding is the seed's
  maturity tag, not a section-name check).
- **Proven (Mobily lease liabilities, FY2024):** Case A pass (RECONCILED 2,061,787 / 1,213,068), Case A
  BLOCK (AI ≠ TB), Case B JUDGMENT_CONFIRMED + persistent marker, unsure → BLOCK, the firewall, and the
  bad-split load guard. N0/N0.1 unchanged; 22 suites green, 52 master-FS tests; grep-clean; faces
  byte-identical. **No-backstop honesty recorded:** Case B's human confirm is the sole guard and the status
  is judgment-only forever — it can never borrow Case A's reconciled certainty.

### 2026-06-14 — Slice N0.1: real per-leaf attribution within ONE concept
Closes the N0 known limitation's **within-concept half**. `concept_anchor` no longer spreads the GL note
total proportionally (every leaf "covered"); it now takes **real per-leaf `gl_by_leaf`** so
`LineRecon.covered_leaves`/`uncovered_leaves` are meaningful.
- **GL→specific-leaf hop:** a confirmed `{asset_class → concept-leaf}` attribution (labels-only proposed /
  human-confirmed / stored; the synthetic test supplies it directly). `attach_ppe_note` builds
  `gl_by_leaf = {leaf: Σ nbv over the classes attributed to it}`. **Single-leaf concepts default to
  `{all classes → that leaf}` → PP&E byte-identical to N0** (the six N0 cases unchanged).
- **Structural guard:** the gap is computed on the **covered subtotal**, uncovered leaves excluded from
  BOTH sides — an uncovered leaf can never contribute to a reconciliation, and a PARTIAL note can never
  read as BUILT. **BLOCK** = covered subtotal ≠ GL; **PARTIAL** = reconciles but a leaf is uncovered.
- **PARTIAL is as LOUD as BLOCK:** `note_findings` wires the coverage finding into `MfsExport.findings`
  (conditional — only when a GL runs; `note_results=None` → byte-identical), `not_final` flips True, and
  `MfsExport.note_status[concept]` is queryable (`BUILT`/`PARTIAL`/`BLOCKED`, distinct from a generic "has
  findings"); `MfsExport.notes_complete` is False unless every attached note is BUILT. A statement with a
  PARTIAL note can never present as complete.
- **Proven:** a multi-leaf fixture (1 concept, 3 leaves, GL covers 2) — P3 surfaces uncovered/PARTIAL and
  does NOT pass as a clean aggregate; adding the motor-vehicles class → BUILT; a covered-leaf disagreement
  → BLOCKED. 22 suites green, 46 master-FS tests; grep-clean (incl. `notes.py`); faces byte-identical.
- **Still gated → N0.2:** one note total → N concepts (the current/non-current maturity split). The AI
  PROPOSES the split classification (labels-only), code computes both halves, the note total == Σ-of-N
  check runs, the split is recorded-confirmed-fail-loud (like the sign convention), AI-unsure → BLOCK; the
  AI never authors the split amount (no independent sub-total to catch it). Multi-CONCEPT notes stay gated.

### 2026-06-14 — Slice N0: note-attachment pattern (PP&E) re-anchored to a master concept
First note plugged into the master-FS path: a face concept declares a note, the note is built from a GL,
and it **reconciles to the master concept's value OR BLOCKS**. The existing `fs_notes/ppe.py`
`build_ppe_note` is reused **UNCHANGED** (it takes an injected anchor).
- **Seed-declared notes:** `engine.notes:[{concept, mechanism, anchor}]` on both seeds (`bs_ppe`/`tc_ppe`,
  `roll_forward`). `MasterStructureStore.notes()`/`note_for()`; `validate_engine_meta` fails loud if a
  note's `concept`/`anchor` is absent or not a leaf, or the `mechanism` is unknown. Additive — **faces
  byte-identical**, GATE 0 / fidelity / carry-byte-identity all still hold.
- **Master-FS anchor builder** (`master_fs/notes.py` `concept_anchor`): a `LineRecon` whose target is the
  concept's computed value (`render.leaf_amounts`), `gap = scaled GL-note total − concept value`. The
  `attach_ppe_note` seam calls `build_ppe_note` then anchors to the concept. Contra-by-signal stays in
  `propose_ppe_structure` (labels-only); the builder does arithmetic only.
- **Sign convention — explicit, recorded, fail-loud** (the load-bearing add): `record_sign_convention`
  stores the per-client direction with provenance; `assert_sign_convention` (independent of the anchor)
  BLOCKS when an accumulated-depreciation closing disagrees with the recorded contra direction, and FLAGS
  (magnitude-unverified-on-sign) when no convention is recorded — never assumed, never relying on the
  anchor to catch it.
- **Synthetic GL, 6 cases (2 pass / 4 fail):** Land (cost-only exemption) + Buildings + Plant, total NBV
  6,650 == the concept value. Proven: builds by class + reconciles + Land exempt + sign clean; BLOCKS when
  GL total ≠ concept; surfaces an internal-tie fail; the SIGN assertion BLOCKS even when the anchor is
  fooled; and flags an unrecorded convention. Grep-clean now covers `notes.py`; all 22 suites green.
- **⚠ KNOWN LIMITATION (named, bounded):** the anchor reconciles the GL note **total** to the concept value
  ("whole-concept total-to-total" attribution). A concept fed by MANY TB leaves where only **some** are
  GL-covered can reconcile in aggregate while the per-leaf split is wrong (right on top, wrong underneath).
  The N0 fixture keeps the concept to one/two leaves; **fine-grained GL-class → TB-leaf attribution is a
  NAMED refinement that MUST be resolved before any multi-leaf note** (receivables, contract balances)
  rides this pattern. Recorded here and in `NOTES_PHASE_ROADMAP.md` — bounded, not silently assumed.
- **NAMED PENDING GATE:** real-Mobily-PP&E-GL verification to the riyal against Mobily's published **Note 7**
  (cost / accumulated depreciation / NBV by class, both years), once that GL is generated. This slice's
  pass does NOT depend on it — "synthetic passes" is never "verified." (Alongside Abhishek's telecom
  accounting sign-off.)

### 2026-06-14 — Slice B: archetype detection (propose → human-confirm → fail-loud)
A labels-only pre-step that, given parsed `items=[(code,label)]`, PROPOSES which registered seed the TB
matches; a human CONFIRMS; only a confirmed `seed_id` reaches `generate_master_fs`.
- **`propose_archetype(items, stores, *, client)`** (sibling in `mapping.py`, pinned `gpt-5.1-2025-11-13`,
  labels/codes only): the LLM does **per-label semantic fit** (which chart(s) each label is consistent
  with, + evidence) — **never a confidence number**. `detect.archetype_verdict` (pure, no LLM) then
  computes the score **deterministically**: `score[X] = (# labels fitting EXACTLY chart X) / (# labels)`
  — the discriminating-label fraction (generic/unmatched labels score nobody).
- **Conservative by construction** — a single seed is PROPOSED only on high-top **and** clear-margin
  **and** a weak runner-up; otherwise UNSURE → BLOCK: `below_floor` (matches nothing), `multi_high` (looks
  like several), `near_tie` (ambiguous). "Highest score wins" is NOT the default; unsure is the easy
  landing. Each block proven by a fake-client fixture; live smoke proposes `ksa_bank` (0.64) for bank
  items and `telecom_mobily` (0.58) for telecom items.
- **Confirm reuses the gate:** `confirm_archetype(proposal, chosen_seed_id, …)` REQUIRES an explicit pick
  (no default), logs `AI_CONFIRMED` (proposed) or `preparer_override` (any other registered seed, incl.
  after an unsure block) via the existing `AuditRecord`/`ProvenanceStore`. Detection is a PROPOSAL — never
  auto-confirmed.
- **Orchestrator guard (taken):** `generate_master_fs` now raises on a falsy `seed_id` — `seed_id=None`
  silently defaulting to the bank seed was a live confident-wrong route; closed.
- **Thresholds are CONFIG, not engine literals** — `FLOOR/MARGIN/HIGH_BAR` load from the registry's
  `detect_thresholds` block (current `0.15/0.10/0.30`); `seed.load_detect_thresholds` carries the single
  DOCUMENTED fallback. The verdict path (`detect.py`) never hardcodes the numbers — the grep-clean guard
  now also forbids them there (and `detect.py` joins the archetype-clean engine-file set). All 22 suites
  green; 39 master-FS tests.

> **Calibration honesty — `FLOOR/MARGIN/HIGH_BAR` are PROVISIONAL.** They were calibrated against **N=2
> seeds** (bank + telecom) and limited illustrative/real TBs; they are not yet validated at scale.
> **Re-calibration path:** as real client TBs and a 3rd archetype arrive, re-tune the registry's
> `detect_thresholds` (no engine-code edit) against a labelled set of TB→archetype cases, checking that
> real single-archetype TBs clear the winner bar and mixed/foreign TBs block. **Bias on purpose:** the
> conservatism errs toward MORE unsure verdicts — a human picking the archetype is always safe; a
> confident WRONG archetype is the worst outcome — so when in doubt, lower the winner bar's generosity
> (raise FLOOR/MARGIN, lower HIGH_BAR) rather than the reverse.

### 2026-06-14 — Slice A.1: mapper hardening + carry-leaves (OCI net-income correction, both seeds)
**Root causes (not telecom-specific):** the mapper offered EVERY concept as a candidate (so a TB amount
could land on a computed total), and OCI's net-income line was never populated (Total CI omitted net
income — the bank had this silent bug too: old Total CI = Total OCI).
- **Candidate list = INPUT LEAVES ONLY** (`propose_account_concepts`): no subtotal/total/net or carry-leaf
  is ever offered as a target.
- **Block-don't-absorb** (`apply_mapping_decisions`, `record_preparer_mappings`): a mapping (AI or manual)
  resolving to a computed/carry concept is left OPEN with a finding — never placed on a derived line,
  never dropped.
- **Carry-leaves, seed-declared** (`engine.carry_leaves`: bank `{oci_ni ← pl_net_income}`, telecom
  `{tc_np ← tc_net_profit}`): `derive.apply_carries` populates each carry-leaf from its source total's
  derived value (derive source statement → inject → derive target), deterministic, **no AI, no amounts**.
  `validate_engine_meta` fails loud if a carry `id`/`from` is missing, `id` isn't kind=leaf, or the carry
  graph is cyclic.
- **OCI correction taken for BOTH seeds** (the old Total CI was a silent failure, not a baseline). Proven:
  **Balance Sheet + Income Statement byte-identical**; the **OCI change is EXACTLY the carry** —
  `oci_ni` now renders `== pl_net_income`, Total CI rises by exactly that, no other line moves (bank
  310,000 → 3,440,000; SAAB 300,000 → 1,550,000). Re-froze only the OCI slice of the 4 baselines.
- **Riyal-exact telecom guard:** `tests/fixtures/regression/telecom_mobily_published_fixture.json` (Mobily
  audited FY2024/FY2023) — feed the leaves, carry `tc_np`, assert every printed total to the riyal
  (**Total CI 3,062,385 / 2,149,572**, balance 0, all 18 derived lines, both years).
- **Hardcode hygiene (extended grep-clean, all 7 engine files** — derive/mapping/render/validate/model/
  orchestrator/export): **ZERO** archetype-fact literals (concept_id incl. carry id/from, section name,
  statement key/title, banking vocab). GATE-0 xlsx/CSV reconciliation (which necessarily names the bank
  xlsx's two alias columns) was split into `gate0.py` — it only runs for a seed that ships an approved
  xlsx and is not the runtime path. The pinned model string is the **sole intentional hard literal**
  (see below). Live telecom re-run: Total CI now ties (2,050,000), net-profit-on-total blocked → finding,
  balance 0, provenance still `ai_proposed_unconfirmed`. All 22 suites green; 35 master-FS tests.

> **Why the model pin `gpt-5.1-2025-11-13` is intentionally a HARD literal (do NOT make it configurable).**
> It lives once, in `ai_accountant/config.py` (`OPENAI_MODEL`), as a fully-dated snapshot. A floating alias
> (`gpt-5.1`, `gpt-5.1-latest`) would silently change model behaviour under us — a reproducibility hole:
> the same TB could map differently tomorrow with no code change, and replayed/confirmed mappings could
> drift from what a human reviewed. The dated pin is a framework INVARIANT, deliberately exempt from the
> seed-driven de-hardcoding — a future pass must NOT "helpfully" make it seed/env-driven beyond the existing
> `OPENAI_MODEL` override. (Same exempt category: the sign convention, schema field names, and the
> propose-confirm-store / labels-only contract.)

### 2026-06-14 — Task 1 (component-integrity guard) + Task 2 (telecom seed wired & proven live)
- **Task 1 — closed the silent-zero gap.** `validate_engine_meta` now also checks that every concept's
  `components` entry is a `['+'|'-', existing concept_id]` pair (a bad component id previously contributed
  0 to a subtotal silently). Dangling/invalid component ⇒ raise at load, same discipline as the other
  id checks. Bank seed unchanged (all components valid → still loads, Leg-1 byte-identical); new test
  `test_load_fails_loud_on_dangling_component`.
- **Task 2 — telecom (Mobily) seed, end-to-end, ZERO engine edits beyond Task 1.** Externally authored
  `seeds/master_fs_telecom_seed.json` (`tc_*`, 70 concepts, current/non-current split, IFRS 15/16 lines,
  `provenance_seed = ai_proposed_unconfirmed`) + proposed `Formulas/master_fs_telecom_rollups.json`.
  Registered `telecom_mobily`; `apply_rollups_to_seed --seed-id telecom_mobily` idempotent; `validate_rollups`
  = **consistent (NOT independently confirmed — seed+rollups share one proposal, passes by construction)**;
  GATE 0 **skip-with-notice** (no telecom xlsx). `generate_master_fs(strategy="automap", seed_id="telecom_mobily")`
  ran a **real `gpt-5.1-2025-11-13` mapping call** (labels/codes only, NO amounts in the payload) and
  rendered all three statements — SOFP balances (difference 0), P&L and OCI derive — NOT-FINAL=True
  (every AI mapping `ai_assumed`), **`provenance_seed` left `ai_proposed_unconfirmed` (not relabelled)**.
  `scripts/master_fs_telecom_demo.py`; documents `Master_FS_telecom_mobily.{xlsx,pdf}`.
- **Structure/formula proof (regression guard).** `tests/fixtures/regression/telecom_structure_proof.json`
  (ILLUSTRATIVE balanced dataset, expected values from an INDEPENDENT component-sum) +
  `test_telecom_seed_structure_proof`: all 18 derived lines reproduce + balance == 0. Swap in Mobily's
  published FY2024 figures to make it riyal-exact (not fabricated here).
- **Honest live findings.** The live AI mapped the ambiguous "Net profit for the year" onto the P&L
  net-profit TOTAL (a computed concept), which the orphan guard surfaced (a TB line on a computed line)
  — OCI's carry-leaf stayed empty, Total CI correspondingly understated, **surfaced not hidden**. Latent
  gap for a later slice (the mapping candidate list still includes computed concepts) — NOT fixed here
  (would be an engine edit beyond Task 1). All 22 suites green; 31 master-FS tests.

### 2026-06-14 — Slice A: the master-FS engine is now SEED-DRIVEN (zero engine edits per new seed)
**Goal:** the engine consumes ANY seed purely from that seed's own declarations — adding a seed needs no
engine-code change, no archetype name or seed-specific concept_id literal in engine code, and the bank
output stays **byte-identical**. Done, all four guards hold.
- **Seed self-declaration (`engine` block).** Each seed declares its structural roles: `statements`
  (ordered keys + titles + sections + coverage_totals), `balance_check` (assets/L&E total ids + label/
  short), `memo_leaves`, `default_placement`, `presentation`/`current_non_current_split`, and `prompts`
  (domain / master_desc / entity_noun / mapping_hints / extension_examples). The loader reads it into
  `MasterStructureStore.meta`; `derive.py`, `render.py`, `mapping.py`, `master_fs_export.py` read roles
  from the store — the old literals (`_COVERAGE`, `MEMO_LEAVES`, `balance_difference` ids, `_STATEMENTS`,
  `_STMT_TITLE`, `_CLASS_SECTION`, the banking-vocab prompt) are **gone**.
- **Registry + orchestrator.** `seeds/registry.json` ({id,label,seed_path,rollups_path});
  `load_master_store(seed_id=…)` resolves via it (and `json_path=…` still works for tests). One entry
  point `generate_master_fs(source, *, seed_id, client, period, strategy)` does parse→load→map/record→
  derive→render/export (`seed_id` explicit — the future archetype-detector slot). `apply_rollups_to_seed`
  is now registry-driven, idempotent, and **SKIP-WITH-NOTICE** when a seed has no authored rollups
  ("no rollups" ≠ "fidelity OK"). Stores carry a `master_id`; client mappings are scoped to
  `(master_id, client_id)` (leak-safe — a client spanning masters raises).
- **Guards, all tested.** (1) **Fail-loud at load** — a dangling coverage_total/balance_check/memo id or a
  section that drifts from the concepts raises. (2) **Grep-clean** — no `aljazira|saab`, no `bs_/pl_/oci_`
  concept_id, and none of the six banking terms (Sukuk, Special commission, Tier 1, Murabaha, Financing,
  Customers' deposits) survive in the four engine files. (3) **Byte-identical no-regression** — Leg 1: the
  4 frozen stored results replay to a model byte-identical to the pre-refactor baseline
  (`tests/fixtures/regression/`); Leg 2: the bank prompt assembled from the seed == the original literal
  string; Leg 3: concept data unchanged + GATE 0 + fidelity PASS. (4) **AI/arithmetic boundary** unchanged.
- **Seed-driven PROOF.** A minimal Claude-authored **telecom stub** (`tc_*` ids, `RESOURCES`/`OBLIGATIONS`
  sections) loads via the registry and derives+renders a balanced SOFP with **zero engine edits**; its
  mapping prompt carries the telecom domain and **none** of the banking vocabulary (the hint-swap test).
  Cross-seed id collisions **warn, never fail** (bank `bs_*` vs telecom `tc_*` don't collide).
- **Out (later slices):** archetype DETECTION (B), AI seed GENERATION (C), GUI wiring, the real corporate
  seed/rollups. **All 22 suites green; 27 master-FS tests** (incl. replay, prompt-equality, grep-clean,
  fail-loud, hint-swap, cross-seed warn, master_id scoping).

### 2026-06-13 — PDF pagination: each statement on its own page (layout only)
A statement straddling a page boundary (the Income Statement ran page-1→page-2) made column-first text
extractors scramble copied/pasted text — labels separated from their figures — a **false** "rows came
apart" alarm; the rendered pages were verified correct (rasterized + coordinate-checked, every number on
its label's row). Fix: `export_master_fs_pdf` now emits a `PageBreak` before each statement, so **Balance
Sheet = p1, Income Statement = p2, Comprehensive Income = p3** — none straddles a boundary, extracted text
reads cleanly, and the PDF reads like a real filing (one statement per page). **Layout only** — no derive,
render-logic, arithmetic, or seed change; values/alignment identical (Net income 3,130,000 etc. unchanged).
Regenerated all four sets (AlJazira + SAAB, nomap + premap). All 22 suites green.

### 2026-06-12 — SAAB-vocabulary demo: one master, the second bank's words + its union-only lines
**Goal (Abhishek):** prove the same master/engine handles **SAAB's vocabulary**, not just AlJazira's.
`scripts/master_fs_saab_demo.py` — a representative TB captioned the **SAAB way**, run through the LIVE
`gpt-5.1-2025-11-13` no-mappings path, rendered with **`bank="saab"`** (SAAB's own labels). Illustrative
round numbers (never SAAB's real figures); retained earnings the single balancing figure.
- **Vocabulary mapped LIVE, all [high]** into the SHARED concepts: "Loans and advances, net" → `bs_loans`
  (≠ "Financing"), "Special commission income/expense" → `pl_sci`/`pl_sce`, "Debt securities in issue
  and term loans" → `bs_debt_liab` (≠ "Subordinated Sukuk"), "Due to banks" → `bs_due_to`. ~3 sub-accounts
  roll several-to-one into each concept.
- **Union proof:** the three **SAAB-only** master lines the AlJazira demo left empty are now POPULATED and
  render — **Share premium** (1,500k), **Goodwill and other intangibles, net** as a separate line (800k),
  **Proposed dividends** (800k). All three mapped to their **existing** master concepts (NOT proposed as
  new), confirming the master is a union and each bank renders its own subset.
- **Faces in SAAB's labels** with full presentation completeness: four BS totals, P&L net-lines +
  subtotals + "Net income for the year after Zakat and income tax", OCI two-bucket headings, SAR'000/dates
  — derived totals neutral, AI-mapped leaves amber (`ai_assumed`, unreviewed). **Balances 73,900,000 both
  sides**, both nomap (live AI) and premap, through correct arithmetic (the balancing figure is one line;
  a broken derive would re-open the gap). nomap NOT-FINAL True (ai_assumed); premap NOT-FINAL False.
- One honest live wrinkle, then fixed: GPT first flagged an ambiguous "FVSI investments" caption as unsure
  and proposed a new FVTPL line (a defensible call) — the orphan + balance guards caught the 1,000k gap;
  re-captioned to the clearer "FVOCI equity investments" (which mapped cleanly), so the demo ties.
- Artifacts: `Master_FS_saab_nomap.{xlsx,pdf}`, `Master_FS_saab_premapped.{xlsx,pdf}`,
  `Representative_TB_saab_{nomappings,premapped}.xlsx`. No engine/seed change — all 22 suites remain green.

### 2026-06-11 — Face-statement presentation completeness: derived subtotals/totals/net-lines + 2 guards
**Problem (Abhishek's post-demo feedback):** our faces didn't read like the real AlJazira/SAAB faces —
missing the presentation spine (Total assets/liabilities/equity/L&E, P&L Net-SCI/Total-income/Total-
expenses/Net income, OCI two-bucket sub-headings, SAR'000/date headers). **Diagnosis (confirmed):**
subtotals were **never computed** — `render` summed only mapped TB accounts, a subtotal is never a TB
account, so it stayed empty and the "populated-only" filter dropped it; the seed was a flat list with no
roll-up structure. **Fix = add the derivation**, deterministic, AI-untouched.
- **Authored roll-ups, not AI-authored:** loaded the human-authored signed component formulas from
  `Formulas/master_fs_rollups_authored.json` onto the seed (`scripts/apply_rollups_to_seed.py`): each
  computed concept gets `kind` (leaf|net|subtotal|total) + an explicit signed `components` list. The AI
  still maps **leaves only**; arithmetic is the engine's.
- **Seed schema + GATE-0 reconciliation:** `MasterConcept` gains `kind`/`components`. Added the **four BS
  spine totals** (`bs_total_assets/liabilities/equity/liab_equity`) that weren't in the original approved
  xlsx — **the xlsx spec was updated** to carry them at the foot of each BS section
  (`scripts/add_totals_to_seed_xlsx.py`), same discipline as the dash-drift fix; **GATE 0 re-validates
  JSON↔xlsx↔CSV (PASS)**. A new **authored-formula fidelity check** (`validate_rollups`) proves the seed's
  kind/components equal the authored file (the structure that lives only in JSON).
- **Deterministic derive pass** (`ai_accountant/master_fs/derive.py`): topological (net-lines → subtotals
  → spine totals; a total may reference other totals). Sign convention: TB stores expenses/zakat/tax
  **negative**, net-lines use `+`. Derived lines render **neutral/bold, never amber** (arithmetic, not an
  AI assumption).
- **Render rules** (section-blocked): leaves render iff populated; **spine totals always**; net/subtotal
  iff ≥1 component present; empty intermediates hide. OCI emits the `l1_group` two-bucket sub-headings;
  headers now show **SAR'000** + period-end dates.
- **Two guards** (where silent-wrongness would live): **orphan guard** — every populated leaf must sit in
  a total's **transitive** closure (gross P&L leaves reach Net income *through* the net-lines); orphans are
  **surfaced as findings, never silently excluded**; `pl_eps` is a declared non-summing memo; a build-time
  test asserts **zero orphans** on the canonical seed. **Balance check** — Total assets vs L&E; a mismatch
  is a **non-blocking finding** showing the difference, never auto-corrected (a TB with unmapped suspense
  legitimately won't balance — the difference is signal).
- **`next_order` fix:** new (AI-added) leaves now place among the leaves, **before** the section total
  (the total's 999/1000 sentinel is ignored when picking a slot).
- **Demo regenerated, both sets:** **pre-mapped BALANCES exactly** (124,600,000 = 124,600,000) through
  correct arithmetic — Corporate Murabaha is the single illustrative balancing figure, every other line
  independent, so a broken derive would re-open the gap (no by-construction masking). The **no-mappings
  live run** fired all guards honestly: GPT proposed 2 new face lines (Acceptances, Zakat) → both orphan
  findings (AI-added, no total-membership yet), 2 suspense unmapped, 1 balance finding, NOT-FINAL True.
  Faces now show subtotals, the four BS totals, P&L net-lines + Net income, OCI buckets, SAR'000/dates.
- **All 22 suites green** (18 master-FS, incl. derive/sign, transitive-orphan + zero-orphan-seed, balance
  both-directions, fidelity, OCI buckets). **POST-DEMO follow-up (still parked, slice 10):** the per-line
  human-confirm step also **attaches an AI-added leaf to its section total** (until then the orphan guard
  catches it). Sign-convention is a **real-input question**: a client TB storing expenses POSITIVE flips
  the signs — must be recorded per-client at confirm, never silently assumed.

### 2026-06-11 — Two-TB master-FS demo: live AI-mapped vs preparer-mapped, + live master-extension
- **Two TBs, two input modes** (`scripts/master_fs_demo.py`, ~39 lines each, illustrative round numbers,
  NOT real figures): a **RAW no-mappings TB** → LIVE `gpt-5.1-2025-11-13` mapping; a **PRE-MAPPED TB**
  (carries level/account-type/the master-concept mapping) → **straight-through, NO AI** (deterministic).
  Many accounts roll **several-to-one** into the existing 60 concepts (Cash 3→1, Investments 4→1,
  Loans 3→1, Deposits 3→1). Both produce `Master_FS_nomap.{xlsx,pdf}` and `Master_FS_premapped.{xlsx,pdf}`
  + both TB spreadsheets, replayed from the stored live result (no live call at export time).
- **Live master-EXTENSION demonstrated:** the live run mapped most lines; a second-opinion pass on the
  generic-"Other"/unsure lines had GPT propose **"Zakat and income tax payable" as a NEW master concept**
  (balance_sheet/LIABILITIES, high) → added (provenance `proposed_unconfirmed`) → it **renders on the BS
  tagged NEW**. Acceptances kept in Other; the two suspense/clearing lines → **findings** (not invented).
  The master grew by exactly one genuine line (didn't balloon).
- **Auto-APPLY-as-ai_assumed honesty (the key rule):** the no-mappings run is UNREVIEWED, so **every AI
  mapping is applied (statements populate) but marked `ai_assumed` (UNCONFIRMED)** — none relabelled
  human-confirmed (the laundering the project rejects). So the nomap documents are **mostly amber "AI
  assumption" rows** with the small conditional **NOT-FINAL** footnote firing; the pre-mapped documents
  are **all `preparer`, clean, NOT-FINAL absent**. Green/"confirmed" only ever means a human confirmed.
- **POST-DEMO FOLLOW-UP (recorded, NOT built):** wire the per-line **human-confirm step** that promotes
  `ai_assumed → ai_confirmed` (part of the slice-10 GUI confirm surface). The demo shows "AI mapped
  everything, honestly flagged unconfirmed"; the later build adds "and a human reviews and confirms."
- Line label fix: a rolled-up line shows the **master concept** (its canonical), the client's own
  account captions are preserved in the **provenance view**. **All 22 suites green.**

### 2026-06-11 — Master-FS detailed export (PDF/Excel) + FIRST LIVE gpt-5.1-2025-11-13 mapping
- **First live AI call in the project** (everything prior used fake clients): confirmed key + egress +
  the pinned `gpt-5.1-2025-11-13` respond (reported the path, no silent fallback). A **detailed,
  banking-aware system prompt** (`master_fs/mapping.py` `_MASTER_FS_SYSTEM`, labels-only — Islamic/
  conventional vocabulary, contra-with-its-asset, AT1-sukuk-is-equity, unsure escape) mapped a
  representative bank TB into the master concepts. `propose_master_mappings` (returns FaceMappingProposal
  so it flows through the same confirm/store path); `propose_account_concepts` now uses it.
- **Run-live-once-then-replay:** `scripts/master_fs_live_map.py` made the live call (21 lines), a human
  review confirmed 19, accepted 1 as **AI-assumed** (Salaries → Other G&A, medium), **declined** the
  Sundry-suspense clearing account (flag-don't-force → unmapped → findings), and stored the result to
  `exports/master_fs_live.json`. The export **replays the store** (no live call at demo time, no timeout
  exposure).
- **`reporting/master_fs_export.py`** (reuses the honesty machinery, new content): three face statements
  from the master (populated lines, master order, client labels, **comparative current·prior columns**),
  a **mappings-applied/provenance view**, and a **findings page**. Refinements: **illustrative round
  numbers** (NOT the bank's real figures), **no illustrative banner**, **NOT-FINAL as a small plain
  footnote conditional on real state** (any AI-assumed line / unmapped item), and **comparative-column
  honesty** (a one-period-only line shows its figure where present, a dash where absent — no carry-
  across/zero). AI-assumed renders amber in BOTH the line and the provenance view; note-by-note
  breakdowns shown as a later phase (no placeholder note pages). Artifacts: `exports/Master_FS.xlsx`
  (5 sheets), `exports/Master_FS.pdf` (5 pages). Guard: `test_export_model_is_honest`. **All 22 suites
  green.**

### 2026-06-11 — PHASE 1 BUILT: master FS structure capability (BS / P&L / OCI from a TB vs a shared master)
- **Abhishek's redirect** (precedes slice 10, which stays parked): generate a bank's Balance Sheet,
  Income Statement, and Comprehensive Income from its TB, mapped into a **shared, human-approved master
  structure** (union of Bank AlJazira + Saudi Awwal Bank face lines, liquidity-ordered, 60 concepts).
  The **AI maps INTO it and proposes ADDITIONS — never invents; the master holds STRUCTURE ONLY, never
  an amount.** New package `ai_accountant/master_fs/`. Reuses TB ingestion, signal mapping, the
  propose-confirm-store proposers (pinned `gpt-5.1-2025-11-13`, labels-only), face assembly.
- **GATE 0 (validate the seed before building on it):** `validate.py` reads the approved xlsx (for
  validation only, never runtime data) and diffs the JSON — **0 mismatches** after it caught a real
  **dash-drift** (4 OCI labels: hyphen in JSON vs em-dash in the approved spec) and the JSON+CSV were
  **reconciled to the spec** (logged, not loosened). **Tightening — alias PAIRING:** each
  `both_naming_differs` concept's two labels must be filed under the RIGHT bank (a swap is caught), not
  merely both present. CSV↔JSON also validated (no drift in the flat copy).
- **The capability:** `MasterConcept` store (seeded from the validated JSON, no amount field by design);
  **map-into-seed by signal** (the master canonicals are the candidate vocab; two labels → one
  loans/financing concept) with **conservatism** (an unsure/unfamiliar line → unmapped + flagged, never
  force-mapped); **render only the populated subset** in master order with the client's own labels;
  **comparatives from two same-client TBs** (current + prior columns, one structure); **propose-addition**
  → a new concept with a **coherent placement** (valid section + order, human-confirmed), provenance
  `proposed_confirmed`.
- **Three logically-separate, DB-ready stores, no DB:** (1) global master, (2) per-client confirmed
  mappings **keyed by client (AlJazira's never leak to SAAB)**, (3) provenance/audit (who/what/confidence
  /when). Files/in-memory; DB engine/connections/migrations/concurrency/auth-roles recorded as
  deployment follow-ups, not built. Provenance on every mapping (`preparer` / `ai_confirmed` /
  `ai_assumed`); amounts never sent to the AI; every number deterministic.
- **`tests/test_master_fs.py`** (9 guards) + `scripts/master_fs_check.py`. **All 22 suites green.**
  Coordinates with slice 10: the proposer wiring here is the engine+CLI subset; slice 10's GUI later
  sits over the same stores + provenance/AI-assumed fields. Parked beneath: note modules plug into
  master lines later; generated-vs-published validation; the matcher; independent sign-off.

### 2026-06-10 — Cleanup: legacy Note-5 cascade DELETED + model-pin verified (no proposer-loop build)
- **Why:** the verification of the AI prompts confirmed the four active proposers are **labels-only**
  (no amounts; `DEFAULT_SYSTEM` forbids the model computing/summing), but the **legacy** `routing/
  router.py` sent 2 full sample rows (incl. amount columns) to the model. Not reachable (legacy→legacy
  imports only; active spine imports zero legacy), but a dormant amount-leak that could be revived by a
  stray re-import. Deleted outright → "not reachable" becomes "cannot exist."
- **Removed** (all confirmed legacy→legacy by grep; the active spine imported none of it):
  packages `ai_accountant/{compute,ingestion,notes,policy,routing,validation,export}/`; `ai_accountant/
  ui.py`; root `app.py`, `engine.py`; 11 legacy tests (`test_{cascade,classification,notes,export,
  controls,validation,phase2_complete,hardening,routing,multisource,qa_scenarios}.py`); 12 legacy
  scripts (`run_cascade, qa_suite, make_bundle, make_accuracy_test, make_test_documents,
  verify_l4_provenance, verify_hardening, test_l4_only, test_policy_samples, show_routing, smoke_test,
  extract_policy`); and the dead Note-5 config constants (`SAMPLE_NOTE5_CSV`, `NOTE5_GROUND_TRUTH`,
  `PROFILE_SAMPLE_ROWS`, `LEVELS`). **All 21 remaining (active) suites green; the app + demo export
  still run.**
- **Model pin verified verbatim:** the ONLY model string in the codebase is
  `config.py:24  OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1-2025-11-13")` — the pinned dated
  snapshot. `LLMClient` uses `self.model = model or OPENAI_MODEL`; **no proposer passes a model
  override, no floating `gpt-5.1` alias, no other model anywhere** (all other "GPT-5.1" mentions are
  docstrings/comments). The AI/arithmetic boundary holds at the prompt level (labels-only) and the
  reproducibility pin holds at the model level.
- **AI prompts (verified, not assumed):** all four active proposers (`propose_subcategories`,
  `propose_face_mappings`, `propose_ppe_structure`, `propose_seed_mapping`) send only labels / account
  codes / candidate vocabulary — never amounts. file-kind & region detection are deterministic (no LLM).
- **Still the one next build:** wiring the proposer loop into the GUI (unblocks the no-mappings path,
  the mappings front page, and the AI-answer checkbox with the distinct AI-assumed state). Not built.

### 2026-06-10 — SLICE 9 BUILT: the output layer — BS + P&L as first-class statements (FINALE)
- **The TB-first build is complete.** Presentation finale: a different kind of slice (no number to
  reconcile; risk = misrepresentation). Defining property: **the screen never claims more certainty
  than the engine assigned.**
- **The honesty is a PURE model, tested deterministically** — `ai_accountant/reporting/statement_view.py`
  `build_statement_view` produces a BS/P&L-first `StatementView`: each face line carries its OWN
  `line_status` (BUILT / PARTIAL / BLOCKED / FACE_ONLY / MAGNITUDE_UNVERIFIED), the keystone is a
  SEPARATE claim, BUILT vs face-only are distinct values. The app renders it verbatim, so the
  load-bearing guard isn't Streamlit-flaky. `tests/test_statement_view.py` (8 guards) covers the three
  tightenings: **(a)** status visible at the face line with its question; **(b)** keystone does not mask
  a BLOCKED line (balancing ≠ all reconciled, shown as separate claims); **(c)** reconciled-BUILT
  visibly distinct from face-only; plus **R11** (withheld until unit), **R8** (view mirrors the
  recomputed figure), and **edited-boundary-still-gated** (`parsing.apply_boundary_edit` → unconfirmed,
  a low-confidence edit still needs override — editing changes WHAT the boundary is, not the certainty).
- **`fsgen_app.py` rebuilt around the TB-first flow** (was Phase-5 GL→notes, ships notes alone): TB
  upload → `assemble_face` → BS + P&L as first-class statements with per-line note drill-downs;
  three-case detection (TB-only / TB+GL / GL-only) surfaced honestly; the keystone shown as its own
  claim with a "balancing ≠ all reconciled" warning when a line is BLOCKED; figures withheld until the
  unit is set; questions recompute (R8 — `facetb` threaded into `recompute()`, slice-8). Salvaged: the
  status-chip vocabulary, `renderable`, R11/R8 plumbing. `renderable()` extended for the PP&E note
  (two-layer cost/dep → NBV). `tests/test_fsgen_app.py` (AppTest) rewritten for the new flow.
- **All 32 suites green.** The TB-first build is done — parse (guarded front-end) → face (BS + P&L) →
  anchored reconciled notes → an honest presentation. **Only two threads remain, both external/parked:**
  the matcher (Bucket B, needs the renumbering-vs-different answer) and independent keystone sign-off
  (finance's own non-derived TB).

### 2026-06-10 — SLICE 8 BUILT: GL path made first-class (region detection + recompile anchor)
- **Pre-check (literals discipline, like slice 7's no-regression):** grepped the engine for the
  held-out amounts (`59130178` / `774572767` / `833702945`) — **clean**; all six files carrying them
  are tests (expected-answer pins). The held-out gap must be COMPUTED from uploaded data, never a
  literal on the runtime path. Confirmed before building.
- **Part A — GL ingestion routed through the slice-4 parsing front-end.** `gl/ingest.py`
  `ingest_workbook` now uses `propose_regions(kind="GL")` + `confirm_region` instead of
  `gl/regions.detect_regions` (region=sheet v1). Added a **GL-aware row classifier** to
  `parsing/detect.py` (`_classify_gl_row`, carrying R14: a posting stands on a gl_account / a
  transactional id; an amount-only row is a footer/control total) and factored the shared span/
  confidence logic into `_assemble_region` (kind-agnostic; TB behaviour unchanged). For GL the
  boundary **finds the real header (skipping a title/preamble block) + gates on confidence**; the row
  disposition below the header (footers→control totals, orphans, continuations, column-shifts) stays
  with `_region_to_postings`'s R14 **unchanged** → clean GLs ingest **byte-identical** (the three real
  GLs unmoved; proven by every existing suite still passing). **New guard**
  (`tests/test_gl_messy_region.py`): a title block above the header → header found below it, data
  extracted (region=sheet would fail); footer → control total; an interior subtotal →
  `region_needs_review`, NOT extracted (R24 confirm-gate has teeth). Fixed mid-build: the
  side-by-side-table heuristic false-fired on wide SAP GLs → rebased on the header's width + a
  substantial-share threshold (not one stray cell, not the resolved-column extent).
- **Part B — FaceTB anchor threaded through `recompute()`.** `recompute(..., facetb=...)` +
  `_note_anchor` route each note's account closings to the TB line (slice-5 contract reaches the R8
  loop). `tests/test_recompute_anchor.py`: clean case → BUILT; no-facetb → PARTIAL (back-compat);
  **held-out reinstatement → BLOCK-with-a-question** — closing moves to 774,572,767.18, the gap is the
  held-out −59,130,178.49 (−59,130.18 SAR'000 at the TB's stored precision), status BLOCKED, the "are
  these two rows part of this TB line?" question queued. A forced tie would be the bug. The gap is
  computed (closing − TB line); `tb_scale=1000` is a unit ratio, not an entity amount.
- **All 31 suites green.** The audit follow-ups (slice-4 GL-path region detection, slice-5 recompute
  anchor) are now closed. Next per sequencing: the **output/GUI slice** — present BS + P&L as
  first-class statements with notes hanging off their lines (logged scope), as its own real slice.

### 2026-06-10 — SLICE 7 BUILT: de-hardcode the seed (A2 prefix map + A4 literal → confirmed-once store)
- **The seed is now a confirmed-once STORE, not a code computation.** `build_seed_mapping` (in
  `hierarchy/seed.py`) is a lookup over `SEED_MAPPINGS` — 15 explicit confirmed rows (10400001 +
  14 Investments incl. the two ECL contras), authored once with the fixed `SEED_TS` — plus an optional
  `confirmed=` extension for newly-confirmed accounts. **Removed from the runtime path:** `_inv_prefix`
  (`account[:4]`), `endswith("9900")`, and the literal `{"10400001"}`. `_INV_PREFIX_HINT` survives only
  as an optional proposer hint. New: `ai_propose.propose_seed_mapping` / `confirm_seed_mapping` (read
  the LABEL, 'unsure' valid). Account→structure is now signal-based propose-confirm-store, prefix a
  hint only — so the next client's differing / foreign / absent codes are handled by reading meaning.
- **C1 folded in as a PURE rename:** `MappingEntry.measurement_type` → **`sub_class`** (sector-neutral;
  same values FVIS/FVOCI/AC; value-setting untouched — the stop condition held). Readers updated:
  `seed.py`, `investments.py`, `test_hierarchy.py`.
- **Proofs** (`tests/test_seed_dehardcode.py`): **#1** mapping byte-identical to a kept
  `_legacy_prefix_seed_mapping` on the real fixtures (frozen-dataclass `==`; honest caveat: circular by
  construction — proves the freezing, a regression guard). **#2** Investments (4,256,555,000) +
  Prepayments (833,702,945.67) notes **unmoved** (regression guard). **#3 — the PRIMARY proof:** an
  unknown account maps via propose→confirm→store — (a) confident foreign-language label → maps, (b)
  ambiguous → unsure, UNCONFIRMED, surfaced (money not vanished), (c) contra-by-signal on a non-110x
  code. The real risk de-hardcoding introduces (an unknown account silently failing to map) is what #3
  guards.
- **Blast radius ≈ zero synthetic fixes:** only `test_hierarchy`'s renamed-field read changed; **no
  synthetic site needed an explicit confirmed entry** — every other synthetic `110x` runs through the
  `face_tb` path (the TB's own mapping column), not `build_seed_mapping`. **All 29 suites green.**
- A2/A4 retired; the audit's brittle cluster (A1–A4 + B1) is now fully addressed (A1 in slice 6, A2/A4
  here, B1's per-note config in slice 6). Next per sequencing: close the GL-path region-detection gap
  (slice-4/-5 follow-ups), then the **output/GUI slice** (BS + P&L as first-class statements — logged).

### 2026-06-10 — SLICE 7 plan drafted (de-hardcode the seed) + BS/P&L output scope LOGGED
- **Slice 7 plan** (`SLICE_7_PLAN.md`, review-gated, no code yet): retrofit Investments + Prepayments
  off the **A2 prefix map** (`_INV_MT`/`_inv_prefix`/`endswith("9900")`) and the **A4 literal**
  (`{"10400001"}`) onto the propose-confirm-store path PP&E uses. The seed becomes the **confirmed-once
  store** (frozen `MappingEntry` facts, fixed `SEED_TS`); `build_seed_mapping` becomes a store lookup;
  prefix patterns survive only as optional proposal hints. **Proof = byte-identical no-regression:**
  on the real fixtures, new `build_seed_mapping` output `==` old prefix output exactly (frozen
  dataclass equality, against a kept `_legacy_prefix_seed_mapping` reference), AND Investments +
  Prepayments notes build identically (figures/status/reconciliation unmoved). Plus one unknown account
  through propose-confirm-once to prove the path. Blast radius flagged: synthetic-account tests that
  leaned on prefix generativity get explicit confirmed entries. C1 (`measurement_type`→`sub_class`)
  optional, foldable under the same proof.
- **LOGGED (durable) — BS & P&L are a PRIMARY deliverable for the output/GUI slice.** Per Abhishek
  (*"used for creating BS and P&L, and related notes"*): the **face statements (BS + P&L) are the
  headline output**, notes are their per-line drill-downs. `FaceStatements` is **computed today**
  (slices 1–2) but **not presented** — no export, no formatted statement. The output slice must present
  **BS + P&L as first-class statements with notes hanging off their lines**, not notes alone. Recorded
  here so it isn't lost between now and that slice.

### 2026-06-10 — Hardcoding AUDIT + SLICE 6 BUILT: the PP&E note (first non-financial; generality check)
- **Hardcoding audit** (`HARDCODING_AUDIT.md`) ran first, after three findings surfaced in one slice's
  planning. Result: **brittleness is concentrated, not pervasive** — everything deciding a structural
  fact from a description/label/declared-column was already signal-based (the Prepayments
  `PrepaymentTaxonomy` is the model); the brittle cluster is exactly the decisions made from the
  account **code** — **A1–A4** (the …9900 contra + the `_INV_MT` prefix map + the literal
  `{"10400001"}`) **+ B1** (the global Investments reference table). **Legacy-import grep: clean** — the
  active spine imports nothing from the deprecated Note-5 cascade, so no legacy hardcode is reached
  through a live path. The architectural correction locked in: **"deterministic" ≠ "a code pattern"** —
  determinism comes from **propose → confirm → store**, pattern is at most an optional hint; **AI owns
  structural identification, deterministic code owns every number.**
- **SLICE 6 — PP&E note BUILT** (`fs_notes/ppe.py`), the first commercial note: a **two-layer movement
  schedule** (cost roll-forward + accumulated-depreciation roll-forward → NBV = cost + contra), per
  class and total. Built **P-C-S from the start, zero new hardcodes.**
  - **A1/A2 fixed inline by SIGNAL, not pattern:** contra identification + asset class come from
    `propose_ppe_structure` (reads the LABEL, never the code; 'unsure' valid) → `confirm_ppe_structure`
    → re-applied deterministically. NO `endswith`, NO prefix map. **B1:** a per-note `MovementConfig`
    (PP&E's own codes) + unmapped→Unclassified-flagged→propose-confirm. **C1:** the dimension is the
    asset class (no `measurement_type` leak). **Anchored via `LineRecon` (slice-5 contract): NBV
    reconciles to the PP&E TB line; a reconciliation BLOCK overrides any internal pass.**
  - **Guards** (`tests/test_ppe_note.py`, 7): NBV→BUILT; both schedules tie+net; **per-class pairing**
    (a mis-pairing that still totals 708m is CAUGHT — grand ties, per-class wrong, Plant flagged);
    **Land no depreciation** (universal rule); contra-by-signal (fake client, label-over-code on a
    non-conventional code, no silent guess); unmapped ref → flagged; **lie BLOCKS at two magnitudes**.
  - **CAUGHT a lookalike, then re-ran on REAL fixtures.** First built against an in-memory synthetic set
    that shared the grand totals (929/−221/708) but had different per-class numbers — exactly the trap
    the per-class guard exists for. Re-pointed at the real `PPE_Reconciliation_…GL.xlsx` (7 accounts,
    56 postings) + the populated TB PP&E line (708,000 SAR'000: Land 150,000 / Buildings 333,000 /
    Plant 193,000 / Vehicles 32,000). The note pairs cost+contra → per-class NBV, keys by the cost
    code, scales to '000, reconciles to the line (GL Σ 708,000 == TB 708,000, gap 0.0). **Per-class now
    matches the GL EXACTLY** (Buildings 435/333, Land 150/150, Plant 280/193, Vehicles 64/32 — millions).
    The TB line reading 0.00 earlier was a stale-copy desync from the same fixture growth; resolved.
    Script: `ppe_note_check.py`.
  - **A2 PREFIX MAP UNTOUCHED** (the lock): PP&E does not add itself to `_INV_MT`; Investments/
    Prepayments entries unchanged. Retrofitting them off A2/A4 with a byte-identical no-regression
    proof is **Slice 7** (kept separate so new-note and refactor-proven-notes never mix in one suite).
- **Fixture drift handled honestly:** the user extended both derived TBs with a commercial skeleton
  (PP&E cost classes + Trade payables / Share capital / Revenue / Cost of sales) and added a real
  `PPE_Reconciliation_…GL.xlsx`. bucket_c's incidental leaf-count sanity (20) went stale → **re-pinned
  20→23** with a comment; the MEANINGFUL reconciliation assertions (Investments BUILT exact,
  Prepayments 833,702,945.67, orphans −59,130,178.49) were **verified to still hold exactly** — not
  loosened. **All 28 suites green.** Recorded follow-up: the PP&E TB line is a zero skeleton, so a real
  PP&E reconciliation awaits a populated TB line.

### 2026-06-10 — SLICE 5 BUILT: the note-contract inversion (breakdown reconciles to the TB line)
- **The flip.** A note no longer owns its number. `tie_ok` changes from "Σ my lines == my own total"
  (internal) to **"the breakdown reconciles to its anchoring TB line"** — reusing the **same
  `LineRecon`** the Bucket C keystone uses (one reconciliation path, not two, can't drift). Built to
  `SLICE_5_PLAN.md` after review, with the two review additions.
- **Symbols:** both notes gain an **`anchor: LineRecon`**. New properties: `reconciles_to_tb`,
  `internal_tie_ok` (generic `Note`) / `internal_structural_ties_ok` (`InvestmentsNote`) — the old
  internal ties, demoted to structural preconditions. `magnitude_verified` is now a property =
  `anchor.reconciles` (the float `magnitude_anchor` param/field is **removed**, superseded). The
  region→engine-style anti-drift discipline applied to the note builders: `emit_account` (slice 4)
  and now the single `LineRecon` check.
- **Precedence stated as precedence:** a reconciliation **BLOCK overrides any internal pass** —
  `status()` returns BLOCKED when `anchor.status()=="BLOCKED"` even if every internal tie holds.
  Internal consistency can never upgrade a failed reconciliation.
- **Recon-to-raw carried through** (R23): the anchor reconciles to `recon_amount` (raw when a
  breakdown exists), with `adjustment_bridge` (Final−raw) visible — never a tolerance.
- **No-anchor → magnitude-unverified, never silently BUILT** (R16, the GL-only Track-1 default) — the
  dangerous failure was always the silent default; this gives the inversion teeth in the GL-only case.
- **Guards** (`tests/test_note_inversion.py`, 6 tests): Investments anchored → **BUILT** (gap 0.00,
  total_net 4,256,555,000 SAR ↔ TB raw 4,256,555 TB'000); **the internal-tie-that-lies BLOCKS at TWO
  magnitudes** — a clean planted **−300 TB'000 (300,000 SAR)** small gap AND a 1bn large gap, both
  above `tol=0.005`, both BLOCK while `internal_structural_ties_ok` stays True (the small-real-gap and
  the recon-to-raw false-gap are mirror images — a test on each side); **partial coverage** → PARTIAL
  to the covered subtotal; **PARTIAL→BUILT** recompile transition (unit unconfirmed → answer → BUILT,
  a real status-boundary crossing, not just a re-run). Script: `note_inversion_check.py`.
- **Existing tests updated to the new contract** (not weakened): `tie_ok`→`internal_tie_ok` /
  `internal_structural_ties_ok` (investments, prepayments); `test_recompute` terminal assertion now
  PARTIAL+magnitude-unverified (the GL-only `recompute()` orchestrator supplies no anchor → correctly
  never silently BUILT). **All 27 suites green.**
- **Caveat preserved (5 slices, no overclaim):** reconciling to a *derived* TB proves breakdown↔line,
  NOT that the line is independently right — independent keystone sign-off stays parked on finance's
  own (non-derived) TB.
- **Recorded follow-ups:** thread the FaceTB anchor through the `recompute()` ORCHESTRATOR (will
  surface the real reinstatement-vs-TB-raw question: held-out reinstatement moves Prepayments to the
  774.6M control total, which must then reconcile against the 833.7M TB raw). Sequencing next: first
  non-bank note (generality checkpoint) → close the GL-path region-detection gap → GUI.

### 2026-06-10 — SLICE 4 BUILT: the parsing front-end (find & read the table correctly), guarded
- **New package `ai_accountant/parsing/`** — the front-end between the proven engine and an arbitrary
  upload. Built to plan after review (`SLICE_4_PLAN.md`), with two additions the review demanded.
- **Defining property drives it:** a mis-detected boundary SILENTLY corrupts numbers (no crash), and
  there's no downstream tie to catch it — so the parser never silently extends/truncates/absorbs a
  boundary.
- **Components:** `file_kind.py` (TB-vs-GL by CONTENT signals, never filename; an UNSURE→asks verdict;
  per-file v1 with per-region recorded as the revisit) · `region.py` (`DetectedRegion` with
  confidence / `needs_review` / `confirmed`; `ParsingGateError`) · `detect.py` (`propose_regions` —
  header by max field-resolution, span = first→last DATA row; **TB tie-breaker:** P scaffold + C leaf
  are ONE data block keyed off Level/Account-Type, not "where the numbers start") · `confirm.py`
  (`confirm_region` + `extract` gate) · `route.py` (three-case detect-and-maximize; TB → FaceTB via
  the shared `emit_account` core refactored out of `ingest_tb`, so region-path and whole-sheet-path
  never drift).
- **Two failure directions, opposite guards:** include-too-much (trailing footer subtotal → EXCLUDED,
  the 1.6B shape) and include-too-little (interior blank → span continues past it, tail kept).
- **Review addition 1 — the second line of defense (R24, conservatism):** exact-match on the fixture
  proves only the mess we DESIGNED; for the mess we didn't, a low-confidence region is `needs_review`
  and **cannot be auto-confirmed** (explicit override required) — an interior subtotal degrades to
  conf 0.70 < 0.75 and is refused. **Review addition 2 — headless without auto-accept:** the only path
  slice 4 runs is programmatic, so a test/CLI confirms against a KNOWN answer; a WRONG boundary is
  REJECTED and flagged, never rubber-stamped (`test_wrong_boundary_is_NOT_auto_confirmed`).
- **Guard fixture** (`tests/test_parsing_frontend.py`, 8 tests): a hand-built messy grid (title,
  `(in SAR '000)` subheader, F/G instruction row, blank separators, INTERNAL blank inside the data,
  two trailing footer subtotals) with a KNOWN answer (header 5, data 6–12); asserts EXACT region, not
  "plausible." Scripts: `parse_frontend_demo.py` (shows the boundary as the confirm step would),
  `build_messy_fixture.py` (materialises the .xlsx). **All 26 suites green** (the `ingest_tb` refactor
  left every TB/Bucket-C suite passing).
- **Scope kept firm:** the account MATCHER (Bucket B) is a different risk surface and is NOT in this
  package. Distinct also from the legacy `ingestion/table_detect.py` (which served the Note-5 cascade).
- **Recorded follow-ups:** per-region file-kind; AI multi-region proposer behind `propose_regions`;
  re-wiring GL `ingest_workbook` onto confirmed regions (still `region = sheet` internally).

### 2026-06-10 — Scope correction: the parsing front-end is UNBUILT (named as Slice 4), three-case re-pin
- **Honest status recorded** (`SLICE_3_PLAN.md`): everything proven — incl. the reconciliation that
  just passed — was fed data of KNOWN structure (scripts that knew the header row / SAR column;
  `region = sheet` v1; known-header resolver). **The parsing front-end the app needs is effectively
  still stubbed** and is NOT folded into "ingestion, done." The neat derived TBs would lull a parser
  into looking solved; the real test is the mess (title row, `(in SAR '000)` subheader, instruction
  row, blank separators, footer subtotals that caused the 1.6B double-count, orphan rows).
- **Three input cases re-pinned as detect-and-maximize** (TB-only / TB+GL / GL-only), each with a
  different front-door parse + a file-kind detection step. TB+GL reconciliation passing ≠ "app handles
  all three."
- **Slice 4 = the parsing front-end, its own slice, next build target** (no precondition): file-kind
  detection → structure-agnostic region detection (AI-proposes-regions / human-confirms-boundaries,
  never auto-slice) → field resolution on unfamiliar layouts → three-case routing, guarded by a
  deliberately MESSY synthetic fixture. New silent-failure surface: a mis-detected boundary silently
  corrupts numbers → flag-don't-auto-slice.
- Bucket B (matcher) and independent keystone sign-off remain parked on their two preconditions.

### 2026-06-10 — Bucket C MACHINERY SIGN-OFF on real magnitudes (corrected TB → clean BUILT sweep)
- Derived TBs regenerated to the authoritative 833,702,945.67 (Prepaid line 833,702.95 SAR'000,
  share-capital rebalanced; TB balances). Re-ran Bucket C:
  - **Investments — BUILT exact** (GL 4,256,555,000 == TB raw, gap 0.0000, ECL contras included).
  - **Prepayments — BUILT exact now** (GL 833,702,945.67 == TB raw, gap 0.0000 at the TB's 2dp-'000
    precision).
  - **Orphans — still net −59,130,178.49 SAR** (the two malformed rows surfaced, not absorbed).
- **The test kept its teeth (R21):** `test_bucket_c.py` now reconciles with a **TIGHT tol=0.005**
  (sub-rounding only) and asserts the Prepayments line is **BUILT with gap == 0.0** against the
  corrected figure — not a widened tolerance. A real gap (e.g. the old 3.27M) would still BLOCK. The
  lesson it locks (keystone flags a real aggregation disagreement) stands — we fed it the right number,
  didn't loosen the check.
- **Machinery sign-off:** Investments and Prepayments both reconcile exact on real GL totals through
  the full routing/disposition pipeline, orphan finding intact. This is the machinery proven on real
  magnitudes — NOT the independent sign-off (TB derived from GLs → ties by construction; independent
  waits on finance's own TB). All 14 suites / 50 tests pass.

### 2026-06-10 — The 3.27M, confirmed (show-the-work): R14 continuation rows, not a footer leak
- `scripts/show_3p27m.py` decomposes the Prepayments GL: strict literal-`10400001` = **830,435,137.84**
  (the TB's naive figure) **+ 383 R14 continuation rows = 3,267,807.83** = pipeline **833,702,945.67**;
  the 4 footer subtotals (**774,572,767.18**) are correctly EXCLUDED (they're the old 2× double-count).
- The 383 rows: **blank account column but each carries a transactional id (doc/date/ref/object-key)
  → R14 'continuation' → inherits sheet account 10400001.** Their references confirm genuine
  prepayment postings (PREPAID AMORT / RECLASS, JAN MED INS ×191, MERCEDES, releases, year-end adj).
  **Disjoint from the footer rows** (footers have no transactional id → 'subtotal_row', excluded) — so
  not a footer slice leaking in. ⇒ **833,702,945.67 is the authoritative clean 10400001 figure.**
- Once finance regenerates the derived TB's Prepayments line to 833,702,945.67, the line reconciles
  BUILT exact. `test_bucket_c.py` also locks the no-mappings structural guarantee (20 unmapped flagged,
  keystone awaits, 20 questions — no silent guessing). All 14 suites pass.

### 2026-06-10 — Slice 3 Bucket C run (real magnitudes) + Run 2 AI face-mapping (machinery, not independent sign-off)
- **Real-file ingestion adaptations** (derived TB): robust header-row detection (skips a title block),
  `Amount as per trial balance` / `L2 Mapping` (face line) / `L0 mapping` (section) columns; a
  `section` tag on `TBAccount`; `recon_amount` (reconcile to **raw** when a breakdown exists, else
  Final — a Final-only TB has nothing to bridge); routing `tol` for thousands-rounding.
- **RUN 1 (Bucket C):** **Investments reconciles BUILT exact** — GL Σ 4,256,555,000 == TB (gap 0),
  incl. the two ECL contras rolling in negative. The **two planted malformed rows surface as orphans,
  net −59,130,178.49 SAR** (exact) — not absorbed. **Prepayments: BLOCKED** — my GL aggregation
  833,702,945.67 vs the TB's 830,435,137.84, gap 3,267,807.83 (NOT the expected BUILT). Same method
  gave Investments an exact match, so this is a genuine GL↔TB difference (not a year-cutoff, not
  exact-dup dedup — unexplained); the keystone correctly **flagged it instead of rubber-stamping
  BUILT**. Flag for reconciliation with whoever derived the TB. `tests/test_bucket_c.py`,
  `scripts/bucket_c_run.py`.
- **RUN 2 (AI face-mapping):** no-mappings TB → 20 unmapped leaves flagged, keystone awaits, 20
  questions queued (no silent guessing). AI proposals (same path, new prompt — `propose_face_mappings`,
  reuses `LLMClient`): **20/20 exact-match vs key, 0 low-confidence**; subtle ones all correct
  (11029900/11039900 → Investments contra; 41010101→Cost of sales, 51010101→Revenue by **label over
  code**). 'unsure' verdict available but not triggered (all labels unambiguous); nothing force-mapped.
  `scripts/bucket_run2.py`.
- **Sign-off language:** the derived TB ties by construction → this verifies the **machinery on real
  magnitudes**, NOT independent sign-off (that waits on finance's own TB). Bucket B (matcher) and the
  independent sign-off remain paused. All 14 suites pass.

### 2026-06-10 — Slice 3 design update: G/L precedence + the "both" CoA answer + crosswalk-first matcher
- **G-vs-L precedence (not just naming):** documented in `face_tb/classification.py` and the plan —
  G-levels exist ONLY on the GL-only path; **the moment a TB is present, the L-levels are
  authoritative and G-levels are not consulted**, so the note recast routes through the TB
  classification, never the GL-fallback. Closes the last naming hazard.
- **§9.1 answer = "both" (per-account, not per-file):** routing is a **graded path, not a mode
  switch** — deterministic code-match where codes align (built), assisted fallback where they don't.
  An unmatched account is the **orphan finding extended** (candidate for assisted match), not an error
  and not a parallel path.
- **Matcher (Bucket B) DESIGN locked, BUILD held — crosswalk-first:** (1) deterministic code-match
  (built) → (2) confirmed-once **crosswalk table** (`GL X → TB Y`, AI proposes / human confirms /
  stored, deterministic thereafter — the renumbering common case) → (3) per-row AI match (last
  resort). Held pending the team answer: renumbering (mostly crosswalk) vs different account set
  (more per-row).
- **Next build = Bucket C (keystone sign-off on real data), before B:** the deterministic core already
  covers the matching majority of a same-system export, so the keystone signs off on the clean-match
  accounts the moment a populated real TB + matching GL lands; the matcher is an enhancement, not a
  precondition. `SLICE_3_PLAN.md` updated. No code logic changed (docstring + plan only).

### 2026-06-10 — TB-first redesign, SLICE 3 (no-precondition parts): rename + routing + recon keystone
- **Plan:** `SLICE_3_PLAN.md` (three buckets: buildable-now ✅, blocked-on-§9.1 matcher ⛔,
  blocked-on-real-data keystone sign-off ⛔).
- **A1 — locked first task DONE:** GL-fallback hierarchy levels `L1–L4` → **`G1–G4`**
  (`hierarchy/seed.py`, `nodes.py`, consumer test, CLI). TB classification keeps `L0–L4` (`face_tb`);
  legacy cascade untouched. The L1–L4 / L0–L4 overlap is gone — no half-renamed mix.
- **A2/A3 — routing + the four findings** (`face_tb/routing.py`): `route_gl_to_tb` matches GL→TB by
  code (deterministic core). Findings: orphan (flagged), reconciliation gap (**BLOCKED**, diff =
  GL Σ − TB raw, exact), partial coverage (**PARTIAL**, reconciles to the COVERED subtotal),
  granularity mismatch. `LineRecon.status()` BLOCKED/PARTIAL/BUILT. Synthetic TB+GL set tested
  (`tests/test_tb_routing.py`).
- **A4 — recon-to-raw guard:** reconcile GL to the **raw** TB amount, never `Final`;
  `raw + adjustment = Final` is a visible itemized bridge (`adjustment_bridge`), never a tolerance.
  Verified: a line with an adjustment reconciles to raw (GL ≠ Final, still BUILT) — reconciling to
  Final would manufacture a false gap.
- **NOT built (gated, awaiting review + the two chased items):** the matcher *strategy* (deterministic
  vs AI fuzzy-match — §9.1), the keystone *sign-off* (needs a populated real TB+GL — synthetic ≠
  proven), the note-contract inversion, and the TB-path UI.
- **All 13 suites / 48 tests pass.**

### 2026-06-10 — TB-first redesign, SLICE 2: TB-only made real (richer face + gap + recompile)
- **Richer face assembly:** section subtotals + statement totals; verified on a fuller synthetic TB
  (all five L0 sections) — Total assets 9,500 == Liabilities 3,300 + Equity 5,000 + Net income 1,200,
  keystone balances; L3 note-subtotals exposed (PP&E 4,500, Inventory 2,000). Still no note module.
- **TB-only gap report** (`face_tb/gap.py`): every note-backed (breakdownable) face line carries
  **"PARTIAL — face built, GL breakdown not provided"** (§4 TB-only state); non-note lines '—'.
  `NOTE_BACKED` is seeded config (R18). Findings — unmapped leaves, unknown-section leaves,
  near-duplicate captions — flow to the clarification queue.
- **TB recompile loop** (`face_tb/recompute.py`, reuses the GL loop's `Resolution`): an answer is a
  stored fact; the **face is reassembled from the FaceTB + all resolutions**, never patched.
  Resolutions: map an unmapped leaf, assign an unknown section, merge near-duplicate captions.
- **Guards (R21):** answering an unmapped-leaf finding recomputes the face by **exactly** the leaf's
  amount (the Cash line moves +75, face becomes complete & balances), idempotent; caption-merge
  un-fragments one line; unknown-section assignment makes the keystone runnable. Adjustment check
  refined — a TB carrying only a Final column has nothing to reconcile (no false mismatch).
- **Tests:** `tests/test_face_gap.py`; `scripts/face_tb_check.py` (fuller TB). Engine+CLI+tests, no UI.
- **All 12 suites / 43 tests pass.** Chasing before slice 3: a **populated real TB + matching GL**
  (for keystone-against-real-numbers) and the **§9.1 chart-of-accounts answer** (lookup vs fuzzy-match).

### 2026-06-10 — TB-first redesign, SLICE 1: TB ingestion + face-statement assembly (TB-only)
- **Two-TB separation (structural):** the GL-derived class `TrialBalance` → **`RollForwardTB`** (renamed
  everywhere, no alias — a shared name silently muddies which is the position vs the breakdown). Its
  role is now "GL-side breakdown artifact." The new spine is the ingested **`FaceTB`**.
- **New package `ai_accountant/face_tb/`:** `classification.py` (ingested L0–L4, READ not computed +
  the old↔new crosswalk), `model.py` (`FaceTB`/`TBAccount`/`Adjustment` — `raw_amount` & `final_amount`
  kept separate for the slice-3 recon-to-raw; `Adjustment` a LIST over variable columns), `rollup.py`
  (summation over the ingested classification; exposes the L3 note-subtotal), `ingest.py` (column
  resolver by meaning; tolerates stray tabs, sub-designations, N adjustment columns; unparseable rows
  flagged not dropped), `face.py` (BS from Asset/Liability/Equity, P&L from Income/Expense; the real
  balance keystone).
- **First guards (R21), on a hand-built synthetic TB that balances to a set number (1,400):**
  TB-side mapping coverage (unmapped amount-bearing leaf flagged AND it is *exactly* the keystone
  gap); **keystone refuses to run, labelled, on an unknown L0 section**; adjustment arithmetic
  (`raw + Σ adj == Final`, a gap and an adjustment can't masquerade); near-duplicate mapping captions
  fragment (open vocabulary) and are **surfaced** (`distinct_mappings`/`near_duplicate_mappings`),
  never silently merged; stray-tab code normalised. `tests/test_face_tb.py`, `scripts/face_tb_check.py`.
- **Slice-1 boundary (out):** GL routing, TB↔GL reconciliation, note recast (the inverted `tie_ok`),
  adjustment entry surface, comparatives, UI of the TB path — all slice 3+.
- **SLICE-3 PRECONDITION (write-it-down-now):** the **first, blocking task of slice 3** is renaming the
  old GL-fallback hierarchy off L1–L4 to remove the L1–L4 / L0–L4 label overlap — *before* notes are
  recast. Half-old-half-new naming going live when the layers meet is the silent-confusion bug.
- **All 11 suites / 39 tests pass.**

### 2026-06-10 — FS-Gen: answered-questions recompile loop (R8) — answering changes the FS
- **`ai_accountant/recompute.py`:** an answer becomes a stored `Resolution` (value + approver +
  timestamp); `recompute(entries, resolutions, scale)` rebuilds the **entire FS deterministically
  from raw ingest results + every resolution** — new postings, TB, notes, gap report, statuses. The
  UI never writes a number; the figure changes because the recomputation changed it. Idempotent.
- **What resolutions do:** period window → confirmed `PeriodWindow` (split defined, as-of set);
  quarantined row "reinstate" → the held-out amount becomes a posting (drops the total toward the
  control total, flips the tie); dedup / control-artifact / Other / source-recovery → acknowledged,
  clearing their provisional reason; magnitude → clears only when an independent anchor figure is
  supplied AND matches (R16). `TrialBalance` and `Note` now carry a `resolved` set so
  `provisional_reasons()` drops acknowledged concerns — a note reaches BUILT when its LAST clears.
- **Guard (R21) — the loop's whole job, asserted precisely:** `test_recompute.py` asserts
  reinstating the 2 held-out rows moves the recomputed total by **exactly −59,130,178.49** (→
  774,572,767.18, the control total), the held-out reason disappears, it's idempotent, and
  **answering every Prepayments question flips PARTIAL → BUILT**. Catches the "stored but not
  applied" failure (answer looks recorded, FS unchanged).
- **UI wired:** the Q&A panel's "Record answer & recompute" stores a `Resolution` and reruns;
  everything (notes / gap / statuses / exports) is recomputed. Integration test
  `test_ui_answer_recomputes_the_rendered_figure` confirms answering through the app moves the
  rendered Prepayments total 833,702.95 → 774,572.77 (SAR'000) — recomputed, not patched.
- **All 10 suites / 33 tests pass.** Track 1 + the recompile loop are solid; ready for the redesign.

### 2026-06-10 — FS-Gen: units-consistency fix (silent-magnitude class in presentation, R23)
- **Bug:** the Investments PDF headline read `4,256,555,000.00 SAR` (absolute) while the table below
  it read `4,256,555.00` under `Amount (SAR'000)` — same quantity, two units, one note. Root cause:
  `Presentation.unit_label` was a **free string decoupled from `scale`**, and `status_line`
  hardcoded the raw absolute figure + "SAR" while the table scaled. A reader trusting the header is
  off 1000×; the same hardcoded "SAR'000" was correct on Prepayments (genuinely thousands) — so two
  notes rendered in different real units under one label.
- **Fix:** `unit_label` is now a **property derived from `scale`** (1→SAR, 1000→SAR'000,
  1e6→SAR millions) — one source of truth. `status_line` (both note types) presents the headline
  figure **at the confirmed scale with that label**, withheld until confirmed (R11), so headline and
  table always agree. All callers stop passing a free `unit_label`. Verified: the regenerated PDF
  shows `4,256,555.00 SAR'000` in the headline, the absolute figure gone.
- **Guard (R21):** `test_unit_label_equals_the_unit_the_figures_are_in` renders Investments at scale
  1 and 1000 and asserts the label **tracks** the scale (proving it's derived, not hardcoded) and
  `figure × scale(label) == raw_total`, per note. A future hardcoded label fails this.
- **All 9 suites / 30 tests pass.** (Note: the user observed the bug on an earlier PDF whose
  Prepayments breakdown predates the AI-labelling; the fix is against current state.)

### 2026-06-09 — FS-Gen: export import-collision fix + two guards it exposed
- **Bug fixed (export download crashed on 2nd click):** `reporting/__init__.py` defined wrapper
  functions `export_excel`/`export_pdf` that imported submodules of the *same name* — importing the
  submodule rebound the package attribute from the function to the **module**, so the 2nd call hit
  `TypeError: 'module' object is not callable`. Fixed by renaming the submodules to
  `excel_writer.py` / `pdf_writer.py` and importing the functions explicitly — function and module
  names can no longer collide. Verified callable-repeatedly with correct magic bytes (PK / %PDF).
- **Why no test caught it (integration-not-unit, like the queue `__bool__`):** the suites tested the
  export functions directly but never crossed the package public surface (`export_*_bytes →
  export_*`) the app uses. Added `test_export_bytes_public_api_is_repeatable` (calls each twice —
  the collision only bit on the 2nd call) and `test_downloads_work_through_the_app_path` (AppTest
  second rerun recomputes exports through the app path).
- **Eroded guard restored (R21):** the restyle made PARTIAL amber, but the status-prominence tests
  asserted on **red (`st.error`) only** — so amber PARTIAL prominence was no longer protected (the
  suite passed because nothing checked it). Added
  `test_both_status_states_are_prominent_amber_partial_and_red_magnitude`: amber PARTIAL **and** red
  magnitude both asserted adjacent to the figures. A future grey-caption downgrade now fails a test.
- **UI download path:** now uses in-memory `st.download_button` (browser), not a server-disk write.
- **All 9 suites / 29 tests pass.** Track 1 is a clean, fully-green whole.

### 2026-06-09 — FS-Gen Phase 5 UI: four presentation fixes (no number/status/gate changed)
- **Download actually works (functional bug):** the "Wrote exports\…" message wrote to the server
  disk (invisible in a browser). Replaced with `st.download_button` fed by in-memory bytes
  (`export_pdf_bytes` / `export_excel_bytes`); the on-disk path stays for the CLI only.
- **Amber vs red, prominence kept:** PARTIAL now renders **amber** (provisional, will change); **red**
  is reserved for BLOCKED / MAGNITUDE-UNVERIFIED (don't-trust-this-magnitude) — more honest than the
  all-red flatten, still adjacent to the figures and weighty (no grey line, no collapsed footnote).
- **Doubled caveat fixed at the source:** `status_line` is now the headline (status + figure) only;
  the directional outlook / magnitude warning lives in `caveats`, shown **once**, mixed case (no
  long all-caps line). Applies to UI, PDF, and Excel uniformly.
- **Gap report rendered, not raw JSON:** one bordered card per note — name, colored status chip
  (:green/:orange/:red), open-item count, and the directional one-liner. Raw JSON demoted to an
  expander.
- **Clarification queue grouped + humanised:** three groups (Investments / Prepayments / Trial
  balance & ingestion); plain-language titles ("Held-out row 569 — misaligned…") with the type-code
  and raw path demoted to detail inside the expander; impact shown before the answer widget.
- **Tabs for output, gates stay sequential (R22):** Notes / Gap report / Clarification queue /
  Exports are tabs (safe to roam); the upload→confirm→confirm→build pipeline remains a stepped gated
  flow — tabs never bypass a gate.
- **All 9 suites pass UNCHANGED** — gating, status-travels, open-items-never-empty, export prominence
  all intact; the restyle touched no number, status, or gate.

### 2026-06-09 — FS-Gen Phase 5 (complete): Streamlit UI with gates + live Q&A panel
- **New FS-Gen Streamlit app** (`fsgen_app.py`, separate from the legacy `app.py`/`ui.py`): upload/
  sample → region-confirm → field-map-confirm → period window → trial balance → mapping-confirm →
  notes → gap report → clarification Q&A. Renders the same `GapReport`/`renderable` model.
- **Confirm steps are GATES, not suggestions (R22):** region-, field-map-, and mapping-confirm each
  require an explicit checkbox; the next step does **not** build until confirmed — clicking through
  on defaults is impossible. A field region missing a required field BLOCKS.
- **Status travels with the notes (R22):** each note's PARTIAL/NOT-FINAL banner + caveats
  (incl. MAGNITUDE UNVERIFIED) render adjacent to its figures on the same screen, not on a separate
  tab. R11: presentation unit defaults to **withheld**; figures show only once a unit is chosen.
- **Q&A panel = same queue, directional honesty:** each question shows its tie impact (why it
  matters / which way the number moves) BEFORE the answer widget; blocking questions flagged.
- **Headless regression** (`tests/test_fsgen_app.py`, Streamlit `AppTest`): asserts the TB/notes
  steps do NOT build until each gate is confirmed, and that NOT-FINAL/MAGNITUDE-UNVERIFIED appear on
  the notes screen. **All 9 suites pass.**
- **Pattern recorded (R21):** every silent-failure near-miss leaves a permanent assertion, not just
  a patch. Owed-but-noted: assert an independent control total exists-or-is-marked-absent; assert
  the served model matches the pinned string.

### 2026-06-09 — FS-Gen Phase 5: Excel + PDF export with in-file prominence
- **Render-target-agnostic model** (`reporting/render_model.py`): `renderable(note)` extracts
  status + caveats + figure rows for both note types — proving the model is reusable before a
  second consumer exists (no status detail stranded in the CLI renderer).
- **PDF export** (`reporting/export_pdf.py`) — the highest-stakes target (it leaves the system).
  Prominence survives INSIDE the file: a red **NOT-FINAL footer on every page**, a status **banner
  above the figures**, and the caveat **inline on the total row** (`[MAGNITUDE UNVERIFIED] — NOT
  FINAL`). Verified: both pages carry NOT-FINAL; the Investments-total page carries the magnitude
  caveat inline. A page screenshotted alone still reads provisional.
- **Excel export** (`reporting/export_excel.py`) — status block in the **top rows, frozen** (visible
  without scrolling, not a tab nobody clicks), caveat on the **total row** too. Verified by reading
  the file back (`STATUS: PARTIAL` + `MAGNITUDE UNVERIFIED` in the frozen top block; total row
  carries the caveat).
- **Consequence guard added (the bug's whole class):** `test_partial_note_never_renders_as_built`
  asserts a note with known open items ALWAYS renders a non-empty gap report (reasons surfaced,
  queue non-empty, "NOT FINAL" present) — so "queue silently empties → PARTIAL looks BUILT" cannot
  recur, not just this instance.
- **Tests:** `tests/test_exports.py`; `scripts/export_notes_check.py` → `exports/` (gitignored).
  **All 8 suites pass.** Remaining Phase 5: the Streamlit UI + live Q&A panel (renders this same
  model).

### 2026-06-09 — FS-Gen Phase 5 (start): gap report + downward-skew status + model stamp
- **Proposals artifact stamped** with the model snapshot (`gpt-5.1-2025-11-13`) + date — if the pin
  is later bumped, a reader sees the stored proposals came from a different model (`proposals_to_json`/
  `proposals_from_json` carry an envelope).
- **Status states DIRECTION, not just PARTIAL (R20):** `Note.provisional_outlook` says the open
  items **skew downward, not to zero** — Prepayments reconciles to the control total 774,572,767.18
  once held-out reinstates (−59.1M), with 48.0M unlabelled + −4.39M reclass likely reducing it
  further. `status_line()` carries the figure + the direction.
- **Gap report (`ai_accountant/reporting/`)** — the Phase-5 honesty core. Renders per-note
  BUILT/PARTIAL/BLOCKED with **status + caveats in a banner ABOVE the figures** (Investments'
  MAGNITUDE-UNVERIFIED and Prepayments' downward-skew are first-class, not footnotes). One model
  for every channel (CLI now, Excel/PDF/UI later); the Q&A is the **same** clarification queue.
- **Bug fixed:** `ClarificationQueue.__len__` made an empty queue falsy, so `queue or ...` silently
  discarded a freshly-passed empty queue — shared-queue threading was broken. Added `__bool__` and
  switched to `is not None`. Surfaced by the gap-report integration; covered by a regression test.
- **Tests:** `tests/test_gap_report.py` (prominence + the queue-threading regression). `scripts/
  gap_report_check.py`. Full suite (7 files) passes.
- **Remaining Phase 5:** Excel/PDF export and the Streamlit UI — both render this same gap-report
  model, holding the prominence principle (status/label as prominent as the numbers).

### 2026-06-09 — FS-Gen: model pinned to snapshot + AI proposals confirmed & applied
- **Model pinned for reproducibility (R19).** The request string was the floating alias `gpt-5.1`,
  which OpenAI served as snapshot `gpt-5.1-2025-11-13`. A floating alias would let AI proposals
  drift on re-run, so `config.py` is now pinned to the **dated snapshot** `gpt-5.1-2025-11-13`
  (override via `OPENAI_MODEL`). Confirmed: the ONLY FS-Gen LLM call is the proposer; all
  deterministic code (incl. the synthetic fixture) uses no model. The 16 proposals were generated
  by `gpt-5.1-2025-11-13`.
- **AI proposals confirmed & applied (human-in-the-loop, R8).** 15 confirmed (13 prepaid sub-types
  + 2 not-a-prepayment flags); "Total Technical Triangle" left **unclear** in Other. `confirmed`
  facts (sub_type + is_prepayment + approver + timestamp) recompile the note: Other split into
  Prepaid insurance / advertising / software & subscriptions / professional-services lines.
- **Not-a-prepayment = flagged HOLDING line, never relocated.** The 4 FX-variance/accrual rows
  (−4,390,032.87) sit on a "Flagged — not a prepayment, pending finance reclassification" line that
  stays **inside this note's total** (tie holds); a question routes them to finance. The tool
  surfaces, it does not decide the destination or move the money. Verified by test
  (`Σ lines == account_total` after application; money not relocated).
- **Prepayments remaining blockers are all finance answers, not AI:** held-out −59.1M, period
  window, dedup-key, the 45M magnitude + description recovery (48M unlabelled), the reclassify line,
  and the control artifact. The AI's job is done.
- Tests added: auditable-proposer (no-network, evidence required) and confirm-application
  (holding-line does not relocate). Full suite (6 files) passes.

### 2026-06-09 — FS-Gen: AI proposal (auditable) + R17 scoping + overfitting guard (synthetic fixture)
- **R17 surface-scoping wired:** unreadable Other rows (blank or numeric-only labels) route to an
  "Other — unlabelled (needs source recovery)" line + a **description-recovery** query, never the AI;
  the **45M blank posting gets a STANDALONE magnitude query** (materiality ≥ 10M). AI surface shrank
  to 27 readable rows / 12.78M; 6 unlabelled rows / 48.0M → human.
- **Auditable AI proposer** (`fs_notes/ai_propose.py`): proposes a sub-type + **evidence** per
  distinct label, with an explicit `is_prepayment` verdict so it can flag non-prepayments rather than
  bucket them (R5 — labels only, never figures). Live run correctly: insurance/software/subscription/
  advertising classified with evidence; "FX variance" and "Manual Accruals" flagged NOT-prepaid;
  a vendor-only name returned 'unclear'. Proposals stay unapplied until human confirmation.
- **Config-vs-engine refactor:** the prepayment keyword taxonomy is now an injectable
  `PrepaymentTaxonomy` config object; the classifier is general. See the **Overfitting audit** above.
- **Synthetic third fixture** (`tests/test_synthetic_gl.py`): a GL unlike both real files proves the
  general behaviours hold on an unseen file (resolution by meaning, blank-account disposition,
  column-shift, dedup, control capture, unmapped-account flagging). Full suite (6 files) passes.

### 2026-06-09 — FS-Gen: clearing the Prepayments queue — R15 reclass + R17 (AI surface scoping)
- **FVIS DOM/INT sanity check (Investments):** every FVIS segment tag matches an independent signal
  (the description's Domestic/International hint, a different column) — the ~50% international FVIS
  split is real (unquoted equities + convertible debt are offshore instruments), not a mis-tag.
- **R15 deterministic reclass implemented** (`is_brought_forward`, `fs_notes/classification.py`):
  brought-forward/take-on rows reclass to an **"Opening balance (brought forward)"** line *before*
  any classification, so the AI never sees an opening balance. Prepayments now: Opening 389,862,362.02
  / Prepaid 381,422,122.34 / Other 60,784,904.40 (33 rows) / control 1,633,556.91; tie holds.
  Advances/Deposits/VAT were 100% take-on → folded into Opening.
- **Checkpoint probe (R17):** the 33 "Other" rows are not uniform — ~22 (~13.1M) are vendor-labelled
  prepaids (insurance/software/subscriptions/advertising) the AI can name; **3 are blank-label real
  postings totalling 47.63M (incl. a single 45M, doc 2600000272 / ref 00098582 / 2021-02-03)**; ~8
  are oddities (FX variance, accruals, shifted-description amount-strings). A blank label is not
  AI-labelable → those go to a **source/description-recovery query** (the 45M is also a magnitude
  item), oddities are flagged. The AI only ever sees rows it can legitimately read.
- **Tests:** `test_is_brought_forward_signals`, `test_r15_reclasses_brought_forward_to_opening_before_other`.
  Full suite passes. **Paused at the pre-AI checkpoint** for confirmation before any AI proposal runs.

### 2026-06-09 — FS-Gen Phase 4b: Investments, Net note (end-to-end; both notes now work)
- **`fs_notes/investments.py` + `reference_codes.py`.** Built entirely from trial-balance leaves
  (which carry segment + `movement_by_ref`), so every figure is the deterministic GL number.
- **Reference codes probed from the real data, not assumed** — caught **`MATURITY`** as a code
  distinct from `DISP-MAT` (the PRD's 6-code prose list would have mis-bucketed it). Seeded config;
  unmapped codes → "Unclassified movement" (in closing, flagged, never dropped — R3, unit-tested).
- **Note 5.1 (by measurement type):** gross → less ECL allowance (the `…9900` contra leaf) → net.
  FVIS 292,700,000 (no ECL leaf — **asserted**, IFRS 9: no ECL on FVTPL); FVOCI net 1,966,050,000
  (ECL −2,650,000); AC net 1,997,805,000 (ECL −7,195,000); **TOTAL net 4,256,555,000**, sections
  sum to total.
- **Note 5.2 (DOM/INT):** the split **survives into the presented columns**, not just the lineage
  (verified on presented output, pre-commitment #3) — e.g. FVIS DOM 142,500,000 + INT 150,200,000
  = 292,700,000; each section's DOM+INT == net (`segment_survives`).
- **Movement schedule** ties: opening 4,056,290,000 + additions 1,911,217,500 − disposals
  1,298,750,000 − maturities 434,130,000 + remeasurement 21,587,499.40 + FX −24,999.40 + ECL
  365,000 = closing 4,256,555,000.
- **R11 gate:** figures withheld until unit confirmed. **R16:** ships labelled **"internally
  consistent; magnitude unverified — no independent control total in source"** (no footer/summary/
  recon in the workbook; the old ~36.7M AMNB figure is a different entity). Queues a question asking
  finance for an external anchor (prior-period note / audited opening / **custody statement** — the
  independent one); the note ties to it and drops the label when supplied.
- **Tests:** `tests/test_investments_note.py`; `scripts/investments_note_check.py`. Full suite
  (ingest + TB + hierarchy + both notes) passes — **end of Track 1 Phase 4: both notes compute
  correctly from the GL**.
- **Next:** Phase 5 (outputs + new UI + gap report + clarification Q&A panel), or clear the
  Prepayments queue (R15: split take-on from genuine-missed before any AI labelling).

### 2026-06-09 — FS-Gen: R14 hardened to the class + R16 magnitude-unverified
- **R14 generalised from footers to the class.** `blank_account_disposition(rec)` now governs every
  blank-account row: inherit the sheet account **only** with its own transactional identity
  (document/object-key/date/period/reference) → `continuation`; amount-only → `subtotal` (control
  total); label-only → `orphan` (header/annotation, flagged, never absorbed). A label is not enough.
  Verified on data: 1629 own-account / 383 continuation / **0 label-only** / 4 footers — so the
  hardening covers stray totals, section headers and carried-down values while changing no number.
  Tested via `test_blank_account_row_class_not_just_footers`. Residual boundary stated: a total row
  that prints its own account needs region detection, not a row heuristic.
- **R16 — internal ties prove wiring, not magnitude.** The Prepayments overstatement held a perfect
  internal tie throughout, so green internal ties are not magnitude evidence. **Investments has no
  independent anchor** (14 GL sheets, account on every row, no summary/footer/recon; the old ~36.7M
  AMNB figure is a different entity). Unit is known (absolute SAR, via cents) but magnitude is
  unverified → Investments will ship labelled **"internally consistent; magnitude unverified — no
  independent control total in source."** An external anchor (prior-period note / audited opening /
  custody statement) should be requested from finance.
- Full suite passes; plan updated (R14 hardened, R16, Phase-4b pre-commitment #4).

### 2026-06-09 — FS-Gen data-integrity fix: subtotal ghosts + control-total keystone (R14/R15)
- **Investigating "why is Prepayments 'Other' 52%?" surfaced a real bug, not a presentation gap.**
  4 rows (one per company-code sheet) were **blank in every field except the amount** — sheet
  footer/total rows that the Phase-1 blank-account fallback had assigned the sheet account and
  summed. They **double-counted the note by 2.08×** (true total **774,572,767.18**, had read
  1,608,275,712.85). Confirmed as subtotals: 3 of 4 equal their sheet's real-posting sum to the
  cent; sheet 1010's equals real + the 2 held-out rows.
- **Fix (R14):** lone-amount rows are excluded from postings and recorded as **control totals**.
  New `TrialBalance` reconciliation keystone — **closing + held-out == Σ control totals** — closes
  at **residual 0.00** for Prepayments (833,702,945.67 + −59,130,178.49 = 774,572,767.18). An
  internal tie proves wiring; this independent control total proves magnitude. **Investments is
  unaffected** (detailed export, an account on every row, no footer rows).
- **Effect on the note:** "Other" collapsed from 834M (52%) to **59.6M (7.2%)** — the genuine
  keyword-miss residual. Prepaid expenses 766.4M (92%). Tie still holds to the cent.
- **R15 carried forward:** when clearing the Prepayments queue, split "Other" into opening/take-on
  brought-forward rows (structural reclass to an opening line — not the AI's job) vs genuine
  prepayment types the keywords missed (the only AI-loop work). Negative Advances/Deposits are
  take-on credit positions, confirmed — not reversal rows caught by keyword.
- **Tests updated** to the corrected figures (ingest exceptions now 2 column-shift + 4 subtotal;
  TB closing 833,702,945.67 + control 774,572,767.18 reconciling; hierarchy/note totals). Full
  suite passes. New `scripts/prepayments_other_probe.py`.

### 2026-06-09 — FS-Gen Phase 4a: Prepayments note
- **New package** `ai_accountant/fs_notes/` (separate from the legacy `notes/` cascade, no imports
  from it): `classification.py` (seeded keyword floor — R4/R5), `note.py` (Note value object with
  the R11 presentation gate + BUILT/PARTIAL/BLOCKED status), `prepayments.py` (`build_prepayments_note`).
- **Authoritative total + reconciling breakdown:** account total = the deterministic GL closing
  (**1,608,275,712.85 SAR**); each posting's **label** (never its figure — R5) maps to a seeded
  category (Prepaid / Advances / Deposits / VAT / Other). **Σ sub-categories == account total to
  the cent at every instant** (verified), with **Other as the live plug** so the tie holds before
  any AI proposal.
- **Flag-don't-bucket (R4):** "Contra"/"Agrees to rec" land on a flagged control-artifact line
  (6 rows, 1,633,556.91 SAR) — in the total so the tie holds, but in **no** prepayment sub-category;
  raises a clarification question. The "this doesn't belong here" verdict fires instead of a
  confident mislabel.
- **R11 presentation gate:** unit/scale is an explicit unconfirmed input; figures are **withheld**
  until confirmed (blocking question queued). Confirming e.g. SAR'000 presents the scaled figures.
- **"breakdown computed" ≠ "note final":** even with the tie holding and the unit confirmed, the
  note stays **PARTIAL** while the account closing is provisional (2 held-out rows, unconfirmed
  window, 755 un-dedupable collisions) and while control artifacts / 55 "Other" rows await
  refinement. Status carries the full reason list.
- **Tests:** `tests/test_prepayments_note.py`; `scripts/prepayments_note_check.py`. Full suite
  (ingest + TB + hierarchy + note) passes.
- **Next:** Phase 4b (Investments, Net — gross→ECL→net by measurement type, DOM/INT columns,
  movement schedule from seeded reference codes) with R11 as a **hard gate** before the first
  presented figure, and an explicit assert that FVIS carries no ECL leaf (by design).

### 2026-06-09 — FS-Gen Phase 3: hierarchy + seed mapping + roll-up (and Phase 2 confirmations)
- **New package** `ai_accountant/hierarchy/`: `mapping.py` (§3 flat account→note/face/classification/
  sign table), `nodes.py` (self-referencing L1–L4 node table + structural `validate()`), `seed.py`
  (both notes seeded `approved_by="seed"`, fixed reproducible timestamp), `rollup.py` (TB leaves →
  node balances + audit lineage).
- **Investments classified from the account code (R2):** 1101→FVIS, 1102→FVOCI, 1103→AC; `…9900`
  → ECL allowance leaf (contra-asset, Cr) within its measurement type. Prepayments `10400001` →
  Prepayments face line (sub-categories deferred to the note module, Phase 4a).
- **Roll-up verified:** Investments L1 "Investments, net" closing **4,256,555,000 == TB closing**
  (through 3 L2 measurement-type subtotals that net their ECL allowance: FVOCI 1,966,050,000 incl.
  `11029900` −2,650,000); Prepayments L1 **1,608,275,712.85 == TB**. 0 structural problems, 0
  unmapped, DOM/INT leaves retained in lineage (19 / 4 leaves). Unknown accounts are surfaced as
  `unmapped`, never absorbed (Phase-6 AI-proposal case).
- **Phase 2 confirmations (from the data, not assumed):** (1) amounts are **absolute SAR** (cents
  present) — disclosure scaling will be **explicit note-module config** (R11); (2) Prepayments
  FY2024 default split shows real movements **Jan 10–May 31 2024** → partial year, carried
  **PARTIAL** with the split flagged provisional (R12); (3) held-out rows remain a human step,
  Prepayments stays PARTIAL; (4) DOM/INT are **separate leaves, never netted** (e.g. `11020020`
  DOM 405M + INT 58.5M). Hardened the period parser to read **Excel-serial dates** (R13) — fixed
  a `44196`-style cell; undated rows 6→4, totals unchanged.
- **New:** `TrialBalance.status()` / `provisional_reasons()` (BUILT vs PARTIAL). Tests
  `tests/test_hierarchy.py`; `scripts/hierarchy_check.py`, `scripts/phase2_confirm.py`. Full suite
  (ingest + TB + hierarchy) passes.
- **Next:** Phase 4a (Prepayments note — single total + reconciling sub-category breakdown) then
  Phase 4b (Investments, Net — gross/ECL/net by measurement type, DOM/INT columns, movement
  schedule), honouring R11 (explicit scale) and R12 (PARTIAL until queue clears).

### 2026-06-09 — FS-Gen Phase 2: canonical trial balance + clarification queue
- **New packages** (no legacy imports): `ai_accountant/trial_balance/` (`period.py`, `dedup.py`,
  `tb.py`) and `ai_accountant/clarify/` (R8 question queue + CLI renderer).
- **Trial balance** = one leaf per `entity_id × gl_account × dimension` (DOM/INT when present),
  each with opening + movements (broken out by reference code) + closing, sign-respecting.
  Period-windowed via `period.py` (opening = brought-forward/take-on rows + pre-window activity;
  movements = in-window; closing telescopes). `currency` is metadata, never a balance dimension.
- **R9 (held-out money breaks the tie):** `TrialBalance.ties` is True only if every leaf rolls
  forward AND nothing is held out. Verified: **Investments TYING** (opening 4,056,290,000 +
  movements 200,265,000 = closing **4,256,555,000**; `11020040` DOM 820M→905M); **Prepayments
  NOT TYING** — 2 quarantined rows (~−59,130,178.49 SAR) break the tie, closing **1,608,275,712.85**
  (identical to the Phase-1 ingest sum — no money moved).
- **R6 (dedup guardrail) — important correction:** the identity key is line-level only if the
  source carries a Line/BUZEI field. The SAP samples don't, so the key is document-level and
  collides (755 rows) on legitimately-repeated lines. Dropping "exact duplicates" was removing
  real money (closing drifted to 1,620,076,135.95), so dedup now **drops nothing without a line
  field** and raises **one aggregate** "key not unique — supply Line/BUZEI" question instead of
  hundreds. Closing returns to the correct 1,608,275,712.85.
- **R8 (clarification queue):** unresolved items queue structured questions (record shape per the
  plan) with the safe default applied (held-out → breaks tie). **Period window asked at run start
  (blocking)**; everything else batched. Prepayments run produces a clean **4 questions** (window,
  one dedup-key, two held-out rows) — honest, not noisy. CLI renderer now; in-app panel at Phase 5.
- **Tests:** `tests/test_trial_balance.py` (ties/held-out/dedup/queue). `scripts/build_tb_check.py`
  prints the TB + tie + queue for both files. All Phase 1 + Phase 2 tests pass.
- **Next:** Phase 3 (account→L4-L1 hierarchy + seed mapping table) → 4a Prepayments / 4b Investments
  note modules.

### 2026-06-09 — FS-Gen Phase 1: GL ingestion (new architecture)
- **Pivot to FS-Gen** (GL → trial balance → notes) per `PRD.md` + `2_DEVELOPMENT_PLAN.md`. New
  package `ai_accountant/gl/` (independent of the legacy Note-5 cascade): `posting.py` (canonical
  `Posting`), `field_resolver.py` (format-agnostic, seeded SAP header→canonical map, required-field
  validation), `regions.py` (region=sheet v1 behind a multi-region interface), `level_detect.py`
  (GL path; sub-ledger/transactional stubbed), `ingest.py` (orchestrator).
- **Verified on both real SAP GL workbooks** (`GL/`, 17-col Prepayments + 29-col Investments —
  resolver is format-agnostic from day one): Investments → 829 postings, 14 accounts, **0
  exceptions**, numbers tie (FVOCI sukuk `11020040`: 820M + 85M = 905M; ECL allowances negative
  contras; DOM/INT captured). Prepayments → 2,014 postings, **one account `10400001`** across 4
  company codes (entity from sheet-name fallback), **2 column-shifted rows quarantined** (flagged,
  not auto-fixed); ~387 blank-account continuation rows correctly defaulted to the sheet's account.
- **Tests:** `tests/test_gl_ingest.py` (skips if `GL/` absent). `scripts/ingest_gl_check.py` reports.
- **Plan updated (Round-3, R8–R10):** AI-mediated **clarification-loop** (queue → batched GPT-5.1
  phrasing → user answers → GPT-5.1 interprets → deterministic recompile; idempotent; CLI now /
  UI later); **held-out money must break the tie (R9)**; **quarantined-row correction discipline
  (R10)**. Sample entity is **NEOM**.
- **Still to do:** Phase 2 (trial balance: period window asked at run start, dedup guardrail,
  per-leaf roll-forward with held-out breaking the tie) → Phase 3 (hierarchy + seed mapping) →
  4a Prepayments / 4b Investments notes → Phase 5 (new UI + gap report + Q&A panel).
- **Note:** `GL/` is real (obfuscated NEOM) data — recommend gitignoring it; not committed.

### 2026-06-04 — POC hardening pass (4 deferred items)
- **Fuzzy policy matching** (`policy/classify._best_policy_rule`): token-overlap with light plural
  stemming + threshold, replacing exact-substring. Real policy-rule wordings now match real
  security names (e.g. "government sukuk held to maturity" → "Saudi Govt Sukuk 2028 …" now hits
  **[policy]**, was [IFRS 9]). Non-matches still fall through to IFRS 9.
- **Confidence on streamed large files** (`streaming` collects stats → `controls.run_streamed_controls`):
  classification coverage, negatives, duplicate IDs computed incrementally; streamed 300k-row file
  now reports **High** (was "Unknown"). `CascadeResult.stream_stats` added.
- **Two new internal controls** in `run_controls`: **roll-forward** (opening + net movements =
  closing, when opening provided) and **cross-source consistency** (same holding, conflicting
  values across files → double-count risk).
- **QA scenarios promoted to pytest** (`tests/test_qa_scenarios.py`): L4-split==L4-only merge,
  streamed-file confidence, opening roll-forward control, cross-source control.
- **Tests: ~42 across 11 files, all green.** Deferred tracker updated (3 items resolved).

### 2026-06-04 — Phase 8 QA battery + policy docs sourced & validated
- **`scripts/qa_suite.py`**: generates a multi-format test battery into `qa_data/` (gitignored)
  and runs each scenario. **10 scenarios, 0 errors:** full multi-level; L4-only (partial/Medium);
  L3-only; **L4 split across 3 files** (== L4-only → multi-file merge works); **foreign column
  names** (normalized); opening+L4 (complete); **missing classifications** (38 auto-classified via
  IFRS 9); **adjacent tables, no blank line**; **multi-sheet Excel**; **300k-row streamed** file.
- **QA findings:** (a) missing-classifications shows IFRS 9 reclassifies sukuks as FVOCI when no
  policy says hold-to-maturity → demonstrates *why policy upload matters*; (b) the streamed
  large-file path reports confidence "Unknown" (skips internal controls) — small gap to note.
- **Policy docs sourced & validated** (`scripts/extract_policy.py`, `scripts/test_policy_samples.py`;
  saved to `policy_samples/`, gitignored):
  - Extracted the **real Bank AlJazira** investment-classification text from the bundled PDF →
    `extract_policy_rules` produced **20 rules**. **PyPDF2 was sufficient** for this text PDF →
    LLMWhisperer only needed for scanned/image/complex PDFs (none hit yet).
  - Added a generic **IFRS 9 policy template** (from web search) → **14 rules**.
  - Finding: policy matching is exact-substring (brittle); fuzzy/semantic matching is the
    "arbitrary-policy hardening" deferred item.
- Scripts committed; generated `qa_data/` + `policy_samples/` gitignored. 38 unit tests still green.

### 2026-06-04 — Phase 6 (part 1): note-definition framework
- New **`ai_accountant/notes/`** package: `NoteDefinition` (note_id, title, buckets,
  classification_map, value_column, l1_label_map, gl_accounts) + `registry` (NOTE5, NOTE_REGISTRY,
  `get_note` with default fallback). This is the seam for generalizing to 40+ notes.
- **Engine now reads the active note's definition** instead of hardcoding Note 5:
  `cascade._BUCKETS/_CLASS_MAP`, `reconcile._BUCKETS`/L1 label map, `controls._GL_ACCOUNTS` all
  source from `DEFAULT_NOTE`. Note 5 behavior is **byte-identical** (all prior tests pass).
- **Tests:** `tests/test_notes.py` — registry + fallback, NOTE5 shape, engine-reads-from-definition,
  a new note can be defined. **38 tests across 10 files, all green.**
- **Honest scope:** this is the *config* seam. The compute *logic* is still investment-shaped
  (purchases→holdings→buckets); a non-investment note needs its own per-note compute steps + sample
  data. Tracked under Phase 6 "still to do".
- **Next:** pick the 2nd note → user provides its sample data → build per-note compute + validate.

### 2026-06-04 — Export fixes (user feedback) + richer L4-only sub-ledger
- **Excel now includes the uploaded source tables** (incl. every L4 transaction table) as its own
  sheet, alongside the computed L1/L2/L3/Reconciliation/Confidence. Sheet names sanitized/uniqued
  (`_unique_sheet_name`). For an L4-only upload the workbook now has L4-A…L4-G sheets.
- **PDF now covers all levels**, not just L1: added an **L3 sub-ledger** table (truncated) and an
  **L4 transactions** section (a capped preview of each detected L4 table) — with "full detail in
  the Excel export" notes. Previews truncate cols/cells to fit the page.
- **Richer reconstructed L3:** when only L4 is uploaded, the rebuilt sub-ledger now carries a
  **Security_Name** pulled from the L4 tables (purchases/MtM/EIR), so it's not just IDs.
- **Note on L4-only detail:** with only L4, L3 can't have columns that never existed in the data
  (ISIN, Issuer, Currency, Coupon%, Maturity…); those only appear when an L3 sub-ledger is uploaded.
  The L2 summary is a bucket rollup (sub-category granularity needs L3 metadata).
- **Ops:** found/killed stale Streamlit servers (two running since 6/2 served old code → "disabled
  export" confusion); standardized on launching from the venv on port 8501. Gitignored run.log/err.
- **Tests:** `test_export.py` extended — L4-only Excel round-trips all source tables; L4-only PDF
  is substantially larger (has L3+L4). **34 tests across 9 files, all green.**

### 2026-06-04 — Phase 5 COMPLETE: Excel & PDF export
- **`export/excel.py`** (openpyxl): multi-sheet workbook — Note 5 (L1) · Classification (L2) ·
  Sub-ledger (L3) · Reconciliation (if an answer key was uploaded) · Confidence. Returns bytes.
- **`export/pdf.py`** (reportlab): audit-style PDF — title, L1 face table, L2 classification,
  reconciliation table (variance rows highlighted), confidence verdict + controls + AI summary.
- **UI**: the two previously-disabled buttons are now real `st.download_button`s
  (`note5_investments.xlsx` / `.pdf`), wrapped so a failure never breaks the results view.
- Both exports take the `Note5Result` (duck-typed → no import cycle).
- **Tests:** `tests/test_export.py` — Excel opens with all 5 sheets and its L1 values equal the
  computed numbers (FVTPL 2,780,000; TOTAL matches); PDF starts with `%PDF` and is non-trivial.
  **34 tests across 9 files, all green.** App boots clean.
- **Next:** Phase 6 (generalize to more notes + note framework) — or deferred policy/LLMWhisperer
  once real docs arrive; Phase 8 QA at the end.

### 2026-06-03 — Flagged-item reasons: LLM-explained (grounded), rule-based fallback
- `validation/controls.explain_flagged_items(report, api_key)`: a **key-gated, batched** LLM pass
  that rewrites each flagged item's `reason` with a context-aware plain-English explanation,
  **grounded in the deterministic finding** (control name + item facts). The control VERDICT stays
  deterministic — the LLM only explains, never re-judges. One call for all items (cap 60). Falls
  back to the deterministic reason with no key / on failure.
- **Why (user's reasoning):** fixed reason strings won't generalize across arbitrary data and the
  future 40+-note expansion; LLM-explained findings do. Logged the bigger structural need —
  **note-agnostic controls/compute driven by per-note config** — in the plan (Phase 6+).
- **UI:** flagged-items expander now notes whether reasons are "AI-generated from the deterministic
  findings" or "rule-based", reinforcing that the AI explains, never decides the verdict.
- Verified live (L4-only orphans → grounded AI explanation referencing the exact txn/holding).
  Orchestrator stays LLM-free; 31 tests green; app boots clean.

### 2026-06-03 — Confidence: every flagged item now explains WHY
- `validation/controls.py`: each flagged item is now a structured dict carrying a plain-English
  **`reason`** (plus identifying fields), not a bare ID. Covers all controls — orphan transactions
  (which holding/txn/type + why), classification gaps, malformed journals, duplicate IDs, negative
  carrying values. UI expander renders the items as a table with the reason column ("Show N flagged
  item(s) — and why"). Verified e.g. orphan: holding AC-001 / txn INC-001 / income / "...not in the
  sub-ledger — usually a prior-period position not uploaded, or a mistyped Holding_ID." 31 tests green.

### 2026-06-03 — Optional LLM narrative over the confidence controls
- Added `validation/controls.narrate_confidence(report, api_key)`: a **key-gated, best-effort**
  plain-English summary of the ALREADY-evaluated controls. Strictly a presentation layer — the
  prompt forbids changing/re-judging any status, inventing numbers, or doing math (on top of the
  global robust system prompt). Returns "" on any failure.
- **Kept the orchestrator LLM-free:** narration runs in the UI layer (`_run`), not `_build`, and is
  stored on `Note5Result.confidence_narrative` (default ""). Deterministic tests are unaffected.
- **UI:** Confidence tab shows "🤖 AI summary: …" above the ✅/⚠️/❌ controls, with a caption
  clarifying the verdicts are deterministic and the AI only narrates them.
- Verified live on the sample (High confidence) — the summary accurately described all controls
  without altering any verdict. 31 tests still green; app boots clean.

### 2026-06-03 — Phase 4b: production validation WITHOUT an answer key
- **Why:** in the real use case the user uploads **L4 only** and we *generate* L1 — there is no
  expected L1 to reconcile against. So validation can't be "compare to ground truth"; trust must
  come from **internal accounting controls** (user insight).
- **Confidence engine** (`validation/controls.py` `run_controls` → `ConfidenceReport`): completeness
  (orphan transactions; classification coverage), **double-entry integrity** (GL journals),
  **sub-ledger ↔ GL postings** tie-out, **no duplicate transaction IDs**, **no negative carrying
  values**. Overall level = High / Medium / Low. No external answer key needed.
- **Fixed the misleading comparison:** `build_reconciliation` no longer compares uploads to the
  bundled-sample's config ground truth — it reconciles **only against levels stated in the upload**
  (L1 BS_Line / L2 5.1). A real holdings upload now produces an **empty** reconciliation report
  (correct) and is judged by the confidence report instead.
- **UI:** header banner now shows "Reconciled to stated FS" when an answer key was uploaded, else
  **"Confidence: High/Medium/Low — N controls passed."** New **"Confidence"** tab lists each control
  with ✅/⚠️/❌ and drill-down into flagged items. `Note5Result.confidence` added.
- **Tests:** `tests/test_controls.py` — sample passes all controls (High); a real holdings upload
  is NOT compared to AMNB (empty reconciliation report); L4-only flags orphan income txns (Medium).
  Updated `test_validation` (no ground-truth section). **31 tests across 8 files, all green.**
- **Next:** Phase 5 (exports) — or deferred policy/LLMWhisperer once real docs arrive.

### 2026-06-03 — Phase 4 (core): validation harness & audit trail
- **Multi-level reconciliation** (`validation/reconcile.py` `build_reconciliation`): compares the
  computed L1 against the values **STATED IN THE UPLOADED DATA** — at L1 (BS_Line face table) and
  L2 (5.1 classification summary) — plus a config ground-truth backstop. Per-level MATCH/variance
  sections. Data-driven, not just hardcoded. (Old `reconcile_l1` kept for back-compat.)
- **Audit trail** (`validation/audit.py` `build_audit_trail`): traces every bucket → its L3
  holdings → the L4 transactions (purchase/sale/income/MtM/amortisation) that reference each
  holding by Holding_ID. Full drill-down from an FS number to source rows.
- **UI**: Reconciliation tab now shows all stated levels with ✅/⚠️ badges; new **"Audit trail"**
  tab with bucket → holdings table → per-holding transaction drill-down (two selectboxes).
- `Note5Result` gains `reconciliation_report` + `audit`.
- **Tests:** `tests/test_validation.py` — stated L1/L2 sections present; stated-L1 variances match
  (FVTPL MATCH, FVOCI +100k, AC −59.5k); audit traces FVTPL→9 holdings→TPL-001 purchase+MtM.
  **28 tests across 7 files, all green.** App boots clean.
- **Still deferred from Phase 4:** editable routing map (needs compute to be routing-driven — pairs
  with AI codegen); per-level reconciliation against stated L3 holdings (we reconcile L1/L2).
- **Next:** Phase 5 (Excel/PDF export) or revisit deferred policy/LLMWhisperer once docs arrive.

### 2026-06-03 — Consolidated all deferred/extension work into one tracker
- Reworked `DEVELOPMENT_PLAN.md` → **"Deferred & extension work — SINGLE SOURCE OF TRUTH"**:
  groups leftovers by the ✅-done phase they extend (Phase 1: AI codegen; Phase 2: editable
  routing map + AI schema mapping; Phase 3: multi-standard selector, arbitrary-policy hardening,
  LLMWhisperer/DOCX/PDF-as-data) plus upcoming-phase items (audit drill-down→4, exports→5, more
  notes/real-FS structure→6). Added two items that audit revealed were untracked: **editable
  routing map** (Phase 2 exit said reviewable *and* editable — only reviewable shipped) and
  **arbitrary-policy hardening**. Added ✅/◀NEXT status markers to phase headers.

### 2026-06-03 — Honesty check + plan updates for deferred work
- **UI honesty pass:** removed the non-working **Scope** controls ("Generate entire FS" checkbox +
  Notes multiselect) → static "Note 5" caption; removed **DOCX** from the policy uploader (parser
  doesn't support it); softened the policy caption to reflect it needs an API key + only affects
  unclassified data. Export buttons remain visibly disabled. No control now implies it works when
  it doesn't.
- **Plan updates** (`DEVELOPMENT_PLAN.md`): Phase 3 marked done with **deferred extensions**
  recorded — multi-standard selector (IFRS 9/SOCPA/US GAAP), arbitrary/customer-specific policy
  hardening, and complex/scanned/DOCX policy docs via **LLMWhisperer**. Added **Phase 8 — End-to-end
  QA with synthetic multi-format test data** (the user-requested "make many test files" pass).
  Added a **Deferred backlog** section mapping every honesty-check finding to its phase.
- **Action needed from user:** provide real accounting-policy documents (PDF/DOCX) so we can test
  extraction quality and build/validate the LLMWhisperer + arbitrary-policy path.
- Tests still green; app imports clean.

### 2026-06-03 — UI: removed non-functional "Accounting standard" dropdown
- The sidebar "Accounting standard" selectbox (IFRS 9 / US GAAP / SOCPA) was **cosmetic** — its
  value was discarded; the engine always used IFRS 9. Per user decision, removed it to avoid
  implying functionality that isn't there. Replaced with a static caption stating the basis
  ("IFRS 9 — uploaded policy rules take precedence"). Multi-standard support (esp. US GAAP
  Trading/AFS/HTM) is deferred until genuinely needed.

### 2026-06-03 — Phase 3 COMPLETE: policy enforcement & classification
- **Classification engine** (`policy/classify.py`): assigns FVTPL/FVOCI/Amortised Cost to a
  security from its description. **Hybrid**: uploaded **policy rules win**; otherwise **IFRS 9
  inference** heuristics (held-for-trading→FVTPL, funds/REIT→FVTPL, bills/hold-to-collect→AC,
  shares→FVOCI election, sukuk/bonds→FVOCI). Every decision carries a **reason + source**
  ("policy" | "IFRS 9"). `normalize_classification` maps FVIS/FVTPL/AC/Amortized spellings to
  canonical buckets.
- **Applied only where needed** (`apply_classification`): fills MISSING/blank `Classification`
  on tables that have a description column AND a position/transaction value column
  (Carrying/Total_Cost/Proceeds/MtM) — so GL journals / EIR schedules are not mis-classified.
  **Stated classifications are never overridden** (data is authoritative). No-op on the fully
  classified sample.
- **Wired end-to-end**: `_build`/`run_note5_from_files` take `policy_rules`; `Note5Result.
  classifications` carries the audit trail. UI extracts policy rules from an uploaded doc first
  (key-gated), passes them in, and shows a **"🏷️ Classification decisions"** panel
  (security · classification · source · reason). No policy → IFRS 9 fallback, clearly labelled.
- **Tests:** `tests/test_classification.py` (IFRS 9 inference; policy override beats IFRS 9;
  label normalization; fills-only-missing; missing-classification data still computes correct
  L1; sample untouched). **25 tests total across 6 files, all green.** App boots clean.
- **Next:** Phase 4 (validation harness & audit trail — full L4→L2→L1 reconciliation, drill-down
  to source + generated code).

### 2026-06-03 — Phase 2 COMPLETE: large-file streaming + opening balances
- **Large-file streaming** (`ingestion/loaders.py` + `compute/streaming.py`): a single large
  holdings CSV (>5 MB) is read in row **chunks** and aggregated incrementally — a 1M+ row
  sub-ledger never loads fully into memory. `run_note5_from_files` auto-routes a large single
  holdings CSV to the streamed path; same `CascadeResult` shape, so reconcile/UI are unchanged.
- **Opening-balance inputs** (`cascade._opening_by_bucket` / `_movements_by_bucket`): when an
  opening-balances table (`Classification` + `Opening_000`, aliases supported) is provided with
  L4, the engine computes **closing = opening + net L4 movements** (+purchases −sales +MtM
  +amortisation) per classification → a **complete (non-partial)** Note 5 from transactions.
  New "opening balances" role in the routing map. UI shows the method note.
- **Tests:** `tests/test_phase2_complete.py` (streaming reads in ≥3 chunks; streamed totals
  match expected; large file auto-routed to streaming; opening+L4 ties out & clears partial).
  **19 tests total, all green.** App boots clean.
- **Phase 2 is DONE.** Next: Phase 3 (policy enforcement: feed policy rules into classification,
  IFRS 9 fallback) — and the cross-cutting note-framework groundwork for FVIS/Domestic-Intl
  structure seen in the real Bank AlJazira FS.

### 2026-06-03 — Phase 2 (part 3): hardening, foreign columns, robust prompts
- **Detector hardened** (`table_detect._segment_block`): splits **adjacent tables with no blank
  line** via numeric-fraction header detection (≤0.15 = header). Sample still parses to 18 tables
  (no regression).
- **Foreign-column normalization** (`ingestion/normalize.py`): alias map renames unfamiliar
  column names to canonical fields; conservative (exact normalized match; never clobbers existing
  columns). Integrated into the collector pipeline (detect → tag → normalize → level).
- **AI column mapping** (`routing.map_columns_with_ai` / `ai_normalize_tables`): optional,
  key-gated pre-pass that maps truly foreign schemas onto canonical fields (profiles only). Wired
  via `run_note5_from_files(files, api_key=...)`; UI passes the key.
- **Robust LLM prompts:** a strong shared **system prompt** (`llm/client.DEFAULT_SYSTEM`) now
  applies to **every** model call — forbids inventing figures, forbids arithmetic on amounts,
  enforces JSON-only output, prefers "unknown" over guessing. Live GPT-5.1 call re-verified.
- **Docs:** added the "How ingestion works" design section (multi-table/multi-sheet/any-level/
  foreign columns) per request.
- **Tests:** `tests/test_hardening.py` (adjacent-table split; alias mapping; sample not clobbered;
  renamed-columns sample still ties to 24,810,000-basis totals). **15 tests total, all green.**
- **Still pending in Phase 2:** large-file (1M+) streaming; opening-balance inputs.

### 2026-06-03 — Phase 2 (part 2): value-routing map
- **Routing map** (`routing/router.py`): classifies **every** detected table by **level + role +
  note** across all sources — deterministic, by column signature (`detect_role`,
  `build_routing_map`). On the sample it labels all **18 tables** with zero "unclassified"
  (sub-ledger, purchases, sales, income, MtM, EIR, ECL, GL journal, the five L2 disclosure
  tables, the four L1 face tables, and the cross-reference map). Flags which tables the cascade
  actually **uses** vs which are outputs (L1 face) / not-yet-consumed (ECL, GL).
- **Optional AI enrichment** (`enrich_routing_map_with_ai`): when a key is present, GPT-5.1
  classifies any tables the rules can't (unknown/foreign schemas), from profiles only — never
  blocks the deterministic map. Wired into the UI processing step.
- **UI**: new **"🗺️ Routing map"** expander shows Source · Table · Level · Role · Feeds · Used · By
  (rule/ai), so the user can see exactly how each uploaded table was interpreted.
- `Note5Result` now carries the `routing` map; `routing/models.py` RoutingEntry relaxed
  (level optional, adds role/used_in_cascade/confidence/origin).
- **Tests:** `tests/test_routing.py` (4) pass; all prior tests still green (11 total).
  `scripts/show_routing.py` prints the map.
- **Still pending in Phase 2:** large-file (1M+) streaming; AI codegen for arbitrary-schema
  column mapping (validated vs the deterministic reference); opening-balance inputs.

### 2026-06-03 — Phase 2 (part 1): heterogeneous, multi-source ingestion
- **Excel + multi-sheet + multi-file** ingestion: `ingestion/collect.py` reads every sheet of
  every uploaded CSV/XLSX, runs table detection per sheet, tags each table with source
  file + sheet, and combines them. `table_detect.read_sheets_from_excel` added.
- **Level detection** (`detect_level` / `apply_level_detection`): infers L1/L2/L3/L4 from
  column signatures when section banners are absent (e.g., a file containing just the L4 rows).
- **Cross-source merge**: `cascade._collect_by_cols` concatenates ALL tables sharing a
  signature, so holdings/purchases split across files or sheets are merged before aggregation.
- **UI**: upload **multiple** CSV/Excel files (any level, multi-sheet, multi-table); results
  show "ingested N tables from M files / K sheets" + the sub-ledger source.
- **Provenance proof** (`scripts/verify_l4_provenance.py`): traces each L4-only holding to its
  exact source row (purchase cost / MtM FV / amortisation). Confirms numbers are computed from
  rows, NOT hallucinated and NOT read from the stored ground truth (computed 9,975,973 ≠ stored
  24,810,000). The cascade has **no LLM in it** — pure deterministic Pandas.
- **Tests:** `tests/test_multisource.py` (Excel multi-sheet == CSV; L3 split across 2 files
  ties out; bannerless level detection) all pass; Phase 1 tests still green; app boots clean.
- **Real FS studied:** read Bank AlJazira Q1-2025 Note 5 (`scripts/find_note5_in_pdf.py`,
  pp.15–16). Real structure = 5.1 classification (FVIS/FVOCI/AC, **gross→allowance→net**,
  3 periods) + 5.2 by-type split **Domestic/International**. Note: real FS uses **"FVIS"**
  (Fair Value through Income Statement) where our sample says FVTPL. Captured for the
  note-framework / Phase 6 work.
- **Still pending in Phase 2:** large-file (1M+ row) streaming; reviewable value-routing-map
  UI; AI codegen (validated against the deterministic reference); opening-balance inputs.

### 2026-06-03 — Phase 1: real L4→L3→L2→L1 cascade + UI redesign
- **`ingestion/table_detect.py`** — parses the stacked multi-table CSV into labeled
  L1/L2/L3/L4/XREF tables (blank-row blocking + banner/title peeling). On the sample it
  correctly finds **18 tables** (L1:4, L2:5, L3:1, L4:7, XREF:1).
- **`compute/cascade.py`** — computes the cascade: L3 holdings → L2 classification summary →
  L1 face lines (folding "FVOCI Equity" into FVOCI), plus L4 transaction aggregates
  (purchases/sales/income/MtM) to prove L4 is consumed.
- **`validation/reconcile.py`** — compares computed L1 to stated ground truth, line by line.
- **`compute/note5.py`** — orchestrator: detect → cascade → reconcile → `Note5Result`.
- **Key result (honest):** FVTPL **ties exactly** (2,780,000). FVOCI **+100,000** and AC
  **−59,500** variances are surfaced automatically — these are real reconciling items in the
  sample (SAMA-bills accretion rounding; a genuine corporate-bond inconsistency the tool
  *caught*). This is the intended behavior: compute from the lowest level, surface variances.
- **UI fully redesigned** (`ui.py` + `.streamlit/config.toml`): hero header, L4→L3→L2→L1 flow
  strip, metric cards with variance deltas, tabs (L1/L2/L3/L4/Reconciliation), colored
  MATCH/VARIANCE styling, bundled-sample loader. AI routing/policy are optional and never
  block the local cascade.
- **Tests:** `tests/test_cascade.py` (4 tests) **all pass**; `scripts/run_cascade.py` CLI for
  quick inspection. Streamlit boots cleanly headless.
- **Deliberately deferred:** AI *generating* the Pandas (Phase 2 codegen) — the deterministic
  cascade here is the known-correct reference the generated code will be validated against.
  Excel/multi-sheet inputs (Phase 2); exports still disabled (Phase 5).
- **UI refinements (user feedback):** API key is now read **silently from `.env`** (no key
  input in the app); the model name is no longer shown anywhere; added a plain-English
  "Why are there differences?" explainer in the Reconciliation tab.
- **Dynamic cascade entry (pulled forward from Phase 2, user-driven):** tables are now found by
  **column signature** (not section banners), and if no L3 sub-ledger is present the engine
  **rebuilds a best-effort L3 from L4** (latest MtM fair value for FVTPL/FVOCI; cost + EIR
  amortisation for AC; else purchase cost). L4-only files now work instead of crashing, and are
  clearly flagged **partial** (they exclude opening balances — an accounting reality, not a bug).
  Friendly error (no traceback) when neither L3 nor usable L4 is found. Verified via
  `scripts/test_l4_only.py` (16 holdings reconstructed; partial total surfaced).
  Still TODO in Phase 2: accept opening balances / L1–L2 uploads, Excel/multi-sheet.
- **Next:** Phase 2 — heterogeneous ingestion (Excel, multi-sheet, multi-table generalization,
  level detection, large files) + AI codegen validated against this reference.

### 2026-06-03 — Phase 0: foundation built
- Created `.venv` (Python 3.14.3); installed deps (streamlit 1.58, pandas 3.0.3, openai 2.40,
  pydantic 2.13.4, etc.). `git init` on branch `main`; added `.gitignore` + `.env.example`.
- Moved sample CSV → `sample_data/`.
- Built the `ai_accountant/` package: `config`, `llm/client` (GPT-5.1 wrapper, JSON mode +
  retries), `ingestion/` (profiler migrated; table_detect/loaders stubs), `routing/`
  (pydantic models + migrated triage), `policy/` (migrated parser + rules), and
  `compute/`/`validation/`/`export/` stubs for later phases.
- `app.py` is now a thin launcher; old `engine.py` is a deprecation shim re-exporting new paths.
- Refactored the full Streamlit UI into `ai_accountant/ui.py`.
- Added `scripts/smoke_test.py`. **Structural smoke test PASSES** (clean imports; model = gpt-5.1).
- Secured the OpenAI key in gitignored `.env`; scrubbed `.env.example` back to placeholder.
- **Live GPT-5.1 JSON call verified** (`chat.completions` + JSON mode works; no Responses API change needed). **Phase 0 COMPLETE.**
- **Next:** begin **Phase 1** (L4→L3→L2→L1 cascade for Note 5).

### Note on optional tooling (2026-06-03)
- User has an **LLMWhisperer** API key. Not needed for Phases 0–2 (core inputs are CSV/Excel
  parsed with pandas). Potentially useful in **Phase 3** if policy PDFs (or PDF-based financial
  data) are complex/scanned and PyPDF2's plain-text extraction proves insufficient — LLMWhisperer
  preserves layout/tables for LLM consumption. Revisit then.

### 2026-06-03 — Planning complete
- Read `project_notes.md`, `app.py`, `engine.py`, and the sample `AMNB_Note5_All_Levels.csv`.
- Captured full project understanding → `PROJECT_UNDERSTANDING.md`.
- Confirmed build decisions with the user (see Decisions log).
- Authored the phased `DEVELOPMENT_PLAN.md` (Phases 0–7).
- Created this living `documentation.md`.
- **Next:** begin **Phase 0 — Foundation & scaffolding** (on user's go-ahead).
