# Slice 6 — the PP&E note (first non-financial note; the generality checkpoint)

> The first commercial/non-financial note module. Its real job is to answer one question: **is the
> engine sector-agnostic, or did Investments/Prepayments quietly bake in financial-sector
> assumptions?** Engine + CLI + tests, **no UI.**
> ~~No code until this plan is reviewed~~ — **✅ BUILT (2026-06-10)** to this plan after the hardcoding
> audit + the architectural correction. Built P-C-S, zero new hardcodes, A2 prefix map untouched. All
> 28 suites green.

## Result against the REAL fixtures (re-run after the lookalike was caught)
**First built against an in-memory lookalike that merely shared the totals (929/−221/708) — caught and
corrected.** Now proven against `GL/PPE_Reconciliation_Q1_2025_XYZ_Company_GL.xlsx` (7 accounts, 56
postings) + the populated TB PP&E line (708,000 SAR'000: Land 150,000 / Buildings 333,000 / Plant
193,000 / Vehicles 32,000). The note pairs cost+contra → per-class NBV, keys by the cost code, scales
to '000, and reconciles to the TB line.
- `tests/test_ppe_note.py` — 7 guards on the real data: NBV reconciles to the **real 708,000 line**
  (GL Σ 708,000 == TB 708,000, gap 0.0) → **BUILT**; both schedules tie and net; **per-class figures
  match the GL EXACTLY** (Buildings 435/333, Land 150/150, Plant 280/193, Vehicles 64/32 — millions);
  **per-class pairing** (a mis-pairing that still totals 708m is **CAUGHT** — grand ties, per-class
  wrong, Plant flagged); **Land has no depreciation**; **contra by SIGNAL** (real labels + a
  non-conventional `88888802`, 'unsure' unconfirmed); **unmapped ref → Unclassified-flagged**; the
  **lie BLOCKS at two magnitudes**.
- `python scripts/ppe_note_check.py` — shows the note, the per-class catch, and the lie on real data.
- **New files:** `fs_notes/ppe.py`, `MovementConfig`+PP&E configs in `reference_codes.py` (B1,
  additive — Investments untouched), `propose_ppe_structure`/`ConfirmedPPEAccount` in `ai_propose.py`
  (A1/A2 by signal). **Identification = AI judgment; netting = deterministic arithmetic.**
- Derived TB ties by construction → proves **breakdown↔line**, not independent sign-off (parked). The
  slice-5 contract did not regress; nothing in the proven notes moved (A2 prefix map untouched).

## LOCKED SCOPE (post-audit, 2026-06-10) — read first
The hardcoding audit (`HARDCODING_AUDIT.md`) ran before this slice. Legacy-import grep came back
**clean** — the active spine imports nothing from the deprecated Note-5 cascade, so the brittle cluster
is exactly **A1–A4 + B1** and it is bounded. Decisions:
- **Slice 6 = PP&E clean.** Build PP&E **propose-confirm-store from the start, adding ZERO new
  hardcodes.** Fix inline **only what PP&E forces:** A1/A3 (contra ID by signal → confirm → store),
  B1 (per-note reference config), C1 (rename the dimension to `sub_class`), and A2's **value-by-signal
  for PP&E's asset class only.**
- **⚠ SLICE 6 DOES NOT TOUCH THE EXISTING A2 PREFIX MAP** (`hierarchy/seed.py` `_INV_MT` /
  `_inv_prefix`). The Investments/Prepayments prefix + literal-account entries stay **exactly as-is**
  through slice 6 — PP&E simply **does not add itself** to that map, and PP&E account→note/class is
  done the new propose-confirm-store way. **No editing the existing prefix map "while in there"** —
  that is scope creep into proven code without a no-regression harness. Nothing in the proven notes
  moves in slice 6.
- **Slice 7 (separate) = de-hardcode the seed.** Retrofit Investments + Prepayments off the A2 prefix
  map and the A4 literal `{"10400001"}` set, with a **byte-identical no-regression proof** (de-hardcoded
  result == hardcoded result, exact, on the existing fixtures). That proof is the slice's whole point,
  and isolating it is what keeps the cause unambiguous (new-note vs refactor-proven-notes never mixed
  in one suite). **B2 + D1/D2** fold into the slice-4 GL-path follow-up; no action on B3, C2, D3, the
  number engine.

## The defining property (drives every decision)
**PP&E is a TWO-LAYER movement schedule, and that two-layer coupling is the genuinely new thing.**
Investments had ONE schedule (the net rolling forward). PP&E has **two parallel roll-forwards that
each roll forward AND net against each other:**
- **Cost** roll-forward: opening + additions − disposals + transfers → **closing cost**.
- **Accumulated depreciation** roll-forward: opening + depreciation charge − disposals → **closing
  accum dep** (a contra).
