# Hardcoding audit — structural-identification assumptions across the engine

> Triggered before slice 6: three findings surfaced in one slice's planning (#2 …9900 contra, #1
> global reference table, #3 measurement_type/prefix map) — a pattern, not three spots. This is the
> deliberate pass that goes looking on purpose, so PP&E is built on a **known** surface.

## What counts as brittle (the tractable distinction)
A hardcoded value is a problem **only** if it is a **structural fact** (what something *is*, where it
*belongs*, how it's *classified*, what it *pairs with*) decided by **matching a pattern with no
signal-based fallback and no confirm step.** Those need **propose → confirm → store** (the determinism
comes after confirmation, not from the pattern). NOT targets: a value used as an **optional hint** with
a signal fallback; a **default/threshold**; a **genuinely universal rule** (IFRS: land isn't
depreciated); and the **number engine** (arithmetic being deterministic is correct and stays).

## The headline result — the brittleness is CONCENTRATED
Everything that decides a structural fact from a **description / label / declared column** was already
built the right way (signal + safe fallback): the Prepayments taxonomy, the field resolver, the TB
level/type/range reads, the brought-forward signals. The brittle cluster is precisely the decisions
made from the **account CODE** — the seed mapping and the Investments contra. That is a small, named
surface, **not "everywhere."** So the remediation is bounded and sequenceable.

---

## A. Code-pattern as the SOLE mechanism for a structural decision → **BRITTLE (needs P-C-S)**
| # | Site | Decides | Why brittle | Fix |
|---|------|---------|-------------|-----|
| A1 | `fs_notes/investments.py:194` `_is_allowance = account.endswith("9900")` | is this account a contra (ECL allowance)? | breaks on any chart where the contra isn't a …9900 leaf (e.g. PP&E's *paired* accum-dep account) | contra ID by **signal** (description "accumulated depreciation"/"allowance", persistent-credit-vs-debit-asset sign, DEP-CHG/ECL refs, magnitude/position) → confirm → store; code suffix = **optional hint**. *(slice-6 finding #2)* |
| A2 | `hierarchy/seed.py:37` `_inv_prefix = account[:4]` → `_INV_MT` | which note + which measurement type? | only works on NEOM's 1101/1102/1103 prefixes; next client's CoA differs | class/note by **signal** (description) → confirm → store; prefix = hint. *(slice-6 finding #3)* |
| A3 | `hierarchy/seed.py:48` `a.endswith("9900")` | contra-role in the mapping | same root as A1 (duplicated) | fold into A1's signal-based contra ID |
| A4 | `hierarchy/seed.py:33` `_PREPAY_ACCOUNTS = {"10400001"}` | is this *the* Prepayments account? | a single literal account number; the next client's prepayments account isn't 10400001 | account→note by **confirmed store** (the seed is the already-confirmed entries; unknowns go through propose-confirm), not a literal set |

**These four are the real target.** A1/A3 are one fact (contra identity) hardcoded twice; A2/A4 are
account→{note,class} hardcoded by prefix/literal. All decide identity from the code with no fallback.

## B. Closed lists that should be open (grow via confirm-store)
| # | Site | Verdict |
|---|------|---------|
| B1 | `fs_notes/reference_codes.py` `_REF_TO_LINE` + `MOVEMENT_LINES` (global Investments movement table) | **BRITTLE-ish** — it IS flag-safe (unmapped → "Unclassified movement", flagged, never dropped) but it's a single global table, not per-note and not extensible via confirm. Fix: **per-note** config + unmapped→flagged→AI-propose-confirm-store. *(slice-6 finding #1)* |
| B2 | `gl/field_resolver.py` `_HEADER_MAP` + `face_tb/ingest.py` `_TB_HEADER_MAP` (header→field) | **ACCEPTABLE — known follow-up.** The *right* pattern (keys off header MEANING, not position) with `unmapped_headers` collected; the AI-propose-mapping fallback is the **stubbed slice-4 interface**, not yet wired. Brittle for a non-SAP client *until* that's wired → it's the slice-4 GL-path follow-up, already on the list. |
| B3 | `fs_notes/classification.py` `SEED_TAXONOMY` (Prepayments keywords) | **ACCEPTABLE — this is the MODEL.** Explicitly a swappable `PrepaymentTaxonomy` value object + label-signal + "Other" plug + AI-propose-confirm loop for "Other". No fix — it's what A1/A2/A4 should look like. |

## C. Sector/entity vocabulary baked into the model
| # | Site | Verdict |
|---|------|---------|
| C1 | `hierarchy/mapping.py:25` `MappingEntry.measurement_type` ("FVIS/FVOCI/AC … '' otherwise") | **MINOR** — structurally reusable, named for the financial sector; the docstring already frames it as "an extra hint." Fix: **rename → `sub_class`** (mechanical) carrying "FVOCI" or "Buildings" alike. The brittleness is in how the *value* is set (that's A2), not the field. *(slice-6 finding #3)* |
| C2 | `fs_notes/investments.py` `_MT_LABEL`, `_MT_ORDER` (FVIS/FVOCI/AC labels+order) | **ACCEPTABLE** — a note module is allowed to know its own disclosure structure; this is note-local content, not engine-level. PP&E carries its own (Land/Buildings/…). Not cross-cutting. |

## D. Magic numbers / conventions
| # | Site | Verdict |
|---|------|---------|
| D1 | `gl/ingest.py:66-75` `_entity_from_sheet` / `_account_from_sheet` (regex on "10400001 GL - 1010") | **MINOR** — a SAP sheet-naming convention, but the gl_account **column is the primary source**; sheet-name is the continuation-row fallback. Breaks the fallback on odd naming, not the main path. Revisit with the GL-path region work. |
| D2 | `gl/regions.py` region=sheet v1 / header-row assumption | **KNOWN follow-up (slice 4).** Note: `face_tb/ingest.py` already does header = max-score row (NOT a hardcoded row 6 — good); only the GL path still uses region=sheet. |
| D3 | `config.py` `OPENAI_MODEL` pin; `prepayments.py` `_MATERIALITY_SAR=10_000_000` | **ACCEPTABLE** — model pin is deliberate/correct (R19); materiality is a default/threshold that only gates whether a *question* is raised, never a number. Make materiality per-entity config later if needed; safe as-is. |

## E. Explicitly on the right side of the hard line (NOT brittleness — do not "fix")
- **The number engine:** roll-forward/netting/reconciliation/total arithmetic (`LineRecon`,
  `MovementSchedule`, gap math). Deterministic is **correct**. Out of scope by design.
- **Flag-don't-absorb guards:** R14 subtotal/continuation/orphan disposition, `_looks_like_account`
  quarantine, the TB `range/level/type` reads (reading the TB's **declared** columns is signal-based,
  not a code convention). These flag or read declared structure; they never silently commit an
  identity from a guessed pattern.
- **Legacy Note-5 cascade** (`compute/`, `routing/`, `ingestion/`, `notes/`, `policy/`, `ui.py`):
  deprecated; has its own hardcodes but is not the active engine. Out of scope unless revived.

---

## Recommended fix order (deliberate, not all-at-once)
1. **Slice 6 fixes INLINE the findings it already touches** — A1/A3 (contra ID by signal → confirm →
   store), B1 (per-note reference config + propose-confirm for unknown codes), C1 (rename
   `measurement_type`→`sub_class`) and A2's *value-by-signal* for PP&E's asset class. Unavoidable for
   PP&E anyway; building them P-C-S is the point of the slice.
2. **Own remediation slice (proposed "Slice 7 — de-hardcode the seed mapping"):** generalise
   `build_seed_mapping` so account→{note, class, contra-role} is the **confirmed-store + AI-propose**
   path for ALL notes, and **retrofit Investments + Prepayments off A2/A4** (prefix map + literal
   account set) — with code prefix as an optional hint. Retrofitting the two proven notes is how we
   know the fix *removed* the brittleness instead of relocating it. Doing it as its own slice keeps
   PP&E from ballooning.
3. **Folded into existing follow-ups:** B2 + D1/D2 → the slice-4 GL-path region/field-resolution
   follow-up (re-wire GL ingest onto confirmed regions + AI field mapping). No new slice.
4. **No action (verified acceptable):** B3 (Prepayments taxonomy — already the model), C2, D3, E.

## Coverage check — legacy is not reached through a live path (2026-06-10)
Grep for active-spine imports of the deprecated cascade (`routing/`, `notes/`, `compute/`,
`ingestion/`, `policy/`, `validation/`, `ui`): **clean.** Every legacy import is legacy→legacy (the
cascade modules import each other); **no** active-spine package (`gl/`, `trial_balance/`, `face_tb/`,
`fs_notes/`, `parsing/`, `hierarchy/`, `clarify/`, `reporting/`, `recompute.py`) imports any of them
(the lone `fs_notes/__init__.py` hit is a comment asserting it never does). A legacy hardcode reached
through a live path would still be live — there are none. **The A1–A4 + B1 cluster claim holds.**

## Locked decision (2026-06-10)
- **Slice 6 = PP&E clean** — P-C-S from the start, zero new hardcodes; fixes inline only A1/A3, B1, C1,
  and A2's value-by-signal **for PP&E only**. **It does NOT touch the existing A2 prefix map**
  (Investments/Prepayments entries stay exactly as-is; PP&E just doesn't add itself).
- **Slice 7 = de-hardcode the seed** — retrofit Investments + Prepayments off A2/A4 with a
  **byte-identical no-regression proof** on the existing fixtures (that proof is the slice's point;
  isolation keeps new-note and refactor-proven-notes from mixing in one suite).
- **B2 + D1/D2** → slice-4 GL-path follow-up. **No action:** B3, C2, D3, the number engine.

## The line that governs all of it
This audits **structural identification** hardcodes — what something *is* / where it *belongs* — and
fixes them with **propose → confirm → store** (pattern as optional hint). It does **not** touch the
**number engine**; arithmetic being deterministic is correct and stays. The goal was an inventory with
a verdict per item, not a rip-everything-out pass — most of the codebase is already on the right side;
the brittle cluster is A1–A4 + B1, and it's bounded.
