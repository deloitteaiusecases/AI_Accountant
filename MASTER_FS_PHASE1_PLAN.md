# Phase 1 — the master FS structure capability (BS / P&L / OCI from a TB, against a shared master)

> Abhishek's redirect: **before** note-by-note breakdowns, build the capability to generate a bank's
> **Balance Sheet, Income Statement, and Statement of Comprehensive Income** from its trial balance,
> mapped into a **shared, human-approved master structure.** Slice 10 (the broader proposer-loop GUI
> wiring) **stays parked**; this precedes it. **Reuse the existing engine — do NOT build parallel
> machinery.** Engine + CLI + tests, **no UI**, no DB.
> ~~No code until reviewed~~ — **✅ BUILT (2026-06-11)** to this plan with the three tightenings folded
> in (alias-pairing, conservatism, coherent-placement). 22 suites green.

## Result (what to look at)
- **GATE 0 passed:** `validate_seed`/`validate_csv` → **0 mismatches** (SEED↔XLSX and CSV↔JSON). The
  validator caught a real **dash-drift** (4 comprehensive-income labels had a hyphen where the approved
  xlsx has an em-dash) — **reconciled the JSON+CSV to the approved spec** (logged), not loosened. The
  **alias-pairing has teeth** (swapping two `both_naming_differs` aliases is caught). Package:
  `ai_accountant/master_fs/`.
- **`tests/test_master_fs.py`** (9 guards): GATE 0 + alias-pairing; master holds no amounts
  (structural); map-into-seed **both directions** (two labels → one loans concept; "Misc 0099" →
  unsure → unmapped+flagged); render **only populated lines** in master order with the client's labels;
  **comparatives** (two same-client periods → two columns); **propose-addition lands coherently placed**
  (valid section + order, not just appended); **three-store isolation** (AlJazira's mappings never reach
  SAAB); **preparer provenance**. `scripts/master_fs_check.py` shows GATE 0 → render → comparative.
- **Three stores, DB-ready, no DB:** `MasterStructureStore` (global) · `ClientMappingStore` (keyed by
  client) · `ProvenanceStore` (audit). Reuses `propose_face_mappings`/`propose_seed_mapping` (pinned
  `gpt-5.1-2025-11-13`, labels-only). Slice-10 GUI later sits over these same stores/provenance fields.

## The defining property (drives every decision)
**The master structure is fixed and human-approved; the AI maps INTO it and proposes ADDITIONS — it
never invents structure, and the master never holds a single amount.** Every classification carries
its provenance (preparer / AI-proposed-confirmed / AI-assumed); every number is deterministic; amounts
are never sent to the model. Same boundary as the whole project, applied to this new surface.

## GATE 0 (first, before anything builds on the seed) — validate the JSON against the approved xlsx
`seeds/master_fs_structure_seed.json` is the **data the tool loads**;
`seeds/Master_FS_Structure_Seed_AlJazira_SAAB.xlsx` is the **human-approved spec Abhishek signed off**.
**The JSON is correct only if it faithfully represents the xlsx — confirm that match before building
anything on it.**
- A **one-time validation** reads the xlsx's cell **text** (labels / sections / order) and diffs it
  against the JSON: every JSON concept must appear in the xlsx (no AI/JSON invention), every xlsx line
  must appear in the JSON (nothing dropped), and the sections + presence + order must agree.
