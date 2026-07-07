# Slice 7 — de-hardcode the seed mapping (A2 prefix map + A4 literal)

> **Why (the plain reason):** the tool has to take **any accountant's file**, and the next client's
> codes will differ, be foreign-language, or be absent. So account→structure identification must be
> **signal-based propose-confirm-store, with prefix patterns as optional hints only** — the same path
> PP&E now uses. This retrofits the two proven notes (Investments + Prepayments) off their hardcodes.
> ~~No code until reviewed~~ — **✅ BUILT (2026-06-10)** to this plan after review (3 refinements
> folded: #3 primary + robust, explicit confirmed entries not auto-confirm, C1 pure-rename). All 29
> suites green.

## Result (what to look at)
- `tests/test_seed_dehardcode.py` — **#1** mapping byte-identical to the kept `_legacy_prefix_seed_mapping`
  on the real fixtures (frozen-dataclass `==`); **#2** Investments (4,256,555,000) + Prepayments
  (833,702,945.67) **unmoved**; **#3 (primary)** an unknown account maps via propose→confirm→store —
  (a) confident foreign-language label → maps, (b) ambiguous → **unsure, UNCONFIRMED, surfaced not
  vanished**, (c) contra-by-signal on a **non-110x code** (`77770099`).
- **`seed.py`:** `build_seed_mapping` is now a **store lookup** over `SEED_MAPPINGS` (15 explicit
  confirmed rows) + an optional `confirmed=` extension; the prefix/`endswith`/literal-set logic is gone
  from the runtime path (`_INV_PREFIX_HINT` kept only as a proposer hint). `ai_propose.py`:
  `propose_seed_mapping` / `confirm_seed_mapping`. **C1 pure rename** `measurement_type`→`sub_class`
  (same values; value-setting untouched — the stop condition held).
- **Blast radius = essentially zero synthetic fixes.** The only edit was `test_hierarchy`'s renamed-
  field read; **no synthetic site needed an explicit confirmed entry** — every other synthetic `110x`
  runs through the `face_tb` path, not `build_seed_mapping`. The hardcode was load-bearing in fewer
  places than feared.

> (No "general master structure" framing — the grain TB was just a format template; the derived
> banking TB is the real working file. Don't over-motivate it.)

## What's hardcoded today (the retrofit targets)
- **A2** — `hierarchy/seed.py`: `_INV_MT` prefix map (`1101→FVIS`, `1102→FVOCI`, `1103→AC`),
  `_inv_prefix(a) = a[:4]`, and `a.endswith("9900")` deciding the ECL-contra role. The account's note,
  class, and contra-role are all decided **from the code**, no signal fallback.
- **A4** — `hierarchy/seed.py`: `_PREPAY_ACCOUNTS = {"10400001"}` — a literal account number deciding
  "this is Prepayments."

## The fix — the seed becomes the confirmed-once store
- **`build_seed_mapping(accounts)` becomes a STORE LOOKUP**, not a code computation. A frozen
  `SEED_MAPPINGS` store holds the **already-confirmed** facts (one `MappingEntry` per known account:
  note_ref, face_caption, classification, sign, sub_class) authored with the fixed `SEED_TS`
  (deterministic — re-running reproduces it exactly). For an account in the store → its confirmed
  entry; for an account **not** in the store → unmapped, **surfaced** (as today), then run through
  propose-confirm. **No `[:4]`, no `endswith("9900")`, no literal set** on the runtime path.
- **The store is authored FROM the existing confirmation.** The prefix map *was* the original
  confirmation; freezing its output over the real fixture accounts as explicit confirmed facts is
  exactly "the seed becomes the confirmed-once store." Legitimate, and it's what makes the proof below
  byte-identical by construction.
- **The prefix pattern survives ONLY as an optional hint** inside the proposal step (a weak
  corroborator the AI may use when codes happen to be structured), **never** the mechanism.

## The proofs — #3 is the PRIMARY one (be honest about what each proves)
- **#1 Mapping equality — a regression guard, and circular by construction.** On the real fixtures'
  account sets, new `build_seed_mapping(accounts).entries == ` the old prefix output, field-for-field
  (frozen dataclass `==`, against a kept local `_legacy_prefix_seed_mapping`). **Honest caveat:** the
  store is *authored by freezing the prefix output*, so this is `frozen-output-of-X == X` — it proves
  the **freezing was done right**, nothing more. A regression guard, not the point.
- **#2 Note equality — also a regression guard.** Investments + Prepayments build **identical** on the
  real GLs (Investments BUILT-exact 4,256,555; Prepayments 833,702,945.67; reconciliation + status
  unmoved). Proves **we didn't break the two known notes.**
- **#3 The unknown-account path — THE PRIMARY PROOF (the thing the slice exists for).** The real risk
  de-hardcoding introduces is NOT "known notes break" (#1/#2 catch that) — it's **"an unknown account
  silently fails to map and its money vanishes from a face line."** So #3 proves an account the store
  has **never seen** actually maps via propose-confirm-store now that the prefix logic is gone. **Make
  it several cases, not one smoke test:**
  - **(a) confident map** — a clear label → proposed, confirmed, and it maps to the right note;
  - **(b) ambiguous label → UNSURE, UNCONFIRMED** — the conservatism path: it comes back 'unsure',
    is NOT confirmed, and the account stays **surfaced/unmapped, never silently guessed**;
  - **(c) contra account → contra-by-signal** — a label like "…ECL allowance" is identified as the
    contra (classification contra-asset, sign Cr) through the **new seed path**, as it did for PP&E.
  Exercised with a fake client (no network, same pattern as the PP&E/prepayments proposer tests).

## Blast radius — fix each broken synthetic site with an EXPLICIT confirmed entry (NOT auto-confirm)
The enumeration is the honest core of the slice (it shows where the hardcode was load-bearing). From
the audit grep, it is **small**: almost every synthetic `110x` in tests runs through the `face_tb`
path (the TB's own mapping column), **not** `build_seed_mapping`; the seed path is hit only by
`test_hierarchy` and the note builders, all on **real** accounts already in the store. Any site that
*does* break gets an **explicit confirmed `MappingEntry`** ("this test account is X, stated") supplied
via a `confirmed=` parameter on `build_seed_mapping` — **NOT** a fake-client propose-confirm that
rubber-stamps whatever the proposer says. **Keep them separate:** synthetic tests supply explicit
confirmed mappings; the propose-confirm path is proven by the dedicated #3 test **only** (auto-
confirming fixtures would hide whether the proposer is actually right).

## C1 (measurement_type → sub_class) — FOLD IN, as a PURE rename, under the #2 proof
Approved to ride along. **Stop condition:** it must be **only a rename** — same field, same values
("FVOCI"/"Buildings"), **no change to how the value is set**. Note-equality (#2) proves it safe for
free (the notes build byte-identical; only an internal field name changes). **If folding it in turns
out to require touching the value-setting logic, it is no longer cosmetic — STOP and defer it to its
own slice.** Rename only. (The A2 change to the value's *source* — store vs prefix — is the
de-hardcode, separate from and orthogonal to this rename of the field's *name*.)

## Explicitly OUT of slice 7
- **The GUI / output** — still its own later slice. **Recorded scope for that slice (logged now so it
  isn't lost):** per Abhishek — *"used for creating BS and P&L, and related notes"* — the **face
  statements (BS + P&L) are the headline deliverable**, with notes as their per-line drill-downs. They
  are **computed today** (slices 1–2 build `FaceStatements`) but **not presented** — no export, no
  formatted statement. The output slice must **present BS and P&L as first-class statements with the
  notes hanging off their lines**, not ship notes alone.
- **The matcher (Bucket B)** — waits on the renumbering-vs-different answer.
- **Independent keystone sign-off** — finance's own (non-derived) TB.

## Sequencing (after slice 7)
1. **Slice 7** — de-hardcode the seed (this).
2. **Close the GL-path region-detection gap** — re-wire GL `ingest_workbook` onto confirmed regions
   (slice-4 follow-up) + thread the FaceTB anchor through the `recompute()` orchestrator (slice-5
   follow-up).
3. **The output/GUI slice** — present **BS + P&L as first-class statements** with notes as drill-downs
   (the recorded scope above), as its own real slice.

The discipline this slice locks: **identification is proposed-confirmed-stored, prefix is an optional
hint, and the proof is byte-identical** — the retrofit must reproduce the two proven notes exactly, or
it moved something it shouldn't have.
