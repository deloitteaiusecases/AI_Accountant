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

**The two samples differ in width — both are in scope for the resolver from day one.**
- **Prepayments ≈ 17 columns** (no security/counterparty fields).
- **Investments = 29 columns** — adds Posting Key, Debit/Credit Indicator, Profit Center, Cost Center, Trading Partner, Value/Entry Date, Clearing Document, Security ID/ISIN, Counterparty, Portfolio, Nominal/Units.

This is deliberate test value: the field resolver's format-agnosticism is exercised on real data from day one, and the wide-sample concern (former §6 item 3) is largely satisfied by Investments. The shared/core canonical fields (meaning in brackets):

```
Company Code, G/L Account [account code], G/L Account Short Text,
Document type, Document Number, Posting period, Reference [movement/reference code], Object key,
Company Code Currency Value [SAR amount — USE THIS], Company Code Currency Key,
Document Currency Value [original txn ccy — DO NOT SUM], Document Currency Key,
Assignment [segment, e.g. DOM/INT], Text, User Name, Posting Date, Fiscal Year
```

The extra Investments columns are **optional-but-useful, never required**: Security ID/ISIN, Portfolio, Nominal/Units, Counterparty are valuable for the by-type disclosure, so the resolver maps them when present without depending on them; Posting Key / Debit-Credit Indicator / Line are useful for sign and dedup (see Round-2 #5). A row missing an optional field must not fail.

Each file is the **raw data behind one note** — it is *not* a full trial balance. A complete FS would need every GL account, not one.

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

## 2.1 Round-2 locked decisions (Phase 1 review)

**R1 — Phase 1 heaviness: build the interface for the general case, implement the specific case you can test.** Both samples are clean (one table per sheet, header in row 1), so the multi-region detector + confirm UI has **zero test cases** today. The pipeline consumes "a list of resolved regions"; **v1 ships the trivial implementation `region = sheet`** (deterministic). Get both notes working end-to-end on the clean layout first, then swap in real region-detection when a genuinely messy file appears — it's a component swap, not a refactor. So: **(b) in implementation order, (a) in interface design.** Flexibility is designed-*for*, not designed-out.

**R2 — Investments structure.** Derive **classification from the account-code structure** (`11010→FVIS`, `11020→FVOCI`, `11030→AC`, `…9900→allowance`) — deterministic. Use the **short text only for the sub-type *label*** ("Fixed-rate sukuk") — presentation, never classification (keeps it consistent with §6.3). DOM/INT is a TB dimension + note column. ECL netting: `FVOCI gross (11020xxx) − FVOCI allowance (11029900) = net`; `AC gross (11030xxx) − AC allowance (11039900) = net`; FVIS has no allowance. Match the **Bank AlJazira Note 5 layout** (5.1 net summary, 5.2 by-type Domestic/International, movement schedule) — but the template lives in **config** (§6.4); populate only lines that have data, never manufacture empty bank-specific lines.

**R3 — Movement schedule = reference-code config.** Reference-code → movement-line is **another seeded config table** (like account mapping), not hardcoded. Seed the 6 known codes (`OPEN-BF, PURCH, DISP-MAT, REMEAS, FX-REVAL, ECL-IFRS9`) but **expect others in real data** (transfers, reclasses, accruals, reversals, accrued coupon, premium/discount amortisation, FX-on-disposal vs FX-on-reval). Unmapped codes route to an **"unclassified movement" bucket that still rolls into the closing total** and is flagged in the gap report. Never drop an unmapped code; never let one break the roll-forward — the decomposition can be incomplete while the closing still ties.

**R4 — Prepayments sub-grouping = seeded taxonomy + AI fallthrough + exceptions.** Seeded keyword taxonomy as the deterministic floor (Prepaid / Advances / Deposits / VAT / Other), with **Other** as the live balancing plug. AI *proposes* classifications for everything that falls through to Other (per the PRD pattern); human confirms; the confirmed label moves the item out of Other. Control/reconciliation artifacts in the data ("Contra", "Agrees to rec", "Other current assets") are **not** prepayment sub-types — **"flag as data-quality exception" is a valid AI verdict**, not "force into a bucket." A classifier that *must* pick a bucket will confidently mislabel a mis-post. Tie invariant is non-negotiable: **Σ sub-categories = account total, to the cent, at every instant.**

**R5 — AI classifies the unclassified bucket — but only the *label*, never the *figure*.** This governs both R3 and R4. Two questions must stay separate:
- *"Where does this item belong?"* → **AI proposes freely** (with confidence), human confirms. This is the upside; the unclassified bucket is the **queue AI works through**, not a dead end.
- *"Is its figure in the closing total?"* → **YES, unconditionally, from the moment it lands**, regardless of classification status.

If an item only counted *after* AI labelled it, AI confidence would silently drive the bottom line (low-confidence item parked → total quietly drops → roll-forward still appears to tie because opening was computed the same wrong way). That is the exact failure the architecture exists to prevent. **Lifecycle:** item rolls into the total immediately under its account (deterministic) → AI proposes a sub-classification + confidence → human confirms → item moves from "unclassified/Other" into its proper sub-line. The total is identical before and after; only the **breakdown** sharpens. AI improves *presentation*, never moves *money*. "This doesn't belong here → flag" is always an allowed verdict.

**R6 — Dedup key: configurable composite + collision guard, not a fixed triple.** True SAP posting key ≈ Company Code + Document Number + Fiscal Year + **Line Item (BUZEI)**. Default key = Company Code + Document Number + Fiscal Year + Object key. (i) Only dedup rows that are **exact duplicates across all material fields**. (ii) If the key collides on rows with **differing** amount/account, **flag "key not unique — possible missing line field"** rather than merging — merging would destroy real lines. Check whether any of the 29 Investments columns is a line/item indicator (BUZEI) and fold it into the key if so.

**R7 — Today's level path.** Both samples are GL-level. **Scaffold the input-level detector and the region→level interface; implement only the GL path.** Phase 1b (derivation) stays a **defined-but-stubbed module** that raises "not implemented / no sample" rather than guessing — build it against a real sub-ledger/transactional sample when one appears, never speculatively.

**Cross-cutting principle (apply everywhere, including cases not spelled out):** build the interface/abstraction for the general case, implement only the specific case you have a test for, and never write complex code against zero test data.

---

## 2.2 Round-3 locked decisions (after Phase 1 ingestion proven on the real GL files)

**R8 — AI-mediated clarification loop (the interactive resolution machinery; GPT-5.1 for every AI role).** Whenever the engine hits something it cannot resolve **deterministically** — quarantined/column-shifted rows, missing period window, unmapped reference code, control accounts like "Contra" / "Agrees to rec", a non-unique dedup key, an unreconciled sub-ledger — it must **never guess and never silently drop**. It:
1. **Queues a structured open question** and **applies the safe default** (the item stays held-out and keeps breaking the tie; the affected note is PARTIAL/BLOCKED).
2. **After the run completes — batched at the end, never mid-run** — GPT-5.1 phrases the queued questions in plain language for a finance user.
3. The user answers; **GPT-5.1 interprets the answers into structured resolutions**; the **deterministic engine recompiles** the FS with them applied.
4. Each resolution is stored as a **confirmed fact** (value + approver + timestamp) so re-runs never re-ask.

**Invariant:** AI **phrases and interprets**; deterministic code **applies** — the AI never edits a number itself. Same answers → same FS (**idempotent recompile**). Unanswered → safe default holds and the note shows PARTIAL/BLOCKED.

- **One interface, two renderers:** build the **question queue** as the interface; render **CLI prompts now**, **in-app review/Q&A panel** when the UI lands (Phase 5) — same queue, no rework. This is the interactive front-end to the Phase 5 gap report, riding the Phase 7 re-runnable + state-persistence machinery.
- **Question record shape:** `{ item_ref, category, what_is_ambiguous, why_it_matters (e.g. SAR tie impact), candidate_resolutions[], default_if_unanswered, status }`.
- **Timing exception:** most questions batch at the end, **but the period window is a blocking input Phase 2 needs up front** to do the opening/movements split at all — so **ask the period-window question at the start of a run** (or pull it from saved config); everything else queues for the end and leaves its note PARTIAL until answered.

**R9 — Held-out money must break the tie (non-negotiable).** Any quarantined/held-out amount must make the roll-forward report **"not tying — N rows held out (~X SAR)"**, never a clean tie. A clean tie while material rows sit in quarantine is a **bug** — the whole point of the architecture is that money the tool couldn't place does not silently vanish from, or appear to balance, the statement. *(Current samples: +10,869,821.51 and −70,000,000 → ~−59.1M net held out.)*

**R10 — Quarantined-row correction discipline.** When a shifted row is corrected (by a human, or by a future recovery routine), validate the **whole row field-by-field against a clean row** — if the account slid a column, the amount/sign/date likely slid too. The real danger is **recovering the account but reading the amount from the wrong column**. Round-number manual journals (e.g. −70,000,000) are likely reclasses, not ordinary postings — read their `Text`/`Reference` and confirm they belong in this note before reinstating. The tool must surface **all cells of the row** for this check and **never auto-recover**.

> **Sample-entity note:** the obfuscated "XYZ Company" is NEOM; the best end-to-end accuracy check is tying the windowed, rows-resolved figures to NEOM's actual note balances when available.

**R11 — Units are absolute SAR; any disclosure scaling is explicit config (standing instruction).** GL amounts are absolute SAR (verified: sub-SAR cents present). A note disclosed in thousands/millions must apply that scaling as **explicit config in the note module** — never silently inherited. **No number is presented as a note figure until the Investments scale/unit is set explicitly.**

**R12 — Provisional status is first-class; Prepayments stays PARTIAL until the queue clears (standing instruction).** `TrialBalance.status()` returns BUILT only when nothing is provisional; otherwise PARTIAL with reasons. An **unconfirmed/defaulted period window makes the opening/movements split and as-of date provisional** (the closing still telescopes) — so it is a PARTIAL reason, visible on the split, not just the closing. Prepayments is **PARTIAL-pending** (held-out rows + unconfirmed window + un-dedupable key) and must be carried as such into Phase 3/4, never BUILT, until resolved.

**R13 — Date cells may be raw Excel serials.** `posting_date` arrives as ISO strings, `yyyymmdd`, or bare Excel serials (e.g. `44196`). The period engine normalises all three; year classification still prefers the `fiscal_year` field. A serial-derived year that disagrees with `fiscal_year` is a candidate clarification (fiscal_year/date mismatch).

**R14 — Lone-amount rows are sheet subtotals, not postings; use them as a control keystone.** A row blank in every identity field (no account, date, document, object key, reference, or label) but holding an amount is a **sheet footer/total**, not a posting — summing it double-counts the sheet. The ingester excludes such rows from postings and records them as **control totals**. This gives a real balance keystone for a single-note slice: **closing + held-out == Σ control totals** (held-out is added back because the footer was struck before those rows were quarantined). *Found in Prepayments: 4 footer rows (774,572,767.18) had inflated the note to 1,608,275,712.85 — 2.08×; the true balance is **774,572,767.18**, which the books now reconcile to at residual 0.00. The lesson generalises: an internal tie (leaves sum to the face line) proves wiring, not magnitude — an independent control total proves magnitude.*

**R15 — In a note's "Other" bucket, separate opening take-on from genuinely-missed types.** When clearing the Prepayments queue, do **not** run the AI labeller over all of "Other" and call it done. First split: (a) **opening/take-on brought-forward rows** — a roll-forward concept that belongs in an *opening* line, a structural reclass, **not** the AI's job (e.g. negative Advances/Deposits are take-on credit positions, not reversal rows the keyword caught); (b) **genuine prepayment types the seeded keywords missed** — the *only* AI-loop work. Otherwise the AI confidently invents sub-categories for brought-forward balances. **Implemented:** `is_brought_forward()` reclasses to an "Opening balance (brought forward)" line *before* classification; verified — opening 389,862,362.02, Prepaid 381,422,122.34, and "Other" shrank to 33 genuine current rows (60,784,904.40), tie preserved.

**R23 — The unit label is DERIVED from the scale; headline and table must be in the same unit.** A free-text `unit_label` decoupled from the divisor is how a note shows absolute SAR under a "SAR'000" header — a 1000× lie, the silent-magnitude class in presentation. Fixed: `Presentation.unit_label` is a property of `scale` (one source of truth), and `status_line` presents the headline figure AT the confirmed scale with that label (withheld until confirmed, R11) so it matches the table. This matters beyond cosmetics — the TB↔GL reconciliation depends on both sides in a known, labelled, consistent unit. Guard (R21): `test_unit_label_equals_the_unit_the_figures_are_in` renders at two scales and asserts the label tracks the scale (not hardcoded) and figure × scale(label) == raw, per note, in Excel/PDF.

**R21 — Every silent-failure near-miss leaves behind an ASSERTION, not just a patch.** Turn each hard-won lesson into a permanent invariant the suite enforces, so the *class* can't recur. Done: `test_partial_note_never_renders_as_built` (queue-silently-empties class). **Owed (noted, not today):** an assertion that an independent control total either exists or is explicitly marked absent (the double-count class), and a check that the **served** model matches the pinned string (the alias-drift class). When a UI gate, an export caveat, or a tie check is added, ask "what silent failure would make this look fine while being wrong?" and assert the negation.

**R22 — A UI changes WHO touches the tool; human-in-the-loop steps must be unskippable gates.** The UI is the first surface a non-expert may drive with their own GL, shifting risk from "are the numbers right" to "can someone misread what the tool says." So: region-confirm, field-map-confirm, and mapping-confirm are **gates, not suggestions** — the next step does not build until each is explicitly confirmed (clicking through on defaults must be impossible, or the confirm-loop is an empty formality). The clarification Q&A panel renders the **same queue** with the **same directional honesty** (show the tie impact / which way the number moves *before* the user answers — a friendly prompt must not hide what's at stake). PARTIAL / magnitude-unverified status **travels with the note on the same screen** (status adjacent to figures, exactly as inline-at-total does in the PDF) — never only on a separate gap-report tab, or a user who looks only at the notes screen sees clean numbers.

**R20 — Provisional status must state DIRECTION, not just "PARTIAL"; and presentation must not read as completeness.** Open items are not noise that nets to zero. Prepayments' closing reconciles **downward** to the control total (774,572,767.18) once the held-out rows reinstate, with reclassification and recovery rows likely reducing it further — so the status says "skews downward", not a neutral PARTIAL (`Note.provisional_outlook`). Phase 5's trap is that polish reads as finished: the gap report renders **status, the magnitude-unverified label, and the outlook at least as prominently as the figures** (banner before numbers, never a footnote), and every channel (CLI now, Excel/PDF/UI later) renders that one model — no second prettier path that drops the caveats. The clarification Q&A is the **same** queue everywhere (one interface). The proposals artifact is **stamped with the model snapshot** that produced it (reproducibility hygiene).

**R19 — Pin the model to a dated snapshot, not a floating alias.** The AI role uses `gpt-5.1`, but that alias silently resolves to the current snapshot (it served `gpt-5.1-2025-11-13`). For reproducible proposals (re-runs must not reclassify on model drift), `config.py` pins the **dated snapshot**; bump it deliberately, never silently. The only LLM call in FS-Gen is the proposer — all deterministic paths (incl. the synthetic fixture) use no model. Confirmed via `response.model`. When an AI proposal is confirmed, the stored fact records the approver + timestamp (R8); the not-a-prepayment verdict becomes a **flagged holding line inside the note's own total** — finance reclassifies, the tool never relocates the money.

**R18 — Config vs engine is a standing guard; a synthetic fixture proves generality.** Every data-specific fact must live in **config** (a seeded/injectable object), never accrete into the engine — engine = overfitting, seeded row = design working. The keyword taxonomy is now an injectable `PrepaymentTaxonomy`; the header map, reference-code map, and account→note/measurement-type rules are seeded config. `tests/test_synthetic_gl.py` (a GL deliberately unlike both real files) is the permanent proof that the general behaviours hold on an unseen file. See the **Overfitting audit** in `documentation.md` for the full general-vs-data-shaped ledger, including honest caveats (SAP sheet-name parsing and brought-forward keywords still live in the engine; the `…9900` allowance convention and the footer keystone's *availability* are data-shaped).

**R17 — The AI labels only rows that HAVE a label; never blank or data-quality rows.** The R15 residual was not uniform: of the 33 "Other" rows, ~22 (~13.1M) are vendor-labelled prepaids the AI can name (insurance, software, subscriptions, advertising), but **3 are blank-label real postings totalling 47.63M (incl. a single 45M, doc 2600000272)** and ~8 are oddities (FX variance, accruals, shifted-description amount-strings). A blank label is **not AI-labelable** — handing it over invites a hallucinated classification of material money. So before the AI runs, the surface is further split: labelled keyword-misses → AI; **blank-label rows → source/description recovery query** (the 45M is also a magnitude item to explain); oddities → flag-don't-bucket. Same principle as brought-forward, one layer on: the AI never sees what it cannot legitimately read.

**R14 fixes the CLASS, not the footer instance.** `blank_account_disposition(rec)` governs every row whose own account is blank (i.e. would inherit the sheet's account): inherit **only** if it carries its own **transactional identity** (document / object key / date / period / reference) → `continuation`; blank but for an amount → `subtotal` (control total); a label but no account and no transactional id → `orphan` (header/annotation, flagged, never absorbed). A mere label is not enough — headers and totals have labels. Verified on the data: 1629 own-account, 383 continuation, **0 label-only**, 4 footers — so the hardening flags the whole class (stray totals, section headers, carried-down values) while changing no real number. *Residual boundary (stated, not hidden): a total row that prints its own account is structurally indistinguishable from a minimal trial-balance row and needs region detection, not a row heuristic.* **This residual and R1's deferred region detection (region = sheet, v1) are the same underlying limitation seen from two directions — real table-region detection closes both at once (two symptoms, one fix).**

**R16 — Internal ties prove wiring, not magnitude; an unanchored note must say so.** The Prepayments overstatement held a cent-perfect internal tie the whole time — so a green internal tie (Σ leaves = face line, Σ sub-categories = total) is **not** evidence the magnitude is right. Magnitude needs an **independent anchor**. Prepayments got one by luck (sheet footers → control keystone). **Investments has none** — the workbook is 14 GL sheets with an account on every row, no summary/reconciliation/footer, and no prior-period or custody figure in scope; the old ~36.7M-in-thousands figure is a *different* entity (AMNB), not an anchor. Two distinct things must not be conflated: the **data unit is known** (absolute SAR, verified via sub-SAR cents — not a 100× ambiguity), but the **magnitude is unverified**. Therefore Investments ships labelled **"internally consistent; magnitude unverified — no independent control total in source"**, stated on the note, not left implicit — and any external anchor (prior-period note, audited opening, custody/portfolio statement) should be requested from finance.

**Phase 4b pre-commitments (locked):** (1) **R11 is a hard gate** — no presented figure before the unit/scale is confirmed; (2) **assert FVIS carries no ECL leaf** by design (no `1101…9900` account — verified); (3) **the DOM/INT split must survive into the presented note columns**, not just the lineage — the thing most likely to be flattened going from tree to formatted note; (4) **carry R16** — Investments is the harder, unanchored note; present it with the explicit magnitude-unverified label until an independent anchor exists.

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
| **1** | Ingestion & input-level resolution | Accept a **bulk, heterogeneous batch** of uploads. **Region interface designed for the general case; v1 implements `region = sheet`** (both samples are clean — see R1), with multi-region detection (stacked/side-by-side/interleaved tables) as a later component swap behind the same interface, using AI-proposes-regions → human-confirms-boundaries when built. Per region: format-agnostic field resolver (match on meaning, no column-count assumptions; both 17-col and 29-col in scope, optional fields never required) → account code, SAR amount, sign, segment (DOM/INT), dates, period, reference code. Input-level detector **per region** (GL / sub-ledger / raw transactional — may be mixed), routed accordingly. Required-field validation → exceptions, not crashes. |
| **1b** | GL derivation (when input is below GL level) | **Defined-but-stubbed today (R7)** — both samples are GL-level; raises "not implemented / no sample" rather than guessing, built only when a real sub-ledger/transactional sample appears. When built: transaction → account **posting-rule** mapping (**AI proposes → human confirms → deterministic applies**), then deterministic aggregation into account-level postings. **Reconciliation gate:** if a GL balance is also available, derived GL must reconcile to it and the difference is surfaced; if only source data exists, run the internal **debits = credits** keystone and label output "GL derived from source, not reconciled to an independent GL." Output shape identical to an uploaded GL. *Support the source type in hand first; general multi-source derivation (AP/AR/bank/FA/payroll) is Phase 12.* |
| **2** | Canonical trial balance (§6.1) | Per `entity_id` × `gl_account` × dimension(DOM/INT) → opening (collapsed b/f) + movements (by reference code) + closing, sign-respecting, period parametrised. **Period window asked at run start (R8 timing exception); pull from saved config if confirmed.** **Per-leaf roll-forward check; quarantined/held-out amounts BREAK the tie (R9) — never a clean tie with material rows held out.** `currency` is metadata, not a balance dimension. **Dedup guardrail (R6):** default key = Company Code + Document Number + Fiscal Year + Object key (+ Line/BUZEI if present); dedup only exact duplicates across all material fields; on a key collision with differing amount/account, **flag "key not unique"** rather than merge. **Unresolvable items queue a clarification question (R8), never guessed.** |
| **3** | Hierarchy + seed mapping (§6.2–6.3) | Self-referencing L4→L1 node table + mapping-table schema; seed the two notes' account ranges as `approved_by="seed"`. Roll up by `parent_id` → audit lineage for free. |
| **4a** | Note module — **Prepayments** (simpler; do first) | Single account total (authoritative, deterministic) + **reconciling** sub-category breakdown. Seeded keyword taxonomy (Prepaid / Advances / Deposits / VAT / Other) as the floor; **AI proposes** classifications for the Other fallthrough (R4/R5), human confirms; control artifacts ("Contra", "Agrees to rec") **flagged as exceptions, not bucketed**. **Σ sub-categories = account total to the cent at every instant** (the figure is in the total from the moment it lands; classification only sharpens the breakdown). Note-rolls-to-subtotal check. |
| **4b** | Note module — **Investments, Net** (the stress test) | Classification **from account code** (R2; short text = label only), DOM/INT dimension + note column, gross → less ECL allowance → **net** by measurement type. Movement schedule from the **seeded reference-code config** (R3; unmapped codes → "unclassified movement" bucket that still rolls into closing and is flagged, never dropped). Bank AlJazira Note 5 layout as a **config** template (5.1 net summary, 5.2 by-type DOM/INT, movement schedule); populate only lines with data. Exercises many leaves + contra + segment against the proven pipeline. Note-rolls-to-subtotal checks. |
| **5** | Outputs + UI | **Deliverable at this stage = the two notes (Investments, Net + Prepayments) as the FS output** — not full primary statements (those are Phase 8). Gap report (per-note BUILT / PARTIAL / BLOCKED; keystone `N/A — slice`); audit drill-down (L1 → … → L4 postings); Excel/PDF export; **a NEW Streamlit UI (the legacy Note-5 app does not apply)**: bulk-upload data (GL or source) → table-region confirm → field-map confirm → TB → mapping → notes → **clarification Q&A panel rendering the same question queue as the CLI (R8)**. **Note: validation is NOT deferred to here** — the per-leaf roll-forward (Phase 2) and note-rolls-to-subtotal (Phase 4) checks run upstream; Phase 5 only *presents* them. |

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
3. The wide-layout concern is **largely satisfied** — Investments is a real 29-col export, so the resolver is tested on both widths from day one. Remaining ask: confirm whether real exports carry an explicit **Line Item (BUZEI)** field (affects the dedup key, R6), and whether the **6 reference codes** are the complete real set or others should be expected (R3).

---

## 7. Engineering conventions

- **Package layout:** keep the existing `ai_accountant` package; add new modules (`gl/`, `trial_balance/`, `hierarchy/`, `notes/`, `ingestion/`, `derivation/`, …). Mark the old Note-5 cascade as `legacy/`. **New modules must not import from `legacy/`** so the superseded design cannot leak back in.
- **Determinism:** every number must reproduce identically across runs. Any sector/entity/framework branch belongs in configuration/data, not code.
- **Audit lineage:** every figure must answer "why is this number here?" — traceable from L1 total down to the L4 postings and the mapping rule + approver that placed it.
- **Build general, implement specific (R1/R5/R6/R7):** build the interface/abstraction for the general case, implement only the specific case you have a test for, and never write complex code against zero test data. Apply this even to cases not spelled out here.
- **AI sharpens the breakdown, never moves the total (R5):** any AI classification step must leave every total identical before and after; only labels/sub-lines change. "Flag, don't classify" is always a valid AI verdict.
- **Green-light discipline:** nothing is coded until this plan is approved. Build phase by phase; each phase's checks must pass before moving on.

---

## 8. Open items before coding

**Resolved in Round-2 (§2.1):** Phase 1 heaviness (R1), Investments structure & template (R2), reference-code config (R3), prepayments sub-grouping (R4), AI-classifies-the-bucket lifecycle (R5), dedup key (R6), today's level path (R7). The 29-col correction is applied in §0.

**Still to confirm (non-blocking, in parallel — see §6):** entity status of the four company codes; prepayments reporting close date; presence of a Line/BUZEI field and the complete reference-code set.

**Phasing/layout:** the 4a→4b split, Phase 1b position, and package layout (same `ai_accountant` package + new modules + `legacy/`, no imports from legacy) are confirmed.

→ With Round-2 folded in, this is ready to **green-light Phase 1**. Still no code until then.