- **Net book value = cost − accumulated depreciation**, per class and in total.

Everything the slice does is organised around proving the **new** part (two coupled schedules + the
per-class pairing) and **not regressing** the slice-5 contract on the reused parts.

## Reuse vs new — state it explicitly, focus the guards on NEW

### REUSE (proven; do not re-implement, do not re-prove beyond a smoke check)
- **The TB-line anchor + `LineRecon` reconciliation (slice-5 contract).** `tie_ok` = "reconciles to
  the TB line," one path, no new mechanism. PP&E reconciles its **NBV** to the PP&E TB line (see
  below).
- **The contra-netting-to-net SHAPE.** `cost − accumulated depreciation → NBV` is structurally the
  same as Investments' `gross − ECL allowance → net`. Reuse the gross/contra/net section shape and its
  `*_ties` assertion.
- **The reference-coded movement-schedule MACHINERY** (`MovementSchedule`: opening + Σ movements →
  closing, `ties`, unmapped code → an "Unclassified movement" line still in closing, flagged). Reuse
  the machinery; PP&E supplies its own CONTENT (codes/lines).
- **"A class that carries no contra by design"** assertion. Investments: FVIS carries no ECL (IFRS 9).
  PP&E: **Land carries no accumulated depreciation** (land isn't depreciated). Same pattern, new fact.
- R11 presentation gate, R16 anchor/magnitude semantics, status composition, the R8 recompile loop.

### NEW (the genuinely new structure — the guards live here)
- **Two coupled roll-forwards.** Cost and accumulated depreciation each roll forward independently and
  then net. Investments' single `MovementSchedule` becomes a **pair** (cost schedule + dep schedule)
  with NBV derived from both closings.
- **Per-class cost ↔ accumulated-depreciation PAIRING.** Each asset class's cost account paired with
  its CORRECT accum-dep contra — derived from account structure, and **asserted**, because a wrong
  pairing can still produce a right-looking grand NBV. (This collision was caught while building the
  fixture; the guard exists specifically to catch it.)
- **The asset-class dimension** (Land / Buildings / Plant / Vehicles), sourced from the account code —
  replacing Investments' measurement-type (FVIS/FVOCI/AC) and Investments' DOM/INT segment (PP&E has
  no domestic/international split).

## The reconciled figure — NBV (decided, stated)
The TB PP&E line carries **net book value.** All PP&E GL accounts — cost accounts AND their
accumulated-depreciation contras — route to the one PP&E TB line, so the line's raw = Σ(cost) +
Σ(accum-dep contra) = **NBV** (929,000,000 + (−221,000,000) = 708,000,000). The note therefore
**reconciles its NBV (708M) to the PP&E TB line raw** — exactly as Investments reconciled net
(gross + ECL contra) to its line. Cost and accumulated depreciation are the internal two-schedule
breakdown beneath that reconciled NBV. Same anchor, same one path: the PP&E `LineRecon` over all PP&E
accounts.

## Architectural correction — "deterministic" ≠ "a code pattern" (read before the findings)
The findings below were first drafted to replace one hardcode with another (e.g. `…9900` →
`1104010X ↔ 1104019X`). **That is wrong, and it would relocate the brittleness instead of removing
it.** The correction governs all four findings:

- **Deterministic means reproducible with an audit trail** — same inputs → same answer, every run. It
  does **not** require a code pattern. A code pattern is brittle: it breaks on the second real client,
  whose chart of accounts isn't NEOM's (unfamiliar codes, foreign-language descriptions, or no codes
  at all). Replacing a hardcoded pattern with another hardcoded pattern doesn't fix a finding — it
  moves it.
- **The right architecture is the one the 20/20 mapping run already proved:** *AI proposes the
  structural fact from whatever signals exist → human confirms → deterministic code re-applies the
  confirmed fact identically forever after.* **The determinism comes AFTER confirmation, not from a
  code pattern.** (The 20/20 run resolved "FVIS – Mutual funds → Investments" by description,
  distrusting the code, and got the deliberately code-swapped Revenue/Cost-of-sales right by trusting
  the label over the code. Contra identification is the same shape: read the meaning, don't match the
  pattern.)
- **The signal hierarchy** when codes are weak or absent: explicit code/range → **description/label
  (strongest in practice)** → sign / balance behaviour → reference / movement pattern → sheet
  position. The AI works down it with whatever's available, proposes **with a confidence**, and on low
  confidence or conflicting signals **surfaces a question rather than committing** (R24 conservatism /
  flag-don't-force / "unsure" is a valid verdict — the discipline already proven in slice 4 and the
  AI-mapping loop). A code pattern (e.g. `…019X`) is at most **one optional hint** when codes happen
  to be structured that way — never the mechanism.

**THE ONE HARD LINE THAT DOES NOT MOVE.** AI does the structural **guesswork** — classification,
contra identification, mapping, region detection (**judgment**). Deterministic code owns **every
number** — roll-forwards, netting, reconciliation, totals (**arithmetic**). For PP&E: contra
*identification* becomes AI-propose → confirm → store; contra *netting* (sign-respecting subtraction)
stays deterministic. **Identification is judgment; netting is arithmetic.** "Leverage AI for the
guesswork" must never leak into the number engine — that boundary is the spine of the project.

## The generality question — surface findings, don't paper over them
Investments and Prepayments mapped cleanly partly because the taxonomy was built around them. PP&E is
where any baked-in financial-sector assumption shows. They are the **same root issue**: a structural
fact that was **hardcoded instead of proposed-confirmed-stored.** Each is a FINDING the slice records
and generalises **to the propose-confirm-store architecture above**, not to a new hardcode:

### Finding #2 (RE-DRAFTED) — contra identification by SIGNAL + propose-confirm-store, not a pattern
**The assumption:** contra detection is hardcoded to the …9900 convention (`investments.py`:
`_is_allowance = account.endswith("9900")`). The first re-draft would have swapped it for another
hardcode (`1104010X ↔ 1104019X`) — **rejected:** that breaks on the next client's chart of accounts.

**The fix:** contra identification becomes **AI-propose → human-confirm → deterministic re-apply**,
reading MEANING, not matching a pattern. The AI proposes *"account X is the accumulated-depreciation
contra for the Buildings cost account"* from whatever signals exist, working down the hierarchy:
- **description / label** — "Accumulated depreciation – Buildings" (strongest in practice);
- **sign / balance behaviour** — a persistent credit balance held against a debit-balance asset;
- **reference / movement codes** — `DEP-CHG` movements (depreciation charge), not `ADD-PURCH`;
- **magnitude & position** — a contra sized as a fraction of, and positioned against, a cost account;
- **code/range** — `…019X` paired with `…010X` is **one OPTIONAL hint** when codes are structured
  that way; never the mechanism.

…with a **confidence**, and on low confidence / conflicting signals it **raises a question instead of
committing** (an "unsure" verdict is valid — R24). The human confirms; the confirmed pairing is
**stored and re-applied deterministically forever after** (same propose-confirm-store path as the
20/20 mapping run and the prepayments AI loop — not a parallel mechanism). **Identification is
judgment (AI); the netting that follows (sign-respecting subtraction, cost − contra → NBV) is
arithmetic and stays deterministic.** This works on the synthetic fixture (structured codes) **and**
on a real file with arbitrary, foreign-language, or absent codes — because it reads meaning.

### #1 (sanity-checked) — per-note reference config, entries proposed-confirmed-stored
The reference-code movement config is a single GLOBAL Investments table (`reference_codes.py`:
`MOVEMENT_LINES` + `_REF_TO_LINE`). Generalise to a **per-note** config — but the same correction
applies to its CONTENTS: a new client's reference codes (`ADD-PURCH`, `DEP-CHG`, or some unfamiliar
string) are **not a hardcode to extend by hand** — an unmapped code stays "Unclassified, flagged" and
the **AI proposes its movement line → human confirms → stored** (exactly today's unmapped→flagged rule
married to the AI loop). The seeded set is the confirmed-once store, not a closed list. Per-note
structure is the mechanical part; signal-based mapping of unknown codes is the architectural part.

