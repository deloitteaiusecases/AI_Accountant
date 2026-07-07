# Slice 10 — wire the proposer loop into the app (the AI acts inside the app, honestly)

> The one real build left. Different risk profile: **the first time the AI acts inside the app**, on a
> live call path with a human in the loop. The discipline that held in the engine and the prompts now
> has to hold across that call path. Reuse the **pinned `gpt-5.1-2025-11-13` client** and the
> **labels-only proposers as-is — do not change the prompts.** Engine + app + tests, **no UI polish
> beyond what the guards require.** **No code until this plan is reviewed** — same gate as every slice.

## The defining property (drives every decision)
**You can always see WHO decided each classification, and an AI guess can never launder into apparent
fact.** Three things follow and are each a *tested* guard, not an architectural note: (1) an AI-assumed
item is a distinct state end-to-end and can never reach BUILT or render as human-confirmed; (2) the
human's confirm step is real (per-mapping, reviewable, low-confidence flagged) — never a sight-unseen
"accept 23"; (3) every mapping on the final FS carries a **provenance label** (preparer / AI-confirmed
/ AI-assumed), on **both** paths.

## What gets wired (and the path it flows through)
The **four existing proposers** in `fs_notes/ai_propose.py`, called via the pinned `LLMClient`:
- `propose_seed_mapping` — account → note/face line + contra/classification (the no-mappings TB).
- `propose_face_mappings`, `propose_ppe_structure`, `propose_subcategories` — the other classification
  surfaces (PP&E structure, prepayment sub-types) for the same confirm path.

Their outputs become **Resolutions** the existing recompile loop already understands —
`apply_resolutions` maps `unmapped_leaf` → `leaf.mapping` and `unknown_section` →
`section_overrides`, then `recompute_face` reassembles. **No parallel apply path**; the AI proposes,
the human confirms, and the SAME deterministic recompute produces the statements.

---

## 1. The AI-assumed state — asserted END-TO-END (the honesty invariant)
- **Data:** a confirmed mapping/answer carries a **provenance** — `preparer` | `ai_confirmed` |
  `ai_assumed` — as a distinct field on the `Resolution` (e.g. `provenance` + `ai_confidence`), never a
  shared "answered" boolean.
- **Engine:** an `ai_assumed` resolution **applies** (so the line populates and the figure recomputes)
  but adds a provisional reason *"rests on an unconfirmed AI assumption"* that **blocks BUILT**, and
  the line is tagged AI-assumed.
- **Presentation:** a new line status **`LINE_AI_ASSUMED`** (amber + "AI assumption" tag) — distinct
  from `LINE_BUILT` (green) and `LINE_BLOCKED` (red). Carries into the StatementView AND the export.
- **The tested guard (the whole point):** an AI-answered item **recomputes and exports as AI-assumed,
  and CANNOT reach BUILT or render as human-confirmed**, all the way through. Test with a fake client:
  propose → accept-as-assumption → recompute → assert `LINE_AI_ASSUMED`, status ≠ BUILT, export shows
  it amber/labelled; and assert `ai_assumed` and `human-confirmed` never collapse into one state. If
  this invariant slips, AI guesses launder into fact — so it is a hard assertion, not a note.

## 2. The confirm step is REAL, not a rubber-stamp
When the AI proposes (e.g.) 23 mappings on a no-mappings TB:
- The human sees **each** proposal: account, label, proposed line, **confidence**, evidence — and can
  **change** it (pick a different line) or leave it open.
- **Low-confidence / 'unsure' proposals are flagged for attention** (sorted up / highlighted) — the
  AI's own `is_confident=False` drives this; an unsure proposal is never pre-accepted.
- **There is NO "confirm all 23 sight-unseen" button** (that is auto-confirm wearing a confirm button).
  A bulk action exists, but it can only push **unreviewed items into `ai_assumed`** (flagged, never
  BUILT) — never into `confirmed`. **Confirmed = a human reviewed it; assumed = a human chose to let it
  ride unverified.** The app has no scoring key (unlike the 20/20 run) — the human IS the check, so the
  UI makes that check real. Same lesson as the parsing confirm-gate.

## 3. The mapping run is OBSERVABLE
Surface what the AI proposed and at what confidence **before** it flows into statements — the "mappings
applied" view (point 6) is partly this. Both a feature (auditable mappings) and a guard (catch a
mismapping before it reaches the FS). Not "it worked, here are statements."

