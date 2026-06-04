# AI Accountant — Documentation Log

> **Living document.** Updated as we move through development. It records what we've done,
> why, decisions made, and current status. Newest entries at the top of the Changelog.

## Project at a glance
AI-assisted tool that turns raw transactional data (**L4**) into **Financial Statement notes**,
starting with **Note 5: Investments, Net**. The LLM only ever sees file *profiles* (headers +
sample rows); local Pandas does the heavy compute. Target model: **OpenAI GPT-5.1**.

See `PROJECT_UNDERSTANDING.md` for full context and `DEVELOPMENT_PLAN.md` for the phased plan.

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

---

## Open questions / to confirm
- _(none blocking right now)_
- Phase 2: precise table-boundary detection heuristics — to validate on fixtures.
- Phase 3: which IFRS 9 default rules to encode for the no-policy fallback.
- Phase 6: which note to build second.

---

## Changelog
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
