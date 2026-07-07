# Slice 4 — the parsing front-end (find and read the table correctly)

> The thing standing between the proven engine and a user uploading an arbitrary Excel. Own slice,
> next, blocked on nothing (Bucket B matcher + independent sign-off wait on external answers).
> ~~No code until this plan is reviewed~~ — **✅ BUILT (2026-06-10)** to this plan after review, with
> the two review additions folded in: the **conservatism second line of defense (R24)** and the
> **headless-confirm-without-auto-accept** resolution. Package: `ai_accountant/parsing/`. All 26 test
> suites green (incl. the `test_wrong_boundary_is_NOT_auto_confirmed` gate-with-teeth assertion).

## Result against the messy fixture (what to look at)
- `tests/test_parsing_frontend.py` — 8 guards on a hand-built grid with a KNOWN answer (header 5,
  data 6–12): **exact-known-region** (not "plausible"), **include-too-much** (footers 14–15 excluded),
  **include-too-little** (tail past the internal blank kept, data_end=12), **conservatism** (interior
  subtotal → conf 0.70, needs_review, no auto-confirm without override), **wrong-boundary-not-auto-
  confirmed**, file-kind TB/GL/UNKNOWN + rename-proof, and the unconfirmed-extract gate.
- `python scripts/parse_frontend_demo.py` — prints the boundary the confirm step shows a human.
- `python scripts/build_messy_fixture.py` — materialises `TB/Messy_Fixture_XYZ.xlsx` to open the mess.
- **Recorded follow-ups (not silently assumed):** per-region file-kind (v1 is per-file); an AI
  multi-region proposer behind `propose_regions`; re-wiring GL `ingest_workbook` onto confirmed
  regions (still `region = sheet` internally). Next, per your gate: **slice 5**.

## The defining property (drives every decision)
**A mis-detected boundary silently corrupts numbers — it does not error.** Grab a footer subtotal as
data and you get the 1.6B double-count; miss the last rows because a blank line looked like the end
and you silently drop real money. Both produce a *confident wrong answer* that **ties cleanly
downstream** — the reconciliation just reconciles to the wrong number. So every decision below follows
one rule: **the parser must never silently extend, truncate, absorb, or guess a boundary** — it
proposes conservatively, flags uncertainty, and surfaces the boundary for a human to see and move.

## The verification problem — confronted head-on (the hard part)
Everywhere else in this build there was an **independent number** to check against — a control total,
the AI-mapping key, an exact reconciliation gap. **Here there is none:** the parser's output *is* the
input to everything downstream, so no downstream tie can catch a parsing error. Therefore:

> The guard cannot be "does it parse." It must be **"does it extract the EXACT region a human would
> identify as the table"** — header row, first data row, last data row, columns — byte-for-byte.

The only way to have a known-correct answer is to **hand-build a messy fixture** where we *know* which
rows are table vs title/subheader/instruction/footer/blank, and assert the parser extracts the **exact
known region**, never "a plausible region." This is the analog of the hand-computed balancing TB and
the AI-mapping key: the fixture has a known-correct answer because we built it with one.

### …but exact-match on the fixture CANNOT be the only verification (the second line of defense)
The fixture's mess is **mess we designed.** This slice exists for files we *didn't* design — and a
parser can pass exact-match on the hand-built fixture and still mis-detect the first real finance Excel
with an unanticipated mess (a second table to the right, a merged-cell header spanning two rows, a
subtotal *inside* the data, a "carried forward" line that looks like data). The fixture proves the mess
we thought of; **it cannot prove the mess we didn't** — the same synthetic-vs-real trap as everywhere
in this build, and worst here because no downstream reconciliation catches it.

