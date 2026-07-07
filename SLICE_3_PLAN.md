# Slice 3 — GL routing + the TB↔GL reconciliation keystone

> Recast, not new: the GL→notes engine (RollForwardTB + note modules) becomes the **breakdown layer**
> that hangs off a TB line and reconciles up to it. Slice 3 adds routing + the reconciliation
> keystone in front of it. The note-contract inversion (`tie_ok` flips from "breakdown internally
> consistent" to "breakdown reconciles to the TB line") lands here.

Three buckets, with build status. **Precondition-gated parts are NOT built — they await your review
and the two items being chased.**

---

## Bucket A — buildable now, no precondition  ✅ BUILT THIS TURN (synthetic-tested)

### A1. The locked first task — old-hierarchy rename  ✅ DONE
The GL-fallback hierarchy (`ai_accountant/hierarchy/`) levels `L1–L4` → **`G1–G4`** (seed.py, nodes.py,
the one consuming test, the CLI). The new TB classification keeps `L0–L4` (`face_tb`); the legacy
Note-5 cascade is untouched (separate, deprecated). The `L1–L4 / L0–L4` overlap is gone — no
half-renamed mix went live. `test_hierarchy` green.

**PRECEDENCE (not just naming):** the G-levels exist ONLY on the GL-only input path. **The moment a
TB is present, the ingested L-levels are authoritative and the G-levels are NOT consulted** — so the
note recast routes through the TB classification, never the GL-fallback, whenever both are in scope.
This closes the last naming hazard: the distinction is now a rule about *which hierarchy wins*, not
just two label sets that happen not to collide.

### A2. Routing structure + all four findings  ✅ DONE (`face_tb/routing.py`)
`route_gl_to_tb(facetb, gl_amounts)` routes each GL account to its TB line by **code** (deterministic
core). The four ways routing goes wrong are each a FINDING, never suppressed:
1. **orphan** — GL account matching no TB leaf/range → flagged, not absorbed.
2. **reconciliation gap** — routed GL Σ ≠ TB line → **BLOCKED**, diff = `GL Σ − TB raw` (exact).
3. **partial coverage** — GL covers some of a line's leaves → **PARTIAL**, reconciles to the
   **covered subtotal** (not the whole line).
4. **granularity mismatch** — GL account in a TB range but no specific leaf → flagged.

### A3. TB↔GL reconciliation machinery + synthetic set  ✅ DONE (`tests/test_tb_routing.py`)
Synthetic TB+GL: one reconciles→BUILT, one exact-gap→BLOCKED (diff exact), one orphan, one partial.
`LineRecon.status()` = BLOCKED (gap) / PARTIAL (coverage) / BUILT.

### A4. Recon-to-raw guard  ✅ DONE
Reconciliation target is the **raw** TB amount, never `Final`. `raw + adjustment = Final` is a
visible itemized **bridge** (`adjustment_bridge`), never a tolerance — a "gap" and an "adjustment"
can't masquerade. Guard: a Prepaid line (raw 1000, adj 100, Final 1100) with GL Σ 1000 **reconciles
to raw** (BUILT) even though GL ≠ Final; reconciling to Final would have manufactured a false 100 gap.

---

## Bucket B — the matcher (DESIGN locked, BUILD held)  ⛔ NOT BUILT

**§9.1 CoA answer is in: "both" — per-account, not per-file.** In the same file, some GL codes match
the TB codes and some don't. So routing is a **graded path, not a mode switch**, and the unmatched
account is **not an error** — it may be a renumbered account needing an assisted match. This is the
**orphan finding (A2.1) extended, not a parallel path**: an orphan becomes "candidate for assisted
match" rather than terminal.

**Matcher design — crosswalk-first, in priority order** (when codes don't match, the dominant real
case is renumbering: same accounts, different numbers — a *stable correspondence*, not chaos):
1. **Deterministic code-match** — built (A2). Covers the matching majority of a same-system export.
2. **Crosswalk table** — a confirmed-once, stored `GL code X → TB code Y` mapping, reused on every
   future run with that system pair. **AI proposes the crosswalk entries, human confirms, then it is
   deterministic again** (propose/confirm/store, same pattern as the AI label loop). The common,
   auditable case — capture the renumbering rule once, not per-row every run.
3. **Per-row AI match** — "GL account ≈ which TB line?", human confirms, store. **Last resort only**,
   for genuinely unknown accounts with no stable rule.

Each tier is more guarded than the last; the crosswalk is far more auditable than per-row guessing,
so design pushes work *up* the priority list (deterministic > crosswalk > per-row).

**BUILD HELD** pending one more team answer: when codes differ, is it **renumbering** (a fixed
correspondence captured once → B is mostly the crosswalk, easy/reliable) or a **genuinely different
account set** (→ B leans on per-row matching, harder, more guards)? That answer sets how much of B is
tier-2 vs tier-3. Do not build B until it lands.

---

## Bucket C — keystone on real data  ✅ MACHINERY SIGN-OFF DONE · independent sign-off still OPEN

**This is the next thing built, before B.** The deterministic core (A2) already covers the *matching*
half of routing — and on a same-system export that's most or all accounts. So the keystone can be
signed off against real data using the clean-match accounts **the moment the populated real TB +
matching GL lands**, without waiting on the matcher. The crosswalk/per-row fallback (B) catches the
non-matching minority and is an **enhancement, not a precondition** for proving the keystone works on
the matching majority.

**Signing the keystone "verified."** A3 is unit-tested on synthetic — necessary, not sufficient.
Synthetic data can't surprise us; real data is where the unanticipated orphan / partial / CoA mismatch
lives. "green on synthetic ≠ proven." The keystone is BUILT and tested; it is VERIFIED only after it
survives real numbers. **Run order when the data lands:** ingest real TB → ingest matching real GL →
`route_gl_to_tb` on the clean-match accounts → inspect reconciliation/findings → sign-off.

---

## Status after the Bucket C re-run
- **Bucket C — MACHINERY SIGN-OFF ✅ DONE.** Investments + Prepayments both reconcile **BUILT exact**
  on real GL totals (gap 0.0000 at tight tol; the old 3.27M would still BLOCK); orphans −59.1M intact.
- **NOT** independent sign-off (TB derived from GLs → ties by construction) — that stays OPEN.
- **Bucket B (matcher)** — paused on the renumbering-vs-different answer.

---

## ⚠ THE PARSING FRONT-END IS UNBUILT — the gap this green sweep hides

Everything proven so far, **including the reconciliation that just passed**, was fed data of KNOWN
structure: the GL rollups ran in scripts that knew the header row and the SAR column; TB ingestion
ran with `region = sheet` (v1) against files whose table location was given; the field resolver only
recognises the known SAP/TB headers. **The app a user actually drives has none of that** — someone
uploads an arbitrary Excel and the app itself must find where the table starts, which row is the
header, what the columns mean, where data ends, and **ignore title / subheader / instruction / blank
/ footer rows.**

**Honest status:** the engine downstream of parsing is well-proven; **the parsing front-end is
effectively still stubbed** (`region = sheet` v1, known-header resolver, no file-kind detection). That
was the right order (prove the spine first) — but it cannot stay "done in a script," and it is NOT
folded into "ingestion, done."

**The trap:** the two derived TBs are neat (one table, tidy header) — a parser tested only on them
would LOOK solved. The real test is the mess the redesign doc (§4b) already enumerated and we already
hit: a title row, the `(in SAR '000)` subheader, the "Finance team to update column F/G" instruction
row, blank separators, and the **footer subtotals that caused the 1.6B double-count** + the orphan
rows. A parser that survives those is the app; a parser that assumes "row 6 is the header" is the
script. A mis-detected boundary **silently corrupts numbers** — so it's flag-don't-auto-slice.

## The three input cases — detect-and-maximize contract (re-pinned)
The app must DETECT which input it's given and produce the maximum that input supports, labelling the
rest — NOT a mode switch:
- **TB-only** → face statements (BUILT face, PARTIAL breakdown). [engine proven, slices 1–2]
- **TB+GL** → face + reconciled breakdown. [proven this milestone]
- **GL-only** → Track 1 note(s), magnitude-unverified.

What just passed is the **TB+GL reconciliation** — that does NOT mean "the app handles all three."
Each case has a **different front-door parse** (a TB has the L0–L4/range/mapping structure to detect;
a GL has the SAP column layout to resolve), and the app must first **detect which kind of file it is
even looking at** before choosing the parser. That file-kind detection is part of the unbuilt parser.

## Slice 4 — the parsing front-end (ITS OWN SLICE; the next real build target)
It stands between the proven engine and a user's upload, with its own high-stakes failure mode (a
mis-detected boundary silently corrupts numbers), so it gets its own slice and its own guards:
1. **File-kind detection** — GL vs TB vs sub-ledger/transactional (the first front-door step).
2. **Structure-agnostic table-region detection** — find each table's bounding box + header row;
   exclude title/subheader/instruction/blank/footer rows. **AI proposes regions → human confirms
   boundaries → deterministic extract** (replaces `region = sheet` v1; never silently auto-slice).
