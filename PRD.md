# Product Requirements Document — AI Financial Statement Generator (Saudi / IFRS-KSA)

> **Working title:** FS-Gen
> **Status:** Draft v0.2 (for engineering kickoff)
> **Framework target:** Full IFRS as endorsed in the Kingdom of Saudi Arabia (SOCPA) — *not* IFRS for SMEs
> **First-time adoption:** In scope — the tool must support first-time adopters under **IFRS 1** (transition requirements; see §3.3)
> **Reporting currency:** SAR (multi-currency input supported, single presentation currency)

---

## 1. Summary

FS-Gen ingests an entity's accounting data — general ledgers (GLs), trial balances, and supporting documents in arbitrary formats — and produces a **review-ready draft set of IFRS financial statements** plus a precise **exceptions / gap report** describing exactly what could not be produced and why.

The product is **not** a "garbage-in, signed-financial-statements-out" black box. It is an extremely capable staff accountant that does the grunt work — ingesting mess, building the trial balance, mapping accounts, computing note schedules, drafting disclosure prose, and reconciling — then hands a qualified human a near-complete draft and an actionable list of what still needs data or judgement.

### 1.1 Why this framing matters (non-negotiable principle)

A financial statement is an assertion of accuracy that people sign and auditors test. The tool cannot manufacture correctness that is not present in the input data. A tool that confidently emits a polished FS from noise is a liability, because it *looks* authoritative. Therefore:

- The tool's job with messy input is **triage**, not fabrication: extract what is usable, quarantine what is not, and state precisely what is blocking completion.
- **Numbers are never guessed.** If a figure cannot be derived from validated data, the corresponding output is a flagged gap, not an invented value.
- The **exceptions report is a first-class deliverable**, not an error log. In early versions it is arguably the *primary* deliverable, with the FS as the reward once the data clears.

---

## 2. Goals & non-goals

### 2.1 Goals

1. Accept arbitrary, messy financial inputs (multiple GLs, transactional extracts, varying layouts, multiple entities/currencies) and normalise them.
2. Assemble a canonical, validated **trial balance** per entity and period.
3. Map every account into a configurable **L4→L1 reporting hierarchy** with human review of new/changed mappings.
4. Produce the primary statements (statement of financial position, statement of profit or loss and OCI, statement of changes in equity, statement of cash flows) and all notes that are **derivable from the trial balance**.
5. For every note in the expected universe, report its state: **built**, **partially built**, or **blocked**, with the specific missing artifact or judgement named.
6. Support an **incremental, re-runnable loop**: user uploads more data → tool completes additional notes → updates the gap report, without losing prior human-approved mappings.
7. Draft disclosure narrative prose, grounded in the entity's accounting policies.

### 2.2 Non-goals (explicitly out of scope for v1)

- Autonomous production of a final, signed-off FS with no human review.
- Computing figures that require management assertion or external data the tool was not given (e.g. inventing a fair-value level, a contingent liability, or an ECL where no loss data exists).
- Audit. The tool produces a draft; it does not opine.
- Tax/Zakat computation and filing. (Zakat/tax *disclosure* is in scope as a note where the underlying numbers are provided; the *computation* is not a v1 goal — see §9.)
- Real-time integration with ERP systems (v1 is upload-based; API ingestion is a later phase).

---

## 3. Target users & framework

### 3.1 Users

- **Primary:** accountants / finance staff at Saudi entities (or their outsourced bookkeepers / advisory firms) preparing statutory financial statements.
- **Reviewer:** a qualified person (CFO, controller, external accountant) who reviews the draft, approves mappings and judgements, and finishes blocked notes.

### 3.2 Framework

- **IFRS as endorsed in Saudi Arabia**, under SOCPA (Saudi Organization for Chartered and Professional Accountants).
- **v1 target: Full IFRS** (larger/listed entities) — *confirmed*. IFRS for SMEs is **not** a v1 target but the note-requirements map (§7) must remain selectable by framework variant so SMEs can be added later without engine changes.
- **Saudi-specific considerations to confirm during build** (do not hardcode without verification):
  - SOCPA may require additional disclosures beyond pure IFRS.
  - **Zakat and income tax** presentation/disclosure conventions (ZATCA-relevant) — the entity profile drives whether a Zakat note is expected.
  - **Bilingual reporting** (Arabic / English) is common for Saudi statutory filings — treat language as a presentation-layer requirement, not an afterthought (see §11).