### #3 (sanity-checked) — the dimension VALUE is proposed-confirmed, not prefix-derived
`MappingEntry.measurement_type` (FVIS/FVOCI/AC) is named for the financial sector; PP&E's analog is
**asset class** (Land/Buildings/Plant/Vehicles). Two layers: (a) **rename** the field to a
sector-neutral `sub_class` carrying "FVOCI" or "Buildings" alike (mechanical — recommended); (b) more
important, the *value* must not come from a hardcoded prefix map (`1101→FVIS`, `1104→Buildings`). The
prefix map is an **optional hint**; the general path is **AI proposes the class from the
description/signals → human confirms → stored**. The synthetic fixture has clean prefixes (the hint
fires); a real file may not (the signal path carries it).

### #4 (sanity-checked) — the seed IS the confirmed-once store, extended via propose-confirm
`build_seed_mapping` hardcodes only Investments + Prepayments. Adding PP&E confirms it extends to a
third note — but the durable shape is: **the seed = the already-confirmed mappings; a new client's
unknown accounts go through AI-propose → confirm → and are appended to the store**, never hand-coded
per client. Slice 6 adds PP&E's confirmed entries the seeded way (deterministic, fixed timestamp), and
exercises the propose-confirm path for an unknown account so it's proven, not assumed.

