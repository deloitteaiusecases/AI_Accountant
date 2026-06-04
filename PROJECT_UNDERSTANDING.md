# AI Accountant — Project Understanding & Advisory

> Status: **Understanding only.** This is a reference document, not an approval to start
> implementing. It records what the project is today, the key open architectural decisions,
> and the recommendation on the LLM code-execution question. No code is changed by this doc.

---

## Context — why this document exists

The goal was to read `project_notes.md` and the surrounding project, then ask enough
questions to understand the *whole* thing. This captures that understanding — based on the
notes, both source files (`app.py`, `engine.py`), and the sample data
(`AMNB_Note5_All_Levels.csv`) — so there's a single shared source of truth before build work.

---

## What the project is

An AI-assisted tool that turns **raw transactional data (L4)** into **Financial Statement
notes**, starting with **Note 5: Investments, Net** (modeled on Bank AlJazira Q1 2025).
The long-term goal is note-by-note automation of the full FS.

**Data hierarchy (the mental model the whole app is built around):**
- **L4** — raw transactions (purchases, sales, coupons, MtM, EIR, ECL, GL journals)
- **L3** — sub-ledger: aggregated holdings per security (ISIN-level)
- **L2** — note disclosure tables (e.g. Note 5.1–5.5)
- **L1** — face of the FS (Balance Sheet, P&L, OCI, Equity lines)

**Core principle:** the LLM never sees raw rows — only file *profiles* (headers + a few
sample rows). The heavy data work happens locally. This protects token limits, privacy,
and scalability.

## Tech stack
- **Backend/logic:** Python (Pandas)
- **Frontend:** Streamlit (may migrate later)
- **AI:** OpenAI **GPT-5.1** (an API key is available for live testing).
  ⚠️ The code currently hardcodes `model="gpt-4o"` in `engine.py` (lines 85 and 121) —
  these must be updated to GPT-5.1 when we build.
- **Libs (`requirements.txt`):** streamlit, pandas, openai, python-dotenv, openpyxl,
  reportlab, PyPDF2

---

## Current state of the code

### Built and working
| Area | Where | What it does |
|------|-------|--------------|
| Dashboard UI | `app.py` | Styled Streamlit app: upload zone, optional policy upload, sidebar (scope, accounting standard, API key), results tabs, export buttons |
| File profiling | `engine.profile_uploaded_csvs()` | Reads headers + first 5 rows of each CSV/Excel (keeps raw data away from the LLM) |
| Policy parsing | `engine.parse_policy_document()` | PDF/TXT → raw text (PyPDF2) |
| Policy → rules | `engine.extract_policy_rules()` | LLM turns policy text into JSON mapping rules (asset type → FVTPL/FVOCI/AC) |
| File triage | `engine.ai_triage()` | LLM picks which uploaded file(s) hold the relevant L4 data for a note |

### Stubbed / missing (the real work)
- **Phase 3 — the heart of the app:** AI generating Pandas transformations and executing
  them on L4 data. Currently a `time.sleep(1.5)` placeholder (`app.py:136-137`).
- **Results are hardcoded.** The Note 5 totals shown (`app.py:155-158`) are static strings,
  not computed from data.
- **Exports do nothing.** PDF/Excel buttons (`app.py:173-175`) are not wired up.
- **No validation harness** — even though the sample CSV ships L1–L3 as built-in ground truth.
- **No `.env`**, no tests, not a git repo, multi-sheet Excel not yet handled, only Note 5
  partially addressed.