3. **Field resolution on unfamiliar layouts** — the AI-proposes-a-mapping path (currently stubbed).
4. **Guard (R21) — a deliberately MESSY synthetic fixture** (title row, `(in SAR '000)` subheader,
   instruction row, blank separators, footer subtotals, shifted/orphan rows): assert the parser finds
   the right region + header, EXCLUDES the noise, and a mis-detected boundary is flagged not silently
   extracted. The neat derived TBs are necessary but NOT sufficient — they'd lull it.
5. **Three-case routing** — once file-kind detection exists, route TB-only / TB+GL / GL-only.

Buildable **now** (no precondition — the mess to test against is enumerated and partly in the real GLs).

## Sequencing (updated)
1. A1–A4 ✅ → Bucket C machinery sign-off ✅ (this milestone).
2. **NEXT: Slice 4 — the parsing front-end** (own slice, no precondition).
3. Parked on preconditions: **Bucket B matcher** (renumbering-vs-different answer); **independent
   keystone sign-off** (finance's own TB).
4. Then: note-contract inversion (4a/4b → breakdown modules) → TB-path UI wiring → first non-bank note.

Every silent-failure surface keeps its assertion (R21). For Slice 4 the new surface is the
mis-detected table boundary — a parser that confidently extracts the wrong rows is the silent-
corruption failure, so it's flag-don't-auto-slice + the messy fixture. The graded matcher path (B)
still means an unmatched account is a candidate-for-matching finding, never silently absorbed.