> **Open item:** Confirm the precise endorsed-IFRS note set + any SOCPA add-ons for the full-IFRS profile. This determines the concrete contents of the §7 requirements map.

### 3.3 First-time adoption (IFRS 1) — in scope

The tool must handle entities preparing their **first** IFRS financial statements under IFRS 1. This is a distinct scope item, not just a framework label, and the sample data motivates it directly: the uploaded GL contained take-on / migration entries (`TB_BS_Take-On`, posted by a migration user), which is exactly the signature of a first-time-adoption opening balance.

First-time adoption adds transition-specific requirements the engine and requirements map must accommodate:

- An **opening IFRS statement of financial position** at the date of transition (the take-on balances become the starting point — these are the "opening balance" leaves discussed in the hierarchy model, not ordinary period movements).
- **Reconciliations from previous GAAP** to IFRS — of equity (at transition date and end of the comparative period) and of total comprehensive income for the comparative period.
- **IFRS 1 exemptions/elections** the entity has taken — these are `management`-sourced inputs (judgement), not ledger-derivable, and must be captured and disclosed.

> **Design note:** A first-time-adoption run is distinguished by an `is_first_time_adopter` entity flag plus a `transition_date`. When set, the tool expects opening IFRS balances and the previous-GAAP comparatives needed for the reconciliations, and adds the IFRS 1 reconciliation notes to the expected universe. When unset, those notes are not expected and must not be flagged as gaps.

---

## 4. The AI / deterministic boundary (core architectural rule)

This boundary governs the entire system. It exists so that **every number reproduces identically across runs** and carries an audit trail, while AI handles the genuinely fuzzy work.

| Layer | Responsibility | AI or deterministic |
|---|---|---|
| Ingest & normalise | Recognise document types, identify columns (account, amount, date, currency), parse arbitrary layouts | **AI** (proposes), with deterministic validation |
| Trial balance assembly | Aggregate postings to per-account opening/movement/closing | **Deterministic** |
| Balance validation | Assets = liabilities + equity; TB nets to zero | **Deterministic** |
| Account → hierarchy mapping | Assign `note_ref`, face caption, classification to each account | **AI proposes → human confirms → deterministic engine stores & applies** |
| Note calculations (roll-forwards, schedules) | Compute each note's figures from the validated TB | **Deterministic** |
| Statement assembly & cross-checks | Notes tie to face; cash flow ties to BS movements; opening ties to prior closing | **Deterministic** |
| Disclosure narrative | Draft policy and note prose | **AI** (drafts), human edits |
| Exceptions explanation | Explain each gap in plain language; recognise whether an upload satisfies a requirement | **AI**, over a deterministic requirements map |

**Rule of thumb:** garbage tolerance lives entirely in the AI ingestion layer and the exceptions report. It must **never** leak into the number engine as "the AI guessed a figure." If you find yourself adding sector- or entity-specific branches into the number engine, that logic belongs in **configuration/data**, not code (see §6.4).

---

## 5. Processing pipeline

```
Uploads (any format)
   │
   ▼
[1] Ingest & normalise  ──────────────  AI parses; deterministic schema validation
   │
   ▼
[2] Trial balance assembly  ───────────  Deterministic; per entity, per period
   │
   ▼
[3] Balance validation (KEYSTONE)  ─────  TB must net to zero / BS must balance
   │        │
   │        └── fails → halt downstream, report imbalance & amount
   ▼
[4] Account → L4-L1 mapping  ───────────  AI proposes, human confirms, code stores
   │
   ▼
[5] Note modules (per note)  ───────────  Deterministic calculations
   │        │
   │        └── per note: BUILT / PARTIAL / BLOCKED
   ▼
[6] Statement assembly + cross-checks  ─  Deterministic reconciliations
   │
   ▼
[7] Outputs: FS draft  +  Exceptions/gap report  +  Audit lineage
```

### 5.1 The balance check is the keystone

A balance sheet must balance and a trial balance must net to zero. This is the single most powerful weapon against bad data: if the inputs do not net to zero, **something is missing or wrong**, and the tool can say so concretely rather than guessing. The pipeline halts note production if a balancing trial balance cannot be assembled, and reports the imbalance and its magnitude.

---

## 6. Data model

### 6.1 Canonical trial balance (the backbone)

Everything downstream derives from this object. One row per account, per entity, per period:

- `entity_id`
- `gl_account` (code)
- `account_description`
- `opening_balance`
- `period_movements` (or debit/credit totals)
- `closing_balance`
- `currency` (source) → normalised to presentation currency
- `period`