### Sample data — `AMNB_Note5_All_Levels.csv`
A single file bundling **all four levels** (L1→L4) plus a cross-reference reconciliation map
for AL MADINAH NATIONAL BANK, FY2025. Because it contains L1–L3 alongside L4, it doubles as
a **ground-truth test fixture**: run the engine on L4 only, then check the computed L2/L1
against the L2/L1 already in the file. Key totals to reproduce: FVTPL 2,780,000 / FVOCI
12,350,000 / Amortised Cost 9,680,000 / **Total 24,810,000** (SAR '000).

---

## Real-world input reality (important)

Inputs will be **far messier than the sample**:
- Mostly **L4-only** files, but also **mixed-level** files.
- **CSV and Excel**, including **multi-sheet** workbooks.
- **A single sheet can contain MULTIPLE stacked tables** — exactly like the sample CSV
  stacks L1, L2, L3, L4 and a cross-reference map in one file. Any uploaded sheet may hold
  several distinct tables one after another (different headers, blank-row separators).
- **15–20+ files**, sometimes more.
- **Per-file size ranges from small to 1M+ rows.**

**Implications this creates:**
1. **Profiling must handle multi-sheet Excel** (profile every sheet, not just sheet 1).
2. **Profiling must also detect multiple tables *within* a single sheet** — find table
   boundaries (header rows, blank-row gaps, section titles), then profile each table
   separately rather than treating the whole sheet as one dataframe.
3. **Triage/routing happens at the *table* level, not the file or sheet level.** The system
   must reason: across these 15–20+ workbooks → which sheet → which table → which column/
   value → feeds which FS note → in which calculation. This is a value-level routing map,
   not just "which file is relevant."
4. **Schema variety is high** — column names/layouts differ per table, so the engine can't
   assume fixed headers; it must adapt per detected schema.
5. **Scale forbids the LLM ever touching rows** — reinforces the "LLM profiles, local code
   computes" design. Streaming/chunked Pandas reads may be needed for the largest files.

### New core capability this implies: a value-routing layer
Because one upload set can contain dozens of tables spread across sheets and files, the
system needs an explicit **routing map** as an intermediate artifact — produced by the LLM
from profiles, reviewable by the user, e.g.:

```
file → sheet → detected table → role (L1/L2/L3/L4) → which note → which calc input
```

This map is what makes the downstream code-gen targeted (it knows exactly which table and
columns to pull) and auditable (you can trace any FS number back to its source table/cell).

---

## The key decision: how to execute the data work

The notes selected "Approach A — AI as code generator." Here's the recommendation.

### Recommendation: a constrained hybrid (code-gen, but fenced and verified)

For an **auditable accounting tool processing millions of rows**, pure free-form
"LLM writes code → `exec()` it" is too risky, and pure "LLM outputs only a mapping spec"
may be too rigid for messy real-world schemas. Keep code generation for its scalability
**but fence it**:

1. **LLM works only from schema profiles** (headers + sample rows + sheet names) — never raw
   rows. Already the design; preserve it.
2. **LLM emits a reviewable Pandas transformation** *plus* a structured spec describing what
   it's doing (which columns map to which category, which aggregations).
3. **Execution is sandboxed:** whitelisted imports (pandas/numpy only), no file/network I/O
   beyond the target dataframe, CPU/memory/time limits, run in a subprocess.
4. **Every result is auto-validated against ground truth** (the L1–L3 in the sample, and a
   built-in reconciliation check that L4→L2→L1 ties out) before it's trusted/shown.
5. **Generated scripts are pinned per schema signature** — the same file layout reuses the
   previously reviewed/validated script instead of regenerating. This gives determinism,
   lower cost, and a clean audit trail (you can show an auditor the exact code that produced
   a number).

**Why this over the alternatives:**
- vs. *free exec*: adds the safety + auditability a financial tool legally needs.
- vs. *spec-only deterministic*: keeps flexibility to handle the heterogeneous, multi-sheet,
  varying-schema inputs described above, which fixed code would struggle with.

---

## Suggested roadmap (for whenever you decide to proceed)

0. **Model + ingestion foundation** — switch `engine.py` to **GPT-5.1**; upgrade profiling to
   (a) walk every sheet of every workbook and (b) **detect multiple tables within a sheet**.
1. **Value-routing layer** — LLM builds the file→sheet→table→role→note→calc routing map from
   profiles; user can review it.
2. **Phase 3 core** — generate + sandbox-execute transformations driven by the routing map;
   replace hardcoded results with computed Note 5 numbers.
3. **Validation harness** — reconcile computed L2/L1 against the sample's ground truth;
   surface pass/fail in the UI.
4. **Robust ingestion at scale** — large-file chunking/streaming for 1M+ row tables.
5. **Exports** — wire Excel (openpyxl) and PDF (reportlab) to real computed data.
6. **Extend** — additional notes (1, 2, 6, 8); optional `.env` for the API key; tests; git.

---

## Open items to confirm before building
- Confirm the constrained-hybrid execution approach above (or pick a different one).
- Decide priority order of the roadmap.
- Decide whether to keep Streamlit or plan for the frontend migration mentioned in the notes.
- Decide where Note 5 calculations should be auditable to (line-item, holding-level, or both).

---

## Verification (how we'll prove correctness once we build)
- Run the engine on **L4 rows only** from `AMNB_Note5_All_Levels.csv`.
- Programmatically assert computed totals equal the file's L2/L1:
  FVTPL 2,780,000 · FVOCI 12,350,000 · AC 9,680,000 · **Total 24,810,000**.
- Confirm the L4→L2→L1 reconciliation map entries all report MATCH.
- Exercise the UI end-to-end with a live GPT-5.1 key (available).
