# DEVELOPMENT_PLAN — AI Accountant / FS-Gen

> **Status:** Supersedes the earlier Note-5-cascade plan (now legacy).
> **Scope of this plan:** Build a tool that turns messy accounting data into IFRS financial-statement **notes**, starting with two real notes (Prepayments and Investments, Net), then extending to the full machinery.
> **What the user uploads:** a **bulk set of heterogeneous data** — either finished GLs *or* the lower-level data the GL is built from — in any form: a single sheet, multiple sheets, **multiple independent tables inside one sheet**, multiple files, mixed layouts and levels, all at once. The tool ingests all of it.
> **End product at this stage:** the **two notes** — Note 5 (Investments, Net) and the Prepayments note. (Full primary statements are Track 2, Phase 8 — do not over-build toward them now.)
> **Nothing is coded until the plan is green-lit.** This document is the spec; build against it phase by phase.

---

## 0. Context for the implementer

This tool ("FS-Gen" / the AI accountant) generates IFRS financial-statement notes from general-ledger data. The reporting context is **Saudi / IFRS-as-endorsed-in-KSA, currency SAR**. The working entity in all sample data is obfuscated to **"XYZ Company."**

Two real sample workbooks exist and define the input shape:

- **Prepayments** — `Prepayments_Reconciliation_May_2024_XYZ_Company_GL.xlsx`. Four sheets, one per SAP **company code** (`10400001 GL - 1010 / 1100 / 1200 / 1300`), all on a single G/L account `10400001` ("Prepaid expenses" / "Opex Prepayments"). SAP-style export. The first row of the 1010 sheet is a take-on / brought-forward entry (`13_10400001_TB_BS_Take-On`, dated 2019-12-31, user `MIG_FI_01`); everything else is movement (additions `XYZPREPAY…`, releases/amortisation `XYZPREPAY RELEASE…`).
- **Investments, Net** — `Investments_Net_Reconciliation_Q1_2025_XYZ_Company_GL.xlsx`. One sheet per G/L account, grouped by measurement basis: **FVIS** (`11010xxx`), **FVOCI** (`11020xxx`), **Amortised cost** (`11030xxx`), with two IFRS 9 ECL allowances held as **separate contra accounts** (`11029900`, `11039900`). A Domestic/International segment lives in the `Assignment` column (`DOM`/`INT`).

Both sample files use the **same ~17-column SAP layout**. Column headers (canonical meaning in brackets):

```
Company Code, G/L Account [account code], G/L Account Short Text,
Document type, Document Number, Posting period, Reference, Object key,
Company Code Currency Value [SAR amount — USE THIS], Company Code Currency Key,
Document Currency Value [original txn ccy — DO NOT SUM], Document Currency Key,
Assignment [segment, e.g. DOM/INT], Text, User Name, Posting Date, Fiscal Year
```

This file is the **raw data behind one note** each — it is *not* a full trial balance. A complete FS would need every GL account, not one.

---

## 1. Core architectural principles (from the PRD — do not violate)

1. **AI / deterministic boundary.** AI handles the fuzzy work (recognising file shapes, identifying columns, *proposing* mappings, drafting narrative). Deterministic code handles every **number** so it reproduces identically across runs and carries an audit trail. AI must **never** "guess a figure" into the number engine.

2. **The canonical trial balance is the backbone and the convergence point.** Everything downstream derives from one object: per `entity_id` × `gl_account` × dimension → opening + movements + closing, sign-respecting, period-parametrised. Every input path must converge here in identical shape.

3. **Balance check is the keystone.** A full TB must net to zero / the BS must balance. On a *single-note slice* this check is **not applicable** — report it explicitly as `N/A — slice`, never silently pass. The internal keystone that *does* apply at every level is **debits = credits** on the postings.

4. **Group by account, not description (§6.3).** The leaf grouping/mapping key is the **GL account code**, never free-text description. One account commonly carries many descriptions (e.g. "Refundable deposits", "Project advances", "VAT suspense" all inside one prepayments account). Description is a *hint*, never a grouping key. **This rule governs the mapping key only — it does NOT forbid presenting sub-line detail within a note** (see Phase 4a).

5. **Respect natural signs at the leaf.** Additions positive, releases/contra negative, so subtotals mixing assets and contra-balances come out correct. Store the sign rule on the node.