### 6.2 Reporting hierarchy (single self-referencing table)

The L4→L1 rollup is **one self-referencing table**, not four table-builders. Balances live only on L4 leaves; every level above is computed (sum of children), never stored.

| Field | Notes |
|---|---|
| `node_id` | unique key |
| `level` | L1 (apex/subtotal) → L4 (leaf/GL account) |
| `parent_id` | points one level up; null at L1 |
| `label` | display caption |
| `gl_account` | populated on L4 leaves only; null on summary nodes |
| `note_ref` | which disclosure note this rolls into |
| `classification` | current/non-current, asset/liability/equity/income/expense |
| `sign` | natural debit/credit sign so rollups add correctly |
| `approved_by`, `approved_at` | mapping approval metadata (audit lineage) |

**Level semantics (confirmed convention):**

- **L4** — leaf: individual GL account / line-item detail (most granular)
- **L3** — note-level grouping
- **L2** — balance-sheet / P&L caption (face line)
- **L1** — statement section subtotal (most summarised)

**Aggregation rule:** roll up by `parent_id` until parent is null. Do **not** assume every branch is exactly four levels deep — some captions are fed directly by a leaf with no intervening note. Drill-down (L1 → … → L4 postings) falls out of the `parent_id` links for free, and is the audit lineage.

### 6.3 Critical ingestion rule — group by account, not description

The leaf grouping key is the **GL account code**, never the free-text description. A single account commonly carries multiple descriptions (e.g. "Refundable deposits", "Project advances", "VAT suspense" all inside one prepayments account). Grouping by description would scatter one account across multiple notes. Treat the description as a hint, never the grouping key. Respect natural **signs** at the leaf (additions positive, releases negative) so subtotals mixing assets and contra-balances come out correct.

### 6.4 Sector / entity differences live in configuration, not code

The aggregation **engine** is sector-agnostic. Sector and framework differences live in **configuration**: the mapping set, the note-requirements map (§7), and the presentation template (note order, mandatory captions, IFRS vs SME layout). Onboarding a new sector or entity profile means authoring a new config, never forking the engine. (Known exception: structurally different statements — banks, insurers under IFRS 17 — may warrant a dedicated template mode; out of v1 scope.)

---

## 7. Note-requirements map (the gap-detection brain)

For each note in the expected universe (defined by framework + entity profile), the tool stores a structured requirement: **note → required inputs → source type**. The completeness assessment compares produced output against this map. It is **deterministic and framework-driven**, so two runs on the same data yield the same gap report.

`source_type` values:
- `ledger` — derivable from the trial balance
- `supplementary` — needs an additional uploaded document (fixable by the user)
- `management` — needs management assertion/judgement; no document alone suffices

Illustrative entries (to be finalised against endorsed-IFRS-KSA for the chosen entity profile — **verify before hardcoding**):

| Note | Required inputs | Source type |
|---|---|---|
| Prepayments | Account balances + movements | `ledger` |
| Property, plant & equipment | Cost & accumulated-depreciation movements (`ledger`) + asset-class breakdown, useful lives (`supplementary` — fixed-asset register) | `ledger` + `supplementary` (→ **PARTIAL**) |
| Leases (IFRS 16) | Lease schedules: commencement date, term, payments, discount rate per lease | `supplementary` |
| Financial instruments — maturity analysis | Contractual maturities | `supplementary` |
| Financial instruments — fair-value hierarchy | FV level (1/2/3) per instrument, inputs | `supplementary` + `management` |
| Expected credit losses (IFRS 9) | Historical loss data, staging, forward-looking macro inputs | `supplementary` + `management` (see §8) |
| Related parties | Related-party listing + transaction detail | `supplementary` |
| Commitments & contingencies | Management input | `management` |
| Post-balance-sheet events | Management input | `management` |
| Going concern / significant estimates | Management assertion | `management` |
| Zakat / income tax (KSA) | Tax/Zakat computation figures | `supplementary` (computation out of scope — §9) |
| **IFRS 1 — opening IFRS SoFP** *(first-time adopters only)* | Opening balances at transition date (the take-on leaves) | `ledger` (if take-on balances uploaded) |
| **IFRS 1 — reconciliation of equity** *(first-time adopters only)* | Previous-GAAP equity at transition date and end of comparative period | `supplementary` |
| **IFRS 1 — reconciliation of total comprehensive income** *(first-time adopters only)* | Previous-GAAP comprehensive income for the comparative period | `supplementary` |
| **IFRS 1 — exemptions/elections taken** *(first-time adopters only)* | Which IFRS 1 exemptions the entity elected | `management` |

