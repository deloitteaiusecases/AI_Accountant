# AI Accountant — Development Plan

A phased plan from current POC to a working, auditable Note-5 generator that scales to messy,
real-world inputs. Built per the decisions below.

## Decisions driving this plan (2026-06-03)
- **Model:** OpenAI **GPT-5.1** (the app's LLM). **Claude usage for building:** main session
  stays on **Opus** for design/review; **delegate only LARGE/parallel routine batches to Sonnet
  sub-agents** (where savings beat overhead). No manual toggling.
- **Build order:** **Thin end-to-end slice first** (real Note 5 on the sample file), then scale.
- **Sandbox:** **Lightweight in-process guardrails now** (import whitelist, no I/O, timeout),
  full subprocess/OS isolation deferred to pre-deployment hardening.
- **Codebase:** **Restructure into clean modules** (existing `app.py`/`engine.py` folded in).
- **Deploy target:** **Local desktop only for now** — simple `.env`/UI secrets.

## Guiding principles
1. **Build the hierarchy up, one level at a time:** L4 → L3 → L2 → L1. We never jump straight
   from raw transactions to the final table — each level is computed from the one below it.
   - **L4** (raw transactions) → aggregate per security → **L3** (sub-ledger: holdings per ISIN)
   - **L3** → roll up by classification/category → **L2** (Note 5 disclosure tables 5.1–5.5)
   - **L2** → map to face lines → **L1** (final Balance Sheet / P&L / OCI / Equity table)
   - Each level is **validated against the sample's ground truth** before feeding the next.
   - **The entry point is dynamic — the user may upload data at ANY level (L1/L2/L3/L4).**
     The system must (a) detect each uploaded table's level, (b) compute any *missing* higher
     levels upward from the lowest data available, and (c) when more than one level is uploaded,
     **cross-validate** computed vs uploaded and surface the variance.
   - **Conflict rule: an uploaded level is authoritative (it wins) over a computed one.** If the
     user uploads L2 directly, that L2 is the value of record even when our L4→L2 computation
     differs — we still **display the variance as a flag** for transparency/audit, but don't override
     their number. We only *compute* a level when the user hasn't uploaded it.
2. **The LLM never sees raw rows** — only profiles (headers, sample rows, sheet/table maps).
3. **Every number is traceable** — to its source level/table/cell and the exact code that produced it.
4. **Validate against ground truth** — the sample's L1–L3 + reconciliation map gate every result.
5. **Determinism where possible** — pin generated scripts per schema signature; reuse, don't regenerate.

---

## Product end-state (POST-POC) — intelligent multi-note FS from an UNLABELED file set
> POC scope is **Note 5 only**. This section records the full target so we build toward it.

When complete, the user uploads a **set of files with no indication of which note they belong to**,
and the system assembles the **whole Financial Statement** itself:
1. **Ingest** (built): detect all tables across all files/sheets, normalize columns, detect levels.
2. **Note dispatch (THE new intelligence — future):** for every detected table, decide *which
   note(s) it feeds*, by matching its **profile** (headers + sample rows) against the **catalog of
   `NoteDefinition`s**. Rule signatures per note + LLM reasoning over profiles (never raw rows),
   since the documents are unlabeled and messy. Output = a per-note data bundle.
3. **Per-note compute** (Note 5 built; others per-note) on each bundle.
4. **Per-note validation/confidence** (pattern built).
5. **Assemble the full FS** from all notes, with **cross-note consistency** (each note's L1 line
   ties to the FS face; shared figures agree across notes).
6. **Export** the complete FS.

**What already points at this:** `NoteDefinition` is the catalog the dispatcher matches against
(each note will gain a data *signature/description*); the current single-note routing map is the
seed of the dispatcher; the profiles-only + LLM design is how dispatch stays intelligent on
unlabeled data. **Not built now** — POC is Note 5.

---

## Target module structure (built up across phases)
```
ai_accountant/
  app.py                  # Streamlit entry (thin — calls into modules)
  config.py               # constants, model name, paths, thresholds
  llm/
    client.py             # GPT-5.1 wrapper: JSON mode, retries, logging
  ingestion/
    profiler.py           # profile files → sheets → tables (headers + sample rows)
    table_detect.py       # detect MULTIPLE stacked tables within one sheet
    loaders.py            # chunked/streamed reads for 1M+ row tables
  routing/
    models.py             # typed schema: Profile, TableProfile, RoutingMap
    router.py             # LLM builds file→sheet→table→role→note→calc map
  policy/
    parser.py             # PDF/TXT → text (PyPDF2)
    rules.py              # LLM extracts classification mapping rules
  compute/
    codegen.py            # LLM generates Pandas from routing map + profiles
    sandbox.py            # guardrailed execution (whitelist, no I/O, timeout)
    note5.py              # Note 5 orchestration + expected output spec
  validation/
    reconcile.py          # compare computed L2/L1 vs ground truth; L4→L2→L1 ties
  export/
    excel.py  pdf.py      # openpyxl / reportlab exports of computed results
tests/                    # ground-truth + unit tests
sample_data/              # AMNB_Note5_All_Levels.csv (moved here)
```

---

## Phase 0 — Foundation & scaffolding  ✅ DONE
**Goal:** clean, runnable project skeleton on GPT-5.1. No new features yet — just a solid base.
**Model:** Opus (structure) → Sonnet (mechanical moves).
**Tasks:**
- Create venv; pin `requirements.txt`; add `.env` (API key) + `.env.example`; `git init` + `.gitignore`.
- Move `AMNB_Note5_All_Levels.csv` → `sample_data/`; update references.
- Build `ai_accountant/` package per structure above (empty/stub modules).
- `llm/client.py`: GPT-5.1 wrapper (JSON mode, retry, error handling, basic logging).
- Migrate existing `engine.py` functions into `ingestion/profiler.py`, `policy/`, `routing/router.py`
  (rename `ai_triage`), updating `model="gpt-4o"` → GPT-5.1.
- `app.py` becomes a thin entry importing from modules; preserve current UI.
**Exit criteria:** app launches; GPT-5.1 smoke test returns valid JSON; existing UI behaves as before.
**Verify:** `streamlit run ai_accountant/app.py`; run a one-shot LLM smoke-test script.

## Phase 1 — Thin end-to-end slice: the full L4→L3→L2→L1 cascade for Note 5 ⭐ first working product  ✅ DONE
**Goal:** From the sample's **L4 only**, compute the whole hierarchy up to the final L1 table —
**L4 → L3 → L2 → L1** — validating each level against ground truth, and show real (not hardcoded)
tables in the UI.
**Model:** Opus (cascade + codegen + reconciliation design), Sonnet (UI display).
**Tasks:**
- `table_detect.py`: split `AMNB_Note5_All_Levels.csv` into its stacked tables (L1–L4 + xref).
- `router.py`: LLM identifies which detected table holds the L4 transactions for Note 5.
- `compute/`: generate + guardrail-run Pandas for each step of the cascade:
  - **L4 → L3:** aggregate transactions per security (ISIN) → sub-ledger holdings.
  - **L3 → L2:** roll up holdings by classification → Note 5 tables (5.1–5.5).
  - **L2 → L1:** map disclosure tables to the FS face lines.
- `validation/reconcile.py`: validate **at every level** against the sample's L3/L2/L1, ending with
  L1 totals (FVTPL 2,780,000 · FVOCI 12,350,000 · AC 9,680,000 · **Total 24,810,000** SAR '000).
- Wire each level into its UI tab (real numbers + per-level pass/fail badge); remove `time.sleep` stub.
**Exit criteria:** UI shows computed L3, L2, and final L1 tables that match ground truth at every level.
**Verify:** upload the sample via the UI end-to-end with a live GPT-5.1 key; all level reconciliations green.

## Phase 2 — Robust heterogeneous ingestion (scale + mess)  ✅ DONE
**Goal:** Handle the real input reality: 15–20+ files, CSV+Excel, multi-sheet, multi-table-per-sheet,
1M+ rows, mixed/L4-only levels.
**Model:** Opus (detection + routing logic), Sonnet (loaders, plumbing).
**Tasks:**
- Generalize `table_detect.py` (header/blank-row/section-title heuristics) across arbitrary sheets.
- `profiler.py`: walk every sheet of every workbook; profile each detected table separately.
- **Level detection:** classify each detected table as L1/L2/L3/L4 (LLM from profile + signals).
- **Dynamic cascade entry:** compute only the levels the user did *not* upload, building upward to L1
  from the lowest available data; uploaded levels are used as-is.
- **Cross-level reconciliation:** when multiple levels are uploaded, validate computed vs uploaded at
  each shared level and surface the variance — but the **uploaded level is authoritative (wins)**;
  the variance is shown as a flag, not auto-corrected.
- `loaders.py`: chunked/streamed Pandas reads so large files never load fully when avoidable.
- `router.py`: build the full **value-routing map** across many files/tables; make it **user-reviewable**
  in the UI before compute.
**Exit criteria:** a synthetic multi-file / multi-table / large dataset profiles + routes correctly;
routing map is reviewable and editable.
**Verify:** craft fixtures (multi-sheet workbook with stacked tables + a large CSV); inspect routing map.

## Phase 3 — Policy enforcement & accounting rules  ✅ DONE (core)
**Goal:** Make classification respect uploaded policy when present; fall back to IFRS 9 otherwise.
**Delivered:** classification engine (policy rules win → IFRS 9 fallback), explainable decisions
(reason + source), applied only to unclassified position data, wired through the UI.
**Deferred to a later phase (tracked here so we don't forget):**
- **Multi-standard selector** (the removed "Accounting standard" dropdown): bring back a *working*
  IFRS 9 / SOCPA / US GAAP selector. IFRS 9 + SOCPA share rules (SOCPA ≈ IFRS-as-endorsed-KSA);
  US GAAP needs its own Trading/AFS/HTM ruleset (and likely its own bucket labels). Thread the
  chosen standard through `apply_classification` → `classify`.
- **Arbitrary / customer-specific policies:** today any uploaded policy's extracted rules already
  drive classification. Harden this so a *completely different* policy reliably reshapes the
  calculations (broader rule extraction, conflict handling, validation against the policy).
- **Complex / scanned / DOCX policy docs:** PyPDF2 handles clean text PDFs only. Add **LLMWhisperer**
  (layout/OCR extraction) behind the existing `parse_policy_document` interface for messy or
  image-based policies, and DOCX support. **Needs real policy documents to build + test against.**
**Exit criteria (met for core):** policy vs no-policy both produce correct, explained classifications.

## Phase 4 — Validation harness & audit trail  ✅ DONE (core)
**Goal:** Turn validation into a first-class, drill-down audit feature.
**Delivered:** multi-level reconciliation vs values stated in the data (L1 + L2) with MATCH/variance
badges; audit drill-down (bucket → L3 holdings → L4 transactions) in a new UI tab.
**Still deferred:** editable routing map (pairs with routing-driven compute / AI codegen);
per-level reconciliation against stated L3 holdings.
**CRITICAL deferred — production validation WITHOUT an answer key (Phase 4b):** the real user
uploads **L4 only** and we *generate* L1 — there is no expected L1 to reconcile against. So
validation must shift from "compare to ground truth" to **internal accounting controls**:
  - **Sub-ledger ↔ GL tie-out** — net GL journal postings per investment account = computed movement.
  - **Roll-forward vs direct aggregation** — closing computed two independent ways must agree.
  - **Double-entry integrity** — every journal's debits = credits.
  - **Completeness** — no orphan transactions, all holdings classified, every row consumed.
  - **Cross-source consistency** + **anomaly/sanity flags** (negatives, bad dates, dup IDs).
  Output = a **confidence/quality report** ("N controls passed, M items to review"), not pass/fail-
  vs-truth. **Also fix:** gate the config ground-truth backstop to the bundled sample only — never
  compare a real upload to the AMNB sample's numbers.
**Model:** Opus.
**Tasks:**
- Full reconciliation across L4→L2→L1 using the sample's cross-reference map (all MATCH).
- Audit drill-down: click a Note 5 number → see source table/cell + the exact generated Pandas.
- Persist generated scripts pinned per schema signature (reuse + audit log).
**Exit criteria:** reconciliation report all-green on sample; every figure traces to source + code.
**Verify:** open the audit view; spot-check a figure back to L4 rows.

## Phase 5 — Exports  ✅ DONE
**Goal:** Download real computed Note 5 as Excel and PDF.
**Delivered:** `export/excel.py` (openpyxl) writes a multi-sheet workbook (L1 / L2 / L3 /
Reconciliation / Confidence); `export/pdf.py` (reportlab) renders an audit-style PDF (L1 face,
L2 summary, reconciliation with variance highlighting, confidence verdict + controls + AI summary).
Both wired to real `st.download_button`s (replacing the disabled placeholders).
**Exit criteria met:** exported values match the on-screen computed numbers (tested).

## Phase 6 — Generalize to more notes + polish  🟡 IN PROGRESS (part 1 done)
**Goal:** Prove the pipeline generalizes beyond Note 5; productionize quality.
**Model:** Opus (note framework), Sonnet (scaffolding, tests).
**Part 1 — DONE:** `notes/` package — `NoteDefinition` (buckets, classification map, value column,
FS-face labels, GL accounts) + registry + `get_note`. Cascade / reconcile / controls now read the
active note's definition instead of hardcoding Note 5 (behavior byte-identical; 38 tests green).
**Still to do — DEFERRED to POST-POC (POC is Note 5 only, per user 2026-06-04):**
- **Per-note compute pipeline:** the compute logic is still investment-shaped (purchases→holdings
  →buckets); other notes need their own steps keyed off the NoteDefinition.
- **Note dispatcher** (see "Product end-state" above): match each uploaded table to the note(s) it
  feeds, from profiles, across the whole note catalog — the core intelligence for the finished
  product. Generalizes the current single-note routing map.
- **Note-aware routing/classification** (currently Note-5 column signatures).
- **Full-FS assembly + cross-note consistency.**
- Scaffold each new note end-to-end — **each needs its own sample data** (like the policy docs).
- UX polish; robust error/empty states.
**Exit criteria (post-POC):** a second note works end-to-end via the same pipeline; tests pass.
**POC-remaining (Note 5):** Phase 8 QA + the deferred policy/LLMWhisperer once real docs arrive.

## Phase 7 — Hardening (deferred — pre-deployment only)
**Goal:** Production-grade safety/perf when we move off local desktop.
**Tasks:** full subprocess/OS-level sandbox; secrets management; performance tuning; deployment config.
**Trigger:** revisit when deploy target changes from "local desktop only."

## Phase 8 — End-to-end QA with synthetic test data (final, user-requested)  🟡 STARTED
**Status:** `scripts/qa_suite.py` generates + runs a 10-scenario multi-format battery (CSV/Excel,
multi-file, multi-sheet, multi-table, adjacent, foreign columns, L4-only, L4+opening, missing
class, 300k-row streamed) — **0 errors**. Policy pipeline validated on real + template policy docs.
Remaining: turn key scenarios into permanent pytest assertions; broaden adversarial/edge cases.
**Goal:** After all feature phases, exhaustively exercise every capability with realistic,
adversarial inputs — the "make many test files" pass the user asked for.
**Tasks:**
- Generate a battery of synthetic inputs: multiple CSVs **and** Excel; data spread across many
  files; multi-sheet workbooks; **multiple tables per sheet** (blank-separated AND adjacent);
  every entry level (L1/L2/L3/L4) and mixes; foreign column names; large (1M+ row) files;
  L4-only and L4+opening; missing classifications (policy vs IFRS 9); messy/edge cases.
- Run each through the full pipeline; assert correctness and that variances/partials are flagged.
- Capture any defects found → fix or log.
**Exit criteria:** the whole feature set verified end-to-end on diverse, messy, large inputs.

---

## Deferred & extension work — SINGLE SOURCE OF TRUTH (updated 2026-06-03)
This is the one place that lists everything left over from phases marked ✅ DONE (where only the
*core* shipped and some work was extended), plus items that belong to phases not yet reached.
Nothing here is silently broken in the UI — each is labelled/disabled so it never implies it works.
"→ Phase N" = where it gets completed.

### Left over from Phase 1 (cascade) ✅ core done
- **AI codegen execution** — the "AI writes the Pandas and we run it" strategy. The cascade is
  **deterministic** today (correct, tested); using the LLM to *generate* the transformation code,
  validated against this deterministic reference, is still pending. → **Phase 4 / 6 follow-up.**

### Left over from Phase 2 (ingestion) ✅ core done
- **Editable routing map** — the routing map is **reviewable** (read-only display) but not yet
  **editable** in the UI (Phase 2's exit criterion asked for both). User-correctable routing. → **Phase 4.**
- **AI codegen for arbitrary-schema mapping** — deterministic alias layer + optional AI column
  mapper exist; full LLM-generated mapping/codegen pairs with the item above. → **Phase 4 / 6.**

### Left over from Phase 3 (policy) ✅ core done
- **Multi-standard selector** (IFRS 9 / SOCPA / US GAAP) — removed (was cosmetic); bring back a
  *working* one. IFRS 9 + SOCPA share rules; US GAAP needs its own Trading/AFS/HTM ruleset. → **Phase 3 ext.**
- **Arbitrary / customer-specific policy hardening** — any uploaded policy's rules already drive
  classification; harden so a *completely different* policy reliably reshapes the calculations
  (broader extraction, conflict handling, validation vs the policy). → **Phase 3 ext.**
- **Complex / scanned / DOCX policy docs (LLMWhisperer)** — ⓘ PyPDF2 **validated on a real
  text-based bank PDF** (Bank AlJazira → 20 rules via the pipeline), so LLMWhisperer is only needed
  for **scanned/image/complex-layout** PDFs (none encountered yet) and DOCX. Add behind
  `parse_policy_document` when such a doc appears. → **Phase 3 ext.**
- **Arbitrary-policy hardening** — QA showed policy matching is exact-substring (brittle); needs
  fuzzy/semantic asset_type → security matching so a policy reliably reshapes calculations. → **Phase 3 ext.**
- **Streamed large-file confidence** — the streaming path skips internal controls (confidence
  "Unknown"); run controls on streamed aggregates too. → **Phase 4b ext.**
- **PDF-as-data ingestion** (tables *inside* PDFs as input data) — inputs are CSV/Excel today. → **Phase 3 ext / LLMWhisperer.**

### Left over from Phase 4 (validation) ✅ core done
- ~~**Production validation without an answer key (Phase 4b)**~~ → ✅ **DONE.** Confidence engine
  (`validation/controls.py`): orphan txns, classification coverage, double-entry, sub-ledger↔GL,
  duplicate IDs, negatives → High/Medium/Low. Ground-truth comparison now sample-only (real uploads
  judged by confidence, not the AMNB numbers). *Still to add later:* roll-forward (opening+flows vs
  aggregation) and cross-source consistency as extra controls.
- **Editable routing map** + **per-level reconciliation vs stated L3** → with AI codegen.

### Belongs to phases not yet reached (not deferrals — just upcoming)
- ~~**Audit drill-down** (number → source rows)~~ → ✅ **DONE in Phase 4** (bucket → holdings → L4 txns).
- **Generalize the controls/compute engine for 40+ notes (the big vision)** — today the cascade
  AND the internal controls are keyed to Note-5 column names (`Holding_ID`, `GL_Debit`, …). To scale
  to 40+ notes and assemble a full FS, the checks must become **note-agnostic**: generic controls
  ("every reference resolves", "debits = credits", "no duplicates") driven by a **per-note config /
  note-definition**. The LLM explanation layer (done now) already fits this — generic findings,
  LLM-explained. → **Phase 6 (note framework) and beyond.**
- ~~**Excel / PDF export**~~ → ✅ **DONE in Phase 5** (multi-sheet xlsx + audit-style PDF).
- **More notes / full-FS generation** — only Note 5 today; sidebar scope is a static caption. → **Phase 6.**
- **Real-FS Note 5 structure** (FVIS label, Domestic/International split, gross→net impairment). → **Phase 6.**

---

## How we track progress
- `documentation.md` is the **living log** — updated as each phase/sub-task lands (what, why, status).
- Open questions get raised whenever they arise, not just at phase boundaries.

## Open items to confirm at the relevant phase
- Phase 3 ext: **user to provide real accounting-policy documents** (PDF/DOCX, ideally a couple of
  different banks' policies) so we can (a) test PyPDF2 extraction quality and (b) build + validate
  the LLMWhisperer path and arbitrary-policy support against real content.
- Phase 4: audit granularity depth (line-item vs holding-level — likely both).
- Phase 6: which note to tackle second; how to handle the real-FS structure (FVIS terminology,
  Domestic/International split, gross→net impairment) seen in the Bank AlJazira Note 5.
- Phase 8: the user will drive the synthetic multi-format test-data pass once features are done.