Anywhere a fifth such assumption surfaces mid-build, it gets recorded here too — and it gets the same
treatment: **propose-confirm-store, pattern as optional hint, never a new hardcode.**

## Guards — focus on the NEW (synthetic GL with a hand-computed answer)
Proven on a **synthetic PP&E GL with a known answer** (56 entries / 7 sheets; cost accounts
11040101–104, paired accum-dep contras 11040191–194 with **Land 11040101 having none**; reference
codes as above; totals **cost 929,000,000 / accum dep −221,000,000 / NBV 708,000,000**). **Labelled
machinery-on-synthetic — NOT a real-data sign-off** (we have no real PP&E GL; the real GLs are
Investments and Prepayments). A synthetic-only proof must not read as real-data verified.

1. **NBV reconciles → BUILT.** The PP&E note anchored to its TB line, NBV 708M reconciles
   (`anchor.gap == 0`), unit confirmed → `status() == "BUILT"`. (Slice-5 contract holding for a
   two-schedule note.)
2. **Both schedules tie, and net.** Cost schedule ties (opening + additions − disposals + transfers →
   929M); dep schedule ties (opening + dep charge − disposals → −221M); NBV = cost − accum dep = 708M.
3. **Per-class pairing is correct — the headline new guard.** Each class's NBV = its OWN cost − its
   OWN paired accum-dep (Buildings cost ↔ Buildings dep, not Plant's). Assert **per-class** NBV, so a
   mis-pairing that still totals 708M is caught. **"Grand NBV ties" must not stand in for per-class
   pairing.** A deliberately mis-paired variant must fail this guard while the grand total still ties.
   **Note (post-correction):** this now guards the **confirmed** pairing — whatever signal produced it
   (description / sign / reference / optional code hint) — not a code-pattern pairing. The deterministic
   netting re-applies the confirmed pairing; the guard proves the *confirmed* pairing is per-class
   right, independent of how it was identified. The propose step is exercised with a fake client in
   tests (no network — same pattern as the prepayments AI-proposer test); what's asserted is
   no-silent-guess + confirm-store + deterministic re-apply + correct arithmetic.
4. **Land has no accumulated depreciation** (the no-contra-by-design assertion) — Land carries cost,
   no dep contra, and is not depreciated; asserted, not assumed.
5. **Unmapped reference code** → "Unclassified movement," still in closing, flagged — proving the new
   **per-note** reference config works (not the Investments table).
6. **The lie still BLOCKS (don't regress slice 5), two magnitudes.** Perturb the TB PP&E line raw by a
   small (a few hundred k) and a large amount → NBV no longer reconciles → **BLOCKED** while both
   schedules still tie internally. The inversion's teeth, on the two-schedule note.

## Explicitly OUT of slice 6
- **The GUI** — still last, and now **five slices behind the engine**: when it comes it is a **real
  slice** (parse → face → anchored reconciled notes, end to end), not a quick wire.
- **The matcher (Bucket B)** — waits on the renumbering-vs-different-account-set answer.
- **The independent keystone sign-off** — finance's own (non-derived) TB.

## Sequencing (after slice 6)
1. **Slice 6** — the PP&E note (this; the generality checkpoint).
2. **Close the GL-path region-detection gap** — re-wire GL `ingest_workbook` onto confirmed regions
   (the slice-4 follow-up); + thread the FaceTB anchor through the `recompute()` orchestrator (the
   slice-5 follow-up).
3. **The GUI** — once there's a complete reconciled flow worth showing, as its own real slice.

Every silent-failure surface keeps its assertion (R21). The new surface here is the **mis-paired
contra that still totals right** — a per-class pairing that lies while the grand NBV ties — and the
guard is: assert per-class pairing, never let the grand total stand in for it.

**The architectural correction this slice locks in:** determinism comes from **propose → confirm →
store**, not from a code pattern; AI owns the structural judgment (identification, classification,
pairing), deterministic code owns every number (roll-forwards, netting, reconciliation). A code
pattern is at most an optional hint. This is why PP&E is the generality checkpoint — it is the first
note that forces the distinction, and the fix generalises to every future client and sector.