> The four IFRS 1 rows are added to the expected universe **only** when the entity's `is_first_time_adopter` flag is set (see §3.3). Otherwise they must not be treated as gaps.

### 7.1 Three note states

- **BUILT** — fully produced from available data.
- **PARTIAL** — core computed from ledger, with a labelled hole *inside* the note for the missing piece (e.g. PP&E roll-forward built, asset-class breakdown missing). A note 80% built with a marked gap beats a missing note and vastly beats a complete-looking note with invented numbers.
- **BLOCKED** — cannot be built; report names the specific missing artifact **or** flags it as requiring management input.

### 7.2 Distinguish "missing data" from "missing judgement"

`supplementary` gaps are fixable by uploading a document. `management` gaps require a person and no upload will ever satisfy them. The report must not imply a `management` note is "just one upload away," or it sets a false expectation that more files eventually yield a complete FS. For `management` items, prompt with the right questions rather than requesting a file.

---

## 8. Accounting-policy layering & IFRS 9

### 8.1 Policy layering

Policy resolves in three layers, last-wins on conflict:

1. **The standard** (IFRS as endorsed in KSA) — the baseline.
2. **Generic / default policies** — common applications of the standard's elections.
3. **Entity-specific uploaded policy** — overrides/specialises where the entity has made a specific election.

### 8.2 Words vs numbers (critical distinction)

- A policy that affects **disclosure wording** (how the entity describes its method) → drives **AI-generated prose**. Low risk, high value.
- A policy that affects **recognition/measurement** (i.e. changes computed figures — provision rates, classification, staging) → must flow through the **deterministic engine as structured, validated, human-confirmed parameters**, never as free text the AI interprets into numbers on the fly.

Pattern: AI **reads** the uploaded policy and **proposes** structured parameters ("appears to use a 3-bucket provision matrix at 1% / 5% / 20% — apply these?"); a human confirms before any rate touches a calculation.

### 8.3 IFRS 9 / ECL caveat

ECL is among the most judgement-heavy, data-hungry areas in IFRS. It needs forward-looking macro inputs, staging logic, and historical loss data that are **not** in a GL. Decide explicitly per the chosen scope:

- **Disclose** a management-provided ECL figure (tractable, in scope), **vs.**
- **Compute** ECL (requires a separate data pipeline; treat as out of v1 scope unless deliberately resourced).

---

## 9. Non-GL disclosures & supplementary data

A GL yields balances and movements. It does **not** yield debt maturity profiles, lease terms, fair-value levels, related-party relationships, commitments/contingencies, post-balance-sheet events, or segment data. "Upload all the GLs and I'll make the whole FS" is therefore structurally impossible for a real disclosure set — a limitation of the *input*, not the tool.

The tool must:
- Know, per note, whether it is GL-derivable or needs supplementary/management input (§7).
- **Prompt the user** for the specific missing artifact, naming the required fields (e.g. "lease schedule with commencement date, term, payment amounts, discount rate per lease").
- Accept those supplementary uploads and complete the corresponding notes incrementally (§10).

Zakat/income tax: disclosure note in scope where figures are provided; **computation and filing are out of v1 scope.**

---

## 10. Incremental, re-runnable loop

The completeness assessment is a **loop, not a one-shot verdict**:

1. User uploads GLs → tool produces FS draft + gap report.
2. User uploads a supplementary document (e.g. lease schedule).
3. Tool recognises which requirement the upload satisfies, builds **only** the newly-unblocked note(s), and updates the gap report.
4. Prior human-approved mappings and confirmed policy parameters **persist** across rounds — no redo from scratch, no loss of approvals.

State persistence across rounds (mappings, approvals, confirmed parameters, prior outputs) is part of the architecture, not an afterthought.

---

## 11. Outputs

1. **Financial statement draft** — primary statements + all BUILT and PARTIAL notes, in the framework's presentation order. Bilingual (Arabic/English) treated as a presentation-layer concern from the start for Saudi statutory use.
2. **Exceptions / gap report** — for every expected note: state (BUILT / PARTIAL / BLOCKED), and for non-BUILT, the specific missing artifact or the management input required. Also: unmapped accounts, trial-balance imbalance (and amount), opening-vs-prior-closing mismatches, notes whose detail doesn't tie to face totals, and unrecognised inputs.
3. **Audit lineage** — for any figure, the path from face line → caption → note → leaf accounts → source postings (the `parent_id` chain).