- **Validate the per-concept alias PAIRING, not just string presence (tightening).** The 29
  `both_naming_differs` rows each carry two labels — AlJazira's and SAAB's — mapping to one concept. A
  naive "do both strings appear somewhere in the xlsx" check would pass a JSON with the aliases
  **swapped** (AlJazira's label filed under SAAB and vice-versa), which would render every client FS
  with the **wrong bank's wording.** So assert the **bank↔label pairing per concept**: for concept X,
  `label_aliases.aljazira` == the xlsx's AlJazira cell for that row AND `label_aliases.saab` == the
  xlsx's SAAB cell — not merely that both strings exist. (Same lesson as PP&E per-class pairing: "both
  present" is not "correctly paired.")
  Any mismatch is surfaced for human sign-off; **the build does not proceed on an unvalidated seed.**
- The xlsx is read for **validation only** — it is a colour-coded human reference, **never parsed as
  runtime data.** The runtime tool loads **only the JSON.** This is what earns the seed its
  `provenance_seed: "human_approved_template"` — proven, not asserted.
- Confirmed shape to validate against: **60 concepts** — balance_sheet 23 (ASSETS / LIABILITIES /
  EQUITY), income_statement 27 (OPERATING_INCOME / OPERATING_EXPENSES / RESULT), comprehensive_income
  10 — each with `concept_id`, `canonical_concept`, `label_aliases{bank→label}`, `presence`
  (both / both_naming_differs / aljazira_only / saab_only), `order`. The `.csv` is a flat 60-row copy;
  validate it equals the JSON too (so a diff-friendly copy can't drift).

## The architecture (reuse the existing engine)

### 1. The master structure store — seeded from the JSON, fixed, NO amounts
Load the validated JSON into a **`MasterConcept` store** (the union of AlJazira + SAAB face lines,
liquidity-ordered, no current/non-current split — bank-standard; one canonical concept per line). Each
record: `concept_id` (stable), `statement`, `l0_section`, `l1_group`, `canonical_concept`,
`label_aliases`, `presence`, `order`, `provenance` (`human_approved_template` for the seed). It is
**global, shared across all clients, and holds structure only — never a number.**

### 2. Map-into-seed + propose-additions (reuse propose-confirm-store, do NOT invent structure)
A client uploads a TB (mapped **once**, reused each period). Each TB account maps to a master
`concept_id` **by signal/meaning, not code** — reusing the de-hardcoded signal mapping (so "Financing"
and "Loans and advances" both map to the one loans/financing concept). The **client's own label is
preserved for display** (its alias). Mechanism, reusing existing machinery:
- the **master `canonical_concept` list is the candidate vocabulary** passed to the existing
  proposer (`propose_face_mappings` / `propose_seed_mapping`, labels-only, pinned model) →
  account → concept proposal + confidence + evidence;
- **human confirms** (the real confirm step; low-confidence/'unsure' flagged) → stored in the
  per-client mapping store with provenance;
- a TB line **no concept covers** → the AI **proposes a NEW master concept** (a structural addition) →
  **human confirms → appended to the master store** (provenance: proposed-confirmed). **Structure only;
  the master never gains an amount.** This is the existing propose-confirm-store flow, not a new one.

### 3. Render only the populated subset
The client's FS renders **only the master lines its TB populates** — unused concepts are omitted. The
master defines the full ordered structure; each client shows its subset, in master order, with its own
display labels.

### 4. Comparative columns = two TBs of the SAME client, same mapping
Comparatives are a **second TB of the same client (prior period)** run through the **same confirmed
mapping** — current TB fills the current column, prior TB the prior column. **Same bank, two periods —
NOT bank-vs-bank.** Both columns render against the one master structure (the union of lines either
period populates, in master order).

## Store shape — DB-ready, but build NO database
Three **logically separate** stores (a future DB swap, not a back-fill):
1. **Global master structure** — the `MasterConcept`s (seed + confirmed extensions). Shared.
2. **Per-client confirmed mappings** — `client_id → {account → concept_id, client_label, provenance}`.
   **Keyed by client so AlJazira's mappings never leak to SAAB.**
3. **Provenance / audit** — per confirmed mapping/extension: who, what, confidence, when.
Each record carries the fields a DB would need (**stable IDs, provenance, master-vs-per-client
distinction**) so deployment is a swap. **Built entirely on files / in-memory** (JSON + dataclasses) —
**no DB engine, no connections, no migrations, no multi-user concurrency, no confirmation-authority
roles.** Those are real but speculative against a far-off deploy — **recorded as deployment-time
follow-ups, not built.**

## Reuse vs new (explicit)
- **REUSE:** TB ingestion (`ingest_tb`); signal-based mapping + the de-hardcoded confirmed store;
  propose-confirm-store (`ai_propose.py` proposers, pinned `gpt-5.1-2025-11-13`, labels-only); face
  assembly (`assemble_face` / `FaceStatements`); the honesty/provenance discipline; the recompile loop.
- **NEW:** the **`MasterConcept` store** (seeded from the validated JSON); the **map-into-seed +
  propose-additions** flow (account → concept; unmatched → propose new concept → confirm → append);
  **render-only-populated-lines** (the subset assembly against master order); and the
  **comparative-from-two-same-client-TBs** assembly (two columns, one structure).

## The honesty discipline — carried forward UNCHANGED
- **Amounts never sent to the AI** — the proposers stay labels-only (verified; prompts unchanged).
- **Structure proposed by AI, every number deterministic** — the AI maps/extends; arithmetic is code.
- **Provenance on every mapping** — preparer-provided / AI-proposed-confirmed / AI-assumed — and on
  every master extension.
- **The master never holds amounts** — amounts live with each client's TB, not in the master store.

## Proposer-wiring coordination with slice 10 (so they don't duplicate)
This phase uses propose-confirm-store, so it needs proposer wiring. **It is a SUBSET / precursor of
slice 10, at the engine + CLI level:** call the existing proposer → confirm → store into the
master/per-client stores, with provenance and the AI-assumed distinction. **Slice 10's GUI layer (the
confirm UI, the AI-answer checkbox, the mappings-applied front page) sits on top later, over the SAME
stores and the SAME provenance/AI-assumed fields** built here — so the two coordinate rather than
duplicate. (Recommendation: build the engine + CLI flow now; slice 10 surfaces it in the GUI after.)

## Parked beneath this (unchanged)
- **Note-by-note breakdowns** — the existing note modules (Investments / Prepayments / PP&E) plug into
  the master concept later, as drill-downs of a master line.
- **Generated-vs-published validation** — a later reconciliation feature (compare the generated FS to a
  bank's published FS).
- **Slice 10 — the broader proposer-loop GUI wiring** — parked; this phase builds the engine subset.
- **The matcher (Bucket B)** and **independent sign-off** — external/parked.

## Guards (tested — to confirm at build)
1. **Seed fidelity:** the JSON (and CSV) faithfully represent the approved xlsx — 60 concepts, labels,
   sections, presence, order all match; no JSON line absent from the xlsx, none dropped.
2. **Master holds no amounts:** a structural assertion that no `MasterConcept` record can carry a value.
3. **Map-into-seed by signal — BOTH directions:** (a) two differently-labelled accounts ("Financing" /
   "Loans and advances") map to the **one** loans/financing concept, client label preserved; AND
   (b) **conservatism (tightening):** an ambiguous / genuinely unfamiliar TB line comes back **unsure →
   unconfirmed → unmapped → flagged**, never force-mapped to the nearest-looking concept (the "Misc
   0099" case from slice 7). The unsure-stays-unmapped direction is what protects the surface — without
   it, map-into-seed could silently stuff an unrecognized account into a plausible concept.
4. **Render the subset:** a client TB populating N of 60 concepts renders exactly those N, in master
   order, with the client's labels — unused concepts omitted.
5. **Comparative:** two same-client TBs (two periods) render two columns against one structure.
6. **Propose-addition lands with a valid PLACE (tightening):** a TB line matching no concept → proposed
   new concept (fake client) → confirm → appended to the master with provenance **AND a coherent
   position** — a valid `l0_section`, `l1_group`, and a liquidity `order` slot (the AI proposes where it
   sits, the human confirms the placement). Assert the appended concept has a **valid section and order**
   (renders in the right place), not merely that it exists — "the master grew **coherently**," not just
   "the master grew." An unconfirmed proposal does NOT enter the master.
7. **Isolation:** a per-client mapping store keyed by client — AlJazira's mappings never reach SAAB.
8. **Provenance + labels-only + pinned model:** every mapping carries provenance; no amount enters a
   payload; the model string is `gpt-5.1-2025-11-13`.

## Sequencing
1. **GATE 0** — validate JSON↔xlsx (and CSV↔JSON); human sign-off the seed is faithful.
2. **Master store + render-the-subset** on the seed (no AI yet) — prove BS/P&L/OCI assemble from a
   mapped TB against the master, populated-subset only.
3. **Map-into-seed + propose-additions** (reuse the proposers) + the three-store shape + provenance.
4. **Comparative** (two same-client TBs).
Then slice 10 can surface all of it in the GUI, and the note modules plug into the master lines.

The discipline this phase locks: **a fixed, human-approved master the AI maps into and extends but
never invents; only populated lines rendered; comparatives from the same client across periods; every
classification carrying its provenance; and not one amount in the master — the project's honesty
boundary, applied to the master-FS surface.**