6. **Sector / framework / entity differences live in configuration, not code.** The aggregation engine is sector-agnostic. Mapping sets, note-requirements maps, and presentation templates are data.

7. **Mapping pattern: AI proposes → human confirms → deterministic engine stores & applies.** Applies at two levels (see Phase 1b and Phase 3). Once confirmed, a mapping is a stored, reusable, audited fact.

8. **Hierarchy is one self-referencing table.** L4→L1 rollup; balances live only on L4 leaves; every level above is computed (sum of children), never stored. Roll up by `parent_id` until parent is null (do **not** assume exactly four levels). Drill-down and audit lineage fall out of the `parent_id` links for free.
   - **L4** — leaf: individual GL account / line-item detail
   - **L3** — note-level grouping
   - **L2** — balance-sheet / P&L caption (face line)
   - **L1** — statement section subtotal (most summarised)

---

## 2. Locked decisions (Q5–Q10 from review)

**Q5 — Roll-forward mechanics.** `closing = opening (the take-on / OPEN-BF row) + Σ movements`, respecting sign. Sum the **Company Code Currency Value (SAR)** column — the already-converted local-currency figure. **Never** sum the Document Currency Value column, and never mix the two; USD/other-ccy docs are already converted in the SAR column. **ECL allowances** (`…9900`) are **separate contra leaves** that net against the gross value accounts → net (Investments only; Prepayments has no allowance account).

**Q6 — Four company codes.** `1010/1100/1200/1300` are SAP company codes. **For now, sum them as sub-ledgers of one reporting entity.** Map "company code → `entity_id`" in the canonical TB so that true multi-entity consolidation (intercompany elimination, NCI, separate TBs) is later a config/data change, not an engine rewrite. Consolidation is deferred to Track 2. *(Confirm with finance — see §6.)*

**Q7 — Period.** Parametrise it; do not hard-code "May 2024." `opening b/f` = balance at the start of the chosen window; `movements` = postings dated within the window; `closing = opening + Σ`. Pre-window history (2019 take-on + 2019→2023 activity) collapses into the single b/f figure — do not disclose those lines individually. Surface the as-of date as a parameter in the output. *(Confirm real reporting close with finance — see §6.)*

**Q8 — Note breakdown.** Present the **account-level total as the authoritative, deterministic number** (must tie), with a **reconciling sub-category breakdown beneath it** (prepaid expenses / advances / deposits / VAT) derived from the description text as a **presentation layer**, explicitly flagged as text-derived, whose sub-totals must reconcile back to the account total. This honours real-world disclosure without letting description text enter the number engine — fully compatible with §6.3.

**Q9 — Mapping.** **Seed the deterministic mapping table now** (`110xxxxx → Investments`, `10400001 → Prepayments`), written into the *real* mapping-table schema with `approved_by = "seed"`. This is not throwaway — the PRD's deterministic engine stores & applies the approved mapping; the AI-propose/human-confirm loop is only the mechanism for onboarding *unknown* accounts (Track 2, Phase 6).

**Q10 — Balance check.** Note-level reconciliation is the correct check today: **per-leaf roll-forward** (`opening + Σ movements = closing`) and **note-rolls-up-to-subtotal**. The full-TB keystone is meaningless on one note — report it as `N/A — slice`, do not delete it. It switches on when a complete TB is fed (Track 2, Phase 8).

---

## 3. Mapping-table schema (seed two notes into this exact shape)

```
gl_account      -- code, the leaf key
note_ref        -- which disclosure note
face_caption    -- balance-sheet / P&L line it rolls into
classification  -- current/non-current, asset/liability/equity/income/expense
sign            -- natural debit/credit sign
approved_by     -- "seed" for the two seeded notes; a user id once the AI loop exists
approved_at     -- timestamp
```

Hierarchy node table (self-referencing): `node_id, level (L1–L4), parent_id, label, gl_account (L4 only), note_ref, classification, sign, approved_by, approved_at`.

Canonical TB row (§6.1): `entity_id, gl_account, account_description, opening_balance, period_movements (or Dr/Cr totals), closing_balance, currency (source → normalised to presentation), period`.
> **`currency` / document currency is posting metadata, NOT a TB balance dimension.** Balances live in presentation currency (SAR). Do not sum across document currencies as if they were separate balance buckets.