### 11.1 Example gap-report tone (target UX)

> "I built the balance sheet, income statement, and 9 notes from your GLs. I **partially** built the PP&E note — cost and accumulated-depreciation movements are from the ledger, but I can't produce the asset-category breakdown without a fixed-asset register. I **could not** build 4 notes: leases (need lease schedules — term, payments, discount rate), the financial-instruments maturity analysis (need contractual maturities), related-party disclosures (need the related-party listing and transactions), and commitments & contingencies (requires management input, not derivable from ledger data). Upload any of the first three and I'll complete those notes."

---

## 12. Acceptance criteria (v1)

- [ ] Ingests at least: multi-sheet GL exports, trial balances, and CSV/Excel transactional extracts with varying column layouts.
- [ ] Produces a balancing trial balance per entity/period, or halts with a clear imbalance report stating the amount.
- [ ] Every account is either mapped (with human-approved `note_ref`) or surfaced as unmapped — none silently dropped.
- [ ] The same input set produces an identical FS and identical gap report on repeated runs (number engine + requirements map are deterministic).
- [ ] Every expected note is reported as BUILT / PARTIAL / BLOCKED with a specific reason for non-BUILT.
- [ ] `supplementary` vs `management` gaps are clearly distinguished.
- [ ] Uploading a supplementary document completes the corresponding note without re-doing prior work or losing approvals.
- [ ] No figure in any output is AI-generated; all numbers trace to validated source data via audit lineage.
- [ ] Notes tie to face totals; cash flow ties to balance-sheet movements; current opening ties to prior closing — or the discrepancy is reported.

---

## 13. Suggested build phasing

- **Phase 0 — backbone:** ingest → trial balance → balance validation → exceptions report (no notes yet). Prove the keystone and the triage value first.
- **Phase 1 — hierarchy & mapping:** L4–L1 table, AI-proposed mappings, human approval, persistence.
- **Phase 2 — ledger-derivable notes + primary statements:** the deterministic note modules and statement assembly with cross-checks.
- **Phase 3 — requirements map & gap states:** BUILT/PARTIAL/BLOCKED, supplementary prompts, incremental loop.
- **Phase 4 — policy layering & narrative:** AI disclosure prose, structured policy-parameter confirmation.
- **Phase 5 — Saudi presentation polish:** bilingual output, SOCPA-specific disclosures, Zakat/tax note.
- **Phase 6 — IFRS 1 first-time adoption:** transition-date opening SoFP handling, previous-GAAP reconciliation notes, exemption capture (can run alongside Phase 3 since the requirements-map mechanics are shared).

---

## 14. Open questions (resolve before/early in build)

1. ~~**Entity profile for v1**~~ — **Resolved:** full IFRS (not IFRS for SMEs), with **first-time adoption (IFRS 1) in scope** (§3.3). Confirm only whether *every* v1 entity is a first-time adopter or whether the tool must handle both first-time and continuing adopters from day one (the `is_first_time_adopter` flag assumes both).
2. **Exact endorsed-IFRS-KSA note set + SOCPA add-ons** for the full-IFRS profile — needs verification against an authoritative source, not assumed.
3. **IFRS 9 ECL:** disclose a provided figure (in scope) vs compute (out of scope unless resourced)?
4. **Multi-entity / consolidation:** is v1 single-entity, or must it consolidate multiple entities (intercompany eliminations, NCI)? Consolidation is a large additional scope.
5. **Bilingual requirement:** is Arabic output required for v1, or English-first with Arabic later?
6. **Prior-period data:** will users always upload prior-period closing for opening-balance validation, or must the tool handle first-period entities? *(Note: first-period and first-time-adoption are related but distinct — a first-time adopter has a transition-date opening position even if it is not its first period of operation.)*
7. **Zakat/tax note:** confirm it is disclosure-only (figures provided) for v1.

---

*This PRD reflects the architecture discussed: a triage-first, human-in-the-loop FS generator with a strict AI/deterministic boundary, a configurable L4–L1 reporting hierarchy, a deterministic note-requirements map driving BUILT/PARTIAL/BLOCKED gap reporting, and an incremental re-runnable loop. Verify all Saudi-specific (SOCPA/ZATCA) and framework-specific details against authoritative current sources before implementation.*