So there is a **second, named guard that protects the un-designed mess** — and it's not exact-match
(you cannot write an assertion against a file you haven't seen). It's:

> **CONSERVATISM IS THE REQUIRED FAILURE MODE.** On low-confidence / unfamiliar / ambiguous detection,
> the parser degrades to *"not sure — here's my best guess, confirm or correct me,"* **never** to a
> confident wrong region. And: **a low-confidence region cannot be auto-confirmed** — it requires an
> explicit override, *even on the headless/CLI path.*

The exact-match fixture proves correctness on **known** mess; the confidence threshold + the
non-auto-confirm rule is what protects against **unknown** mess. The confirm gate is therefore not
merely "always on" — it is *specifically the safety net for the cases the fixture can't cover.*

### Headless confirmation without becoming auto-accept (the path slice 4 actually runs)
Slice 4 is engine+CLI+tests; confirm is "programmatic/CLI." The hazard: if the CLI path auto-confirms
whatever the AI proposes (no human in a test run), the gate has teeth *in principle* but not *in the
tested path* — every run rubber-stamps. Resolution, built into the model:
- A region carries a **confidence**; below a threshold it is **`needs_review`** and **cannot be
  extracted** without an explicit override token — there is **no silent auto-accept** anywhere.
- **Test fixtures confirm against their KNOWN answer:** a *correct* proposed boundary → confirmed and
  extracted; a *wrong* proposed boundary → the test asserts it was **NOT auto-confirmed** and a flag
  was raised. That keeps the gate real in the only path slice 4 exercises (the
  **wrong-boundary-not-auto-confirmed** assertion is a required test, shown before slice 5).

## Two failure directions → two separate guards (they fail oppositely)
| Direction | Shape | Guard |
|---|---|---|
| **Include too much** | a footer subtotal / instruction row swept into data | the **1.6B double-count** — assert those rows are EXCLUDED |
| **Include too little** | an internal blank row read as the end → drop the tail | **silent money loss** — assert data AFTER an internal blank is still included |
Both tie cleanly downstream; "extracts a plausible region" passes both wrong; **"extracts the exact
known region" catches both.** The fixture carries a case for each, explicitly.

---

## Components

### 1. File-kind detection (step one; its own failure mode)
Misclassifying GL-vs-TB-vs-sub-ledger runs the **entire wrong pipeline** — a confidently-misclassified
file is the worst possible start. So:
- **Content signals, never the filename** (users rename): a **TB** shows L0–L4 level + Account-Type
  P/C + range cells (`11000000 - 11999999`) + mapping columns; a **GL** shows SAP transaction columns
  (Company Code, G/L Account, Company Code Currency Value, Document Number, Posting Date, Reference,
  Assignment) over many rows.
- **An `UNSURE` verdict that ASKS** (flag-don't-force): weak/conflicting signals → `UNKNOWN` → put the
  question to the user ("what kind of file is this?"), never guess.
- Model: `FileKindVerdict{kind: GL|TB|SUBLEDGER|UNKNOWN, confidence, signals: [...], unsure: bool}`.
- Guard: TB→TB, GL→GL, ambiguous→UNKNOWN-asks; renaming a GL to `tb.xlsx` still classifies GL.
- **File-kind is ultimately PER-REGION, not per-file** (the multi-table-in-one-sheet case from the
  original redesign: a sheet can carry a TB block *and* a GL block, or two side-by-side tables).
  Running file-kind once per file gives **one answer for a file with two kinds**. The common case is
  one-kind-per-file, so **v1 simplifies to per-file** — but this is **recorded as a simplification to
  revisit** (per-region kind detection), exactly like the `region = sheet` v1 this slice replaces.
  Not silently assumed: the `FileKindVerdict` is attached at the level v1 computes it, with a TODO
  marker that per-region is the real contract.

### 2. Structure-agnostic table-region detection (replaces `region = sheet` v1)
A region = `{sheet, header_row, data_start, data_end, columns: {field→col}, excluded: [(row, reason)]}`.
- **Header row** = the row where enough cells resolve to field meanings AND the rows below are
  data-shaped (consistent column types). (Reuse the resolver's header-score, already proven on the
  derived TB's title block.)
- **Data end** = where data-shape breaks: a footer (blank-except-amount → R14 `subtotal_row`), a
  "Total" row, or a blank with nothing after. **An internal blank does NOT end the region** — the
  detector looks past a single blank to see whether data resumes (the include-too-little guard).
- **TB-specific tie-breaker (a trap in the real TB structure):** "header = enough cells resolve + rows
  below data-shaped" trips on the TB scaffold — the L0–L3 **parent (P)** rows are loosely "data-shaped"
  too (they have a Level, a description, a range) and they sit *between* the header and the leaf data,
  and the real numbers live at the **L4 leaf (C)** rows which are **interspersed, not in a block at the
  bottom.** A naive "where do the numbers start" mis-places `data_start` onto a scaffold row or reads
  the scaffold as the header. Rule: **TB region detection treats P and C rows as ONE contiguous data
  block keyed off the Level / Account-Type columns** — it does not hunt for "where the numbers start,"
  because in a TB they don't start in a block, they're interleaved with the scaffold.
- **Excluded rows carry a reason** (title / subheader / instruction / footer / blank) so the human
  sees *why* each was dropped — and so a wrongly-excluded row is visible, not silent.
- Reuse the row-level R14 disposition (continuation / subtotal / orphan) for footer/orphan handling —
  it already distinguishes a footer (no transactional id) from real data.

### 3. The AI-propose / human-confirm-boundary contract (R22 applied to parsing)
The confirm step is **load-bearing, not cosmetic** — it's where a finance user catches what the AI got
wrong, and a boundary error that sails through silently corrupts numbers.
- **AI proposes** file-kind, region boundaries, header row, column→field mapping. **Deterministic
  validation** checks the proposal (required fields present, data rows consistent). **The human
  confirms or adjusts.**
- The confirm must show the boundary **as a boundary the human can see and MOVE** — e.g. *"rows 7–432 =
  table, row 6 = headers, A=Level, D=Natural Account, E=Amount, K=Mapping; excluded rows 0–5
  (title/subheader/instruction), 433–436 (footer subtotals)."* `data_start` / `data_end` / `header_row`
  / column map are all **editable**, not a rubber-stamp checkbox.
- **Nothing downstream runs until `confirmed=True`** — a region is not extracted, no FaceTB/RollForward
  is built, until the boundary is confirmed. (Headless slice 4 confirms programmatically/CLI; the
  in-app panel is the later UI wiring — but the model carries the gate so the UI renders it.)

### 4. Field resolution on unfamiliar layouts
The AI-proposes-a-mapping path (currently stubbed): given the header row + sample rows of a
non-SAP/non-template file, AI proposes column→canonical-field mappings (which column is the amount,
the account…), human confirms, stored. Same propose/confirm/store pattern.

### 5. Three-case routing (detect-and-maximize wiring)
Once file-kind + region detection produce clean parsed inputs, route **TB-only → face statements**,
**TB+GL → face + reconciled breakdown**, **GL-only → Track 1 magnitude-unverified** — detect which is
present, produce the maximum, label the rest. This is the wiring that finally connects the parser to
the proven engine across all three cases.

---

## The messy fixture (the load-bearing test)
Hand-built Excel with a KNOWN-correct region (so the assertion is exactness, not plausibility):
```
row 0   XYZ Financial Co.                              ← title
row 1   (in SAR '000, unless stated)                   ← subheader
row 2   (blank)
row 3   Finance team to update column F and G only     ← instruction
row 4   (blank)                                        ← separator
row 5   Level | Acct Type | Natural Account | … | Final | Mapping   ← HEADER (known)
row 6   …first data row…                               ← DATA start (known)
…       …the balancing synthetic TB rows…
row M   (blank)                                        ← INTERNAL blank — must NOT end the table
row M+1 …more data…                                    ← still DATA (include-too-little case)
row N   …last data row…                                ← DATA end (known)
row N+1 (blank)
row N+2 … footer subtotal (blank-except-amount) …      ← FOOTER — must be EXCLUDED (include-too-much)
row N+3 … another footer subtotal …
plus one shifted/orphan row inside the data            ← surfaced, not absorbed
```
The fixture *records* its own known answer: `header_row=5, data_start=6, data_end=N`, excluded =
{0–4 title/subheader/instruction/blank, M is internal-blank-KEPT, N+1..N+3 footer}.

## Guards (R21) — the assertions
- **exact-known-region:** detected `(header_row, data_start, data_end, columns)` == the fixture's known
  answer — not "a plausible table." *(Proves correctness on KNOWN mess.)*
- **include-too-much:** the footer subtotal rows are NOT in the extracted data (1.6B shape blocked).
- **include-too-little:** data after the internal blank IS included (no silent tail-drop).
- **conservatism / R24 — confident-wrong is forbidden:** on low-confidence/unfamiliar/ambiguous
  detection the region is `needs_review` and **cannot be auto-confirmed** — extraction requires an
  explicit override even headless. *(This is what protects the UN-designed mess the fixture can't.)*
- **wrong-boundary-not-auto-confirmed (the headless-gate-with-teeth test):** feed a proposal whose
  boundary is WRONG → assert it was NOT auto-confirmed AND a flag was raised (the CLI/test path never
  rubber-stamps). *Required result shown before slice 5.*
- **file-kind:** TB→TB, GL→GL, ambiguous→UNKNOWN-asks; rename-proof (content, not filename).
- **confirm gate:** an UNconfirmed region yields NO downstream extraction (R22 — the gate has teeth).
- **orphan/shifted in-table:** flagged, not absorbed (carries R14 forward).

---

## Explicitly OUT of Slice 4 — the matcher (Bucket B)
AI **region/header detection** (Slice 4: *find and read the table correctly*) and AI **account
matching** (Bucket B: *reconcile codes that don't line up*) are **different risk surfaces**. They both
use AI and propose/confirm/store, so they will tempt merging — **keep them separate.** Slice 4 hands a
correctly-parsed file to the engine; the matcher reconciles codes *within* an already-parsed file.
Slice 4 does not absorb the matcher.

## Sequencing within Slice 4
1. File-kind detection (content signals + UNSURE-asks).
2. Region-detection model + the two-direction logic (reuse R14 row disposition).
3. AI-propose-region + deterministic validation + the confirm contract (visible, editable boundaries; gate).
4. Field resolution on unfamiliar layouts (AI-propose-mapping).
5. The messy fixture + the exact-known-region guards (the load-bearing tests).
6. Three-case routing (wire parser → engine).

Engine + CLI + tests, no UI (the confirm *panel* is the later UI wiring; the confirm *contract* —
visible/editable boundaries + the gate — is built into the model now so the panel renders it).
Every silent-failure surface keeps its assertion; here the surface is the mis-detected boundary, and
the discipline is **flag-don't-auto-slice + the exact-known-region fixture.**