---

## 4. Three key design properties of ingestion

The user dumps a **bulk, heterogeneous batch** at once. The ingester must cope with three orthogonal kinds of mess: *form* (column layout), *level* (granularity), and *structure* (how tables are physically arranged in files/sheets).

**(a) Format-agnostic field resolution (no column-count branching).** The ingester must key off **field meaning, not column count or header text**. "17-col" / "29-col" are only descriptions of sample shapes — never a config switch or code branch. Build a **field resolver**: a fixed canonical target (account code, presentation-currency amount, sign, date, period, reference type, optional segment), where AI *proposes* "your column X → SAR amount", a human confirms once, and deterministic validation checks every **required** canonical field got mapped. Missing required field → exception in the gap report, not a crash. Extra columns → ignored. A different ERP entirely (Oracle, Dynamics, hand-built workbook) → same resolver. Test against shapes the resolver has never seen — that's the whole point of the feature.

**(b) Structure-agnostic table-region detection (the hard one).** Do **not** assume one table per sheet or a fixed header row. A single uploaded workbook can contain: many sheets; **several independent tables stacked in one sheet** (separated by blank rows, with their own header rows); **side-by-side tables** in the same rows; title/summary/notes blocks interleaved with data; merged cells and embedded sub-headers. The ingester must first **detect table regions** (find each table's bounding box and its header row), *then* run the field resolver per region. This is the most error-prone part of ingestion, so apply the PRD pattern explicitly: **AI proposes the detected table regions → the UI shows them → the human confirms or adjusts the boundaries → deterministic extraction runs.** Never silently auto-slice, because a mis-detected boundary silently corrupts numbers.

**(c) Input-level detection (granularity is a first-class property).** Before building the TB, detect each region's level:
- **GL / posting-level** (the two samples) → flows straight to the canonical TB.
- **Sub-ledger level** → roll up; reconcile to GL if a GL balance is also present.
- **Raw transactional** (AP/AR invoices, bank lines, FA register) → derive postings first (Phase 1b).

Levels can be **mixed within one bulk upload** — some sheets/tables GL-level, others source-level. Detect and route per region, not per file. If a region is below GL, the tool **builds the GL, then runs the normal phases** — see Phase 1b.

---

## 5. The phased plan

Both input paths (uploaded GL, or GL derived from lower-level data) **converge on the canonical TB**, so Phases 2–5 are identical regardless of how the GL arrived. Build the GL once at the front; everything flows the same after.

### Track 1 — make the two notes work end-to-end

| Phase | Name | What it delivers |
|---|---|---|
| **1** | Ingestion & input-level resolution | Accept a **bulk, heterogeneous batch** of uploads. Per file: handle multiple sheets; **per sheet: detect multiple independent table regions** (stacked, side-by-side, interleaved with title/summary blocks) before extraction — AI proposes regions, human confirms boundaries, deterministic extraction runs. Per region: format-agnostic field resolver (match on meaning, no column-count assumptions) → account code, SAR amount, sign, segment (DOM/INT), dates, period, reference type. Input-level detector **per region** (GL / sub-ledger / raw transactional — levels may be mixed across the batch), routed accordingly. Required-field validation → exceptions, not crashes. |
| **1b** | GL derivation (when input is below GL level) | Transaction → account **posting-rule** mapping (**AI proposes → human confirms → deterministic applies**), then deterministic aggregation of source lines into account-level postings. **Reconciliation gate:** if a GL balance is also available, derived GL must reconcile to it and the difference is surfaced; if only source data exists, run the internal **debits = credits** keystone and label output "GL derived from source, not reconciled to an independent GL." Output shape is identical to an uploaded GL. *Support the source type actually in hand first; general multi-source derivation (AP/AR/bank/FA/payroll) is its own later phase — do not promise it all at once.* |
| **2** | Canonical trial balance (§6.1) | Per `entity_id` × `gl_account` × dimension(DOM/INT) → opening (collapsed b/f) + movements (by reference type) + closing, sign-respecting, period parametrised. **Per-leaf roll-forward check.** `currency` is metadata, not a balance dimension. **Dedup guardrail:** because the bulk upload can present the same postings in more than one file/sheet/table, deduplicate on a posting key (e.g. document number + object key + line) so the same entry is never counted twice; flag suspected duplicates rather than silently dropping. |
| **3** | Hierarchy + seed mapping (§6.2–6.3) | Self-referencing L4→L1 node table + mapping-table schema; seed the two notes' account ranges as `approved_by="seed"`. Roll up by `parent_id` → audit lineage for free. |
| **4a** | Note module — **Prepayments** (simpler; do first) | Single account total (authoritative, deterministic) + **reconciling** description-derived sub-category breakdown (prepaid expenses / advances / deposits / VAT) as a presentation layer that ties to the total. Note-rolls-to-subtotal check. |
| **4b** | Note module — **Investments, Net** (the stress test) | FVIS / FVOCI / AC, gross → less ECL allowance → **net**, by measurement type, split Domestic/International, plus full movement schedule (open / purchases / disposals / remeasurement / FX / ECL → close). Exercises many leaves + a contra + a segment tag against the proven pipeline. Note-rolls-to-subtotal checks. |
| **5** | Outputs + UI | **Deliverable at this stage = the two notes (Investments, Net + Prepayments) as the FS output** — not full primary statements (those are Phase 8). Gap report (per-note BUILT / PARTIAL / BLOCKED; keystone `N/A — slice`); audit drill-down (L1 → … → L4 postings); Excel/PDF export; Streamlit UI: bulk-upload data (GL or source) → table-region confirm → field-map confirm → TB → mapping → notes. **Note: validation is NOT deferred to here** — the per-leaf roll-forward (Phase 2) and note-rolls-to-subtotal (Phase 4) checks run upstream; Phase 5 only *presents* them. |

> **End of Phase 5 = both notes computed correctly from the GL, end-to-end.** Realistically spans more than one session; start at Phase 1 and go as far as possible.

### Track 2 — full PRD machinery (after the two notes work)

| Phase | Name |
|---|---|
| **6** | AI account-mapping proposals + human-confirm loop (for unknown accounts) |
| **7** | Note-requirements map + full BUILT/PARTIAL/BLOCKED gap engine + incremental re-runnable loop + state persistence |
| **8** | Full TB keystone (when a complete TB is fed) + primary statements + cross-checks |
| **9** | Policy layering (IFRS 9 + standard online policies as base; user-uploaded policy overrides) + AI disclosure narrative |
| **10** | Saudi presentation: bilingual, SOCPA add-ons, Zakat note |
| **11** | IFRS 1 first-time adoption (transition opening SoFP, prev-GAAP reconciliations, exemptions) |
| **12** | Scale to more notes + multi-entity consolidation + general multi-source GL derivation |

---

## 6. Non-blocking confirmations to get from finance (in parallel — do not hold up Phase 1)

1. Are `1010/1100/1200/1300` genuinely **separate legal entities**, or internal divisions of one reporting entity? (Determines whether Phase 12 consolidation is needed or whether summing is permanently correct.)
2. **Prepayments reporting close date** — is it 31 Dec 2023, or is there real 2024 activity in scope? (Determines the default period window.)
3. Is the real Investments export genuinely **wider than the 17-col sample**? If so, obtain a real wide sample so the field resolver is tested on the wide case — do not assume it works untested.

---

## 7. Engineering conventions

- **Package layout:** keep the existing `ai_accountant` package; add new modules (`gl/`, `trial_balance/`, `hierarchy/`, `notes/`, `ingestion/`, `derivation/`, …). Mark the old Note-5 cascade as `legacy/`. **New modules must not import from `legacy/`** so the superseded design cannot leak back in.
- **Determinism:** every number must reproduce identically across runs. Any sector/entity/framework branch belongs in configuration/data, not code.
- **Audit lineage:** every figure must answer "why is this number here?" — traceable from L1 total down to the L4 postings and the mapping rule + approver that placed it.
- **Green-light discipline:** nothing is coded until this plan is approved. Build phase by phase; each phase's checks must pass before moving on.

---

## 8. Open items before coding

- Confirm the phasing and ordering above (especially the 4a/4b split and the Phase 1b position).
- Confirm package layout (lean: same package + new modules + legacy reference).
- Resolve the wide-layout sample question (§6.3) so Phase 1 is tested honestly.