## 4. The LLM failure path — flag-don't-force applied to infrastructure
Today the app makes zero LLM calls, so there is no failure mode; once it makes live ones there is.
`propose_*` → `client.complete_json` raises `LLMError` after retries (timeout / API error / malformed
JSON). The wired flow **catches `LLMError`** and: the mapping **stays unproposed**, the item **stays
open**, the line stays unmapped (face-only / keystone-can't-run), and **nothing silently defaults to a
guess.** The UI says *"AI mapping unavailable (model error) — item remains open; map it manually or
retry."* Tested with a fake client that raises. *"The demo broke when the model timed out"* must not
happen — a model failure degrades to the honest unmapped state, not a crash and not a guess.

## 5. Scope line — the FOUR proposers, NOT the matcher
This slice wires the **mapping / label / structure proposers** (`fs_notes/ai_propose.py`) into the GUI,
unblocking the **no-mappings path**, the **mappings-applied view**, and the **AI-answer checkbox**.
**Bucket B — the crosswalk matcher — stays OUT** (parked on the renumbering-vs-different answer). It
will tempt merging because it is also propose-confirm-store shaped, but it is a *different* problem
(reconcile GL codes that don't line up) on a *different* surface. Keep it out: nothing in this slice
touches the GL↔TB code matcher.

## 6. The "mappings applied" view — BOTH paths, provenance-labelled (the honest core)
A reader of the final FS should not take the account→line classification on trust, **regardless of who
mapped it.** So the FS exposes a **"mappings applied"** view — each account → its face line/note — with
a **provenance label per mapping**, on **both** paths:
- **with-mappings path:** `preparer-provided` — the accountant's own mappings (today they drive the
  statements but aren't shown *as* an auditable view; **add that**).
- **no-mappings path:** `AI-proposed (confidence X) · confirmed by human`, or `AI-assumed
  (unconfirmed)` — the AI-applied distinguishable from human-confirmed, low-confidence flagged.

Same view, different provenance label, in the app AND the export — so whether the accountant or the AI
mapped `11010010 → Investments, net`, the reader sees the mapping **and who decided it.** Auditability
of the classification must **not** depend on which path produced the FS.

**It is a standalone, ALWAYS-PRESENT artifact** — a "Mappings applied" sheet in the Excel and a page in
the PDF, emitted on **every** run, not only when the AI was involved. The with-mappings path is the
explicit add: today the export shows the *statements* (the result of the preparer's mappings) but not
the **mappings themselves as an auditable view** — this surfaces them, every account → its line/note
labelled `preparer-provided`, so the classification is verifiable without trusting the numbers. The
three provenance values are fixed and exhaustive: **`preparer-provided` · `AI-proposed · confirmed by
human` · `AI-assumed (unconfirmed)`** — and an `AI-assumed` row in this view is the same amber state as
its line (point 1), never shown as settled.

---

## Guards (tested)
1. **AI-assumed end-to-end:** accept-as-assumption → `LINE_AI_ASSUMED`, status ≠ BUILT, export amber +
   labelled; `ai_assumed` ≠ `human-confirmed`, never merged; an AI-assumed line never renders BUILT.
2. **Confirmed ≠ assumed:** AI proposes → human *confirms* (reviewed) one and *assumes* another →
   the confirmed line is human-confirmed (BUILT-eligible if it reconciles), the assumed one is amber;
   no bulk path moves an unreviewed item into `confirmed`.
3. **Observable run:** the proposed mappings + confidences are present in the view before statements
   (assert the mappings-applied view lists each account → proposed line + confidence).
4. **LLM failure:** a fake client that raises `LLMError` → item stays open, line stays unmapped,
   no crash, no silent default (assert the unmapped state persists and a clear message is shown).
5. **Provenance on both paths:** the with-mappings FS shows every mapping as `preparer-provided`; the
   no-mappings FS shows `AI-…` provenance — both in the export.
6. **Prompts unchanged / labels-only / pinned model:** the wired calls use the existing proposers and
   the pinned snapshot verbatim (a guard that no amount enters a payload and the model string is
   `gpt-5.1-2025-11-13`).

All proposer calls in tests use a **fake client** (no network) — the same pattern as the existing
proposer tests; the live path is exercised structurally, the model accuracy is not unit-tested.

## Engine vs presentation (so the split is explicit)
- **Engine:** the `provenance` / `ai_assumed` field on `Resolution`; the recompute rule that applies an
  assumption but blocks BUILT and tags the line; the `LLMError` catch → stays-open behavior; a thin
  service that calls the proposers and turns confirmed/assumed proposals into Resolutions.
- **Presentation:** `LINE_AI_ASSUMED` + amber rendering in view/app/export; the per-mapping confirm UI
  (editable, confidence, low-confidence flagged, no sight-unseen confirm-all); the mappings-applied
  provenance view (both paths) in app + export; the "let AI answer" checkbox.

## Explicitly OUT of slice 10
- **The matcher (Bucket B)** and **independent keystone sign-off** — external/parked, unchanged.
- **Prompt changes** — reuse the labels-only proposers and the pinned client as-is.
- **Any new note module / engine arithmetic** — this is wiring + the AI-assumed state + provenance,
  nothing new computed.

## Sequencing
After this, the no-mappings path, the mappings front page, and the AI-answer checkbox are all live and
honest; the only remaining threads are the two external/parked ones (matcher, independent sign-off).
The discipline this slice locks: **the AI acts inside the app, but every classification carries its
provenance and an AI guess can never become apparent fact — the honesty boundary holds across the live
call path, not just in the engine.**
