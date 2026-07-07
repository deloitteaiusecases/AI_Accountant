"""Master-FS (seed-driven) demo view — Slice G1.

COEXISTS with the GL-pipeline statement view (`fsgen_app.py`): a sidebar radio selects this view, which
drives the FULL master-FS confirm chain through the EXISTING engine gates —

    G0 data → G1 detect & CONFIRM archetype → G2 per-line CONFIRM mapping → G3 unit
    → G4 generate + build notes → G5 CONFIRM split → G6 export

— each gate a REAL `st.stop()` human stop. The GUI CALLS the engine and AUTHORS NO NUMBER: every figure is
computed by the engine from a CONFIRMED classification; `not_final` is ENGINE-derived (it reads the
provenance/status the engine assigned), so skipping a confirm leaves the line AI_ASSUMED (amber) and
not-final ON SCREEN and in the downloaded PDF/Excel — the screen can never claim more certainty than the
engine assigned. Every confirm is the simplest shape that fits — yes/no, pick-from-AI-options, or
options-plus-type-your-own — and "type your own" edits a CLASSIFICATION / LABEL ONLY (which archetype,
which concept, which maturity); there is NEVER a free-text monetary-amount box on a reconciling line.

DEMO HONESTY — the one boundary this slice introduces. The proposers run against `_DemoLLM`, an OFFLINE
stand-in whose answers are DERIVED FROM THE FIXTURE's known concepts. This proves the GUI DRIVES the
engine and the gates HOLD; it does NOT prove detection/mapping ACCURACY — a real LLM on real labels is the
untested hard part (same honesty as "synthetic ties prove mechanics, not real-data correctness"). `_DemoLLM`
is STRUCTURALLY confined to this demo module: the `ai_accountant` engine package never imports it (a grep
test guards that), and the production proposers default to the real `LLMClient` (no stub can reach them).
Live multi-file xlsx ingestion is the explicitly parked slice.
"""
from __future__ import annotations

import calendar
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

from ai_accountant.master_fs.close import apply_retained_close, detect_close_state
from ai_accountant.master_fs.notes import derive_breakdown
from ai_accountant.master_fs.mapping import (agenda_payload, apply_mapping_decisions, confirm_archetype,
                                             propose_account_concepts, propose_archetype,
                                             propose_maturity_pairing, propose_maturity_split,
                                             propose_note_agenda)
from ai_accountant.master_fs.model import ClientMappingStore, MappingRecord, ProvenanceStore
from ai_accountant.master_fs.orchestrator import _stored_from_mapping
from ai_accountant.master_fs.seed import load_all_masters, load_master_store
from ai_accountant.tb_ingest import (apply_tb_sign, best_bs_sheet, best_tb_sheet, confirm_column_roles,
                                     confirm_tb_sign, detect_header_row, load_grid, parse_bs_split, parse_tb,
                                     propose_column_roles, propose_tb_sign, sheet_names, to_engine_inputs)
from ai_accountant.tb_ingest.columns import ROLES
from ai_accountant.tb_ingest.resolve import build_upload_proposals, propose_archetype_from_mapping, resolve_row
from ai_accountant.tb_ingest.source_route import source_routing_audit
from ai_accountant.reporting.master_fs_export import (build_master_fs_export,
                                                      export_master_fs_excel_bytes,
                                                      export_master_fs_pdf_bytes)
from ai_accountant.reporting.render_model import status_caption

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "tests" / "fixtures"
DISCLAIMER = ("SYNTHETIC demo data — detection & mapping run against an OFFLINE stand-in whose answers are "
              "derived from the fixture's known result. Proves the GUI drives the engine and every gate "
              "holds; does NOT prove detection/mapping accuracy.")

UNITS = ["— withheld —", "SAR (absolute)", "SAR'000", "SAR millions"]

# status WORD (status_caption) + a SUBTLE screen colour that REINFORCES it — mirrors render_model.STATUS_COLOUR
# so screen and the PDF/Excel documents read identically. The WORD carries the meaning; colour only echoes it.
_SCREEN_COLOUR = {"BUILT": "green", "RECONCILED": "green",
                  "PARTIAL": "orange", "SPLIT_UNCONFIRMED": "orange",
                  "JUDGMENT_CONFIRMED": "violet", "JUDGMENT_UNCONFIRMED": "violet",
                  "BLOCKED": "red", "not generated": "gray"}


def _chip(status: str, detail: str = "") -> str:
    return f":{_SCREEN_COLOUR.get(status, 'gray')}[{status_caption(status, detail)}]"


# ----------------------------------------------------------------------------- fixtures (live xlsx parked)
@dataclass(frozen=True)
class _FixtureSpec:
    key: str
    label: str
    short: str
    seed_id: "str | None"          # the fixture's KNOWN archetype (None → ambiguous, the unsure-block demo)
    tb: "str | None"
    gl: "str | None"
    ambiguous: bool = False


_FIXTURES = {
    "bank": _FixtureSpec("bank", "Bank (KSA bank archetype)", "synthetic bank demo", "ksa_bank",
                         "bank_demo/bank_synthetic_tb.json", "bank_demo/bank_synthetic_gl.json"),
    "telecom": _FixtureSpec("telecom", "Telecom (corporate archetype)", "synthetic telecom demo",
                            "telecom_mobily", "telecom_demo/telecom_synthetic_tb.json",
                            "telecom_demo/telecom_synthetic_gl.json"),
    "ambiguous": _FixtureSpec("ambiguous", "Ambiguous (generic labels — demo the unsure block)",
                              "ambiguous demo", None, None, None, ambiguous=True),
}

# Generic labels that fit BOTH registered charts → no discriminating signal → the detector lands on UNSURE.
_AMBIGUOUS_ITEMS = [("1", "Cash and cash equivalents"), ("2", "Accounts receivable"),
                    ("3", "Accounts payable"), ("4", "Share capital"), ("5", "Retained earnings"),
                    ("6", "Other reserves")]


@dataclass
class _Fixture:
    """Runtime view of a chosen fixture — rebuilt deterministically each Streamlit run from its spec."""
    spec: _FixtureSpec
    items: list = field(default_factory=list)          # (account, the seed's canonical caption) — a TB-like label
    tb_rows: list = field(default_factory=list)        # [{account,label,current,prior}] for the engine
    client: str = "demo-client"
    canon: dict = field(default_factory=dict)          # concept_id -> canonical (for _DemoLLM's known answer)
    cid_by_account: dict = field(default_factory=dict)
    lease_lines: list = field(default_factory=list)    # split-note movement lines [{code,label,amount,maturity}]
    note_total: float = 0.0


def _load_fixture(spec: _FixtureSpec, stores: dict) -> _Fixture:
    if spec.ambiguous:                                  # no TB — this fixture exists to demo the G1 unsure block
        return _Fixture(spec=spec, items=list(_AMBIGUOUS_ITEMS), client="ambiguous-demo")
    store = stores[spec.seed_id]
    canon = {c.concept_id: c.canonical_concept for c in store.concepts.values()}
    tb = json.loads((FIX / spec.tb).read_text(encoding="utf-8"))
    cid_by_account = {r["account"]: r["concept_id"] for r in tb["rows"]}
    # label = the row's OWN caption when it carries one (sub-account detail for a breakdown), else the seed's
    # concept caption — so multiple leaves under one concept keep distinct labels to group by.
    items = [(r["account"], r.get("label") or canon[r["concept_id"]]) for r in tb["rows"]]
    tb_rows = [{"account": r["account"], "label": r.get("label") or canon[r["concept_id"]],
                "current": float(r["current"]), "prior": None} for r in tb["rows"]]
    fx = _Fixture(spec=spec, items=items, tb_rows=tb_rows, client=tb["client"], canon=canon,
                  cid_by_account=cid_by_account)
    if spec.gl:
        gl = json.loads((FIX / spec.gl).read_text(encoding="utf-8"))
        fx._gl = gl                                     # raw GL kept for payload assembly (note: dynamic attr)
        lease = gl.get("notes", {}).get("lease_liabilities")
        if lease:
            fx.lease_lines = lease["lines"]
            fx.note_total = float(lease["note_total"])
    return fx


def _gl_payloads(fx: _Fixture, llm, split_confirmed: bool) -> dict:
    """Assemble the GL note payloads for build_master_fs_export. Bank → the roll-forward fixture verbatim.
    Telecom → call the REAL propose_maturity_split (via _DemoLLM) to get the lease classification, then hand
    the engine the line amounts to split DETERMINISTICALLY; confirmed flows from the G5 gate."""
    spec = fx.spec
    if spec.key == "bank":
        gl = getattr(fx, "_gl", {})
        sc = gl["sign_convention"]
        return {k: {"leaves": v["leaves"], "confirmed": v["confirmed"], "sign_convention": sc}
                for k, v in gl["notes"].items()}
    if spec.key == "telecom" and fx.lease_lines:
        mitems = [(l["code"], l["label"]) for l in fx.lease_lines]           # AI proposes the maturity (label-only)
        proposals = propose_maturity_split(mitems, client=llm)
        classification = {p.code: p.maturity for p in proposals if p.maturity in ("current", "non_current")}
        line_amounts = {l["code"]: float(l["amount"]) for l in fx.lease_lines}
        return {"lease_liabilities": {"classification": classification, "note_total": fx.note_total,
                                      "line_amounts": line_amounts, "confirmed": split_confirmed}}
    return {}


# ----------------------------------------------------------------------------- the OFFLINE demo LLM (fenced)
class _DemoLLM:
    """OFFLINE stand-in for the live LLMClient — returns canned JSON DERIVED FROM the fixture's known
    concepts, keyed by which proposer's system prompt is calling. The REAL proposers + the REAL
    deterministic verdict run unchanged, just on deterministic input.

    FENCE: this class lives ONLY in this demo module; the `ai_accountant` engine/production package never
    imports it (grep-guarded by the app test), and it CANNOT be constructed without a demo `_Fixture`
    loaded from tests/fixtures — so it can never be pointed at real client data. Production swaps in a real
    `LLMClient` at the same call site (the proposers default to it when no client is passed)."""

    def __init__(self, fixture: _Fixture):
        if not isinstance(fixture, _Fixture):           # structural guard — no fixture, no stub
            raise TypeError("_DemoLLM is demo-only: it requires a fixture loaded from tests/fixtures")
        self.fx = fixture
        self.target = fixture.spec.seed_id
        self._all = list(load_all_masters())

    def complete_json(self, prompt, *, system=None, **_kw) -> dict:
        s = system or ""
        if "ARCHETYPE DETECTOR" in s:
            return self._archetype()
        if "CURRENT or NON-CURRENT" in s:               # maturity proposer (IAS 1 / IFRS 9 frame)
            return self._maturity()
        if "presented COMPONENT lines" in s or "group the sub-accounts" in s:
            return {"components": []}                    # demo: defer to the deterministic group-by-label base
        return self._mapping()                          # account → concept proposals

    def _archetype(self) -> dict:
        if self.fx.spec.ambiguous:                      # generic labels fit EVERY chart → non-discriminating
            return {"per_label": [{"label": l, "fits": list(self._all), "evidence": "generic line"}
                                  for _a, l in self.fx.items], "absent": {}}
        others = [i for i in self._all if i != self.target]   # each label fits ONLY the fixture's known chart
        return {"per_label": [{"label": l, "fits": [self.target], "evidence": f"'{l}'"} for _a, l in self.fx.items],
                "absent": {o: ["(signature lines absent)"] for o in others}}

    def _mapping(self) -> dict:
        out = []
        for a, lbl in self.fx.items:
            cid = self.fx.cid_by_account.get(a)
            concept = self.fx.canon.get(cid) if cid else None      # ambiguous: no known concept → 'unsure'
            out.append({"account": a, "concept": concept or "unsure",
                        "confidence": "high" if concept else "low", "evidence": f"'{lbl}'"})
        return {"proposals": out}

    def _maturity(self) -> dict:
        known = {l["code"]: l["maturity"] for l in self.fx.lease_lines}
        return {"proposals": [{"code": c, "maturity": m, "confidence": "high", "evidence": c}
                              for c, m in known.items()]}


# ----------------------------------------------------------------------------- MfsExport → Streamlit renderer
def render_mfs_faces(model, unit_confirmed: bool) -> None:
    """The three faces, per MfsLine: derived → neutral bold; ai_assumed / judgment_only / new_concept →
    amber/violet WORD tags. Figure WITHHELD until the unit is confirmed (R11). The balance keystone is a
    SEPARATE claim (read from the engine's own balance finding), like the GL view's keystone."""
    if model.disclaimer:
        st.warning("⚠ " + model.disclaimer)
    if model.not_final:
        st.error("DRAFT — NOT FINAL: contains provisional / unconfirmed line(s). This stamp is ENGINE-derived "
                 "(from the mapping provenance / note status) — it cannot be cleared from the GUI.")
    bal = [f for f in model.findings if str(f[0]) == "balance check"]
    st.markdown("**Balance keystone:** " + (":red[**DOES NOT BALANCE**]" if bal else ":green[**BALANCES**]")
                + "  ·  a separate claim from each line's own status")
    for stk, lines in model.statements.items():
        st.subheader(model.statement_titles.get(stk, stk))
        section = None
        for l in lines:
            if l.section != section:
                section = l.section
                st.markdown(f"**{section}**")
            amt = ("—" if l.current is None else
                   ("WITHHELD" if not unit_confirmed else f"{l.current:,.0f} {model.unit}"))
            tags = []
            if l.new_concept:
                tags.append(":orange[NEW concept — AI-proposed]")
            if l.ai_assumed:
                tags.append(":orange[AI assumption — not settled]")
            if l.judgment_only:
                _kind = model.judgment_kinds.get(l.concept_id, "split")   # the marker's OWN kind, not a fixed string
                tags.append(f":violet[{_kind.upper()}]")
            if l.split_undetermined:
                tags.append(":orange[SPLIT UNDETERMINED — total shown per the TB; breakdown is in the notes]")
            if getattr(l, "uncorroborated", False):
                tags.append(":orange[BS-ONLY — NOT RECONCILED to the TB (from the balance sheet)]")
            cols = st.columns([5, 2, 3])
            # derived totals/subtotals are engine arithmetic → neutral BOLD (never amber); leaves are indented
            cols[0].markdown(f"**{l.label}**" if l.derived else f"&nbsp;&nbsp;&nbsp;&nbsp;{l.label}")
            cols[1].markdown(amt)
            cols[2].markdown(" · ".join(tags))
    if model.findings:
        st.warning(f"{len(model.findings)} open finding(s) — accounts surfaced, not guessed: "
                   + "; ".join(f"`{a}` {why}" for a, _lbl, why in model.findings[:6]))


def render_mfs_note(nv, unit_confirmed: bool) -> None:
    """One declared note: the status reads in a WORD (status_caption) with a subtle colour chip; caveats;
    then the rows (WITHHELD until the unit). 'not generated' → grey word + reason, no rows — never faked."""
    st.markdown(f"**{nv.note_ref}** — {_chip(nv.status)}")
    for c in nv.caveats:
        st.caption(c)
    if nv.status == "not generated" or not nv.rows:
        st.caption("· the face line is unaffected; this note was not generated.")
        return
    if getattr(nv, "columns", None):                 # SL-1c.1 — REGISTER TABLE: N attribute columns + amount(s)
        cols = [str(c).replace("\n", " ") for c in nv.columns]
        amt = lambda v: ("WITHHELD" if not unit_confirmed else ("" if v is None else f"{v:,.2f}"))  # noqa: E731
        grid = []
        for r in nv.rows:
            base = dict(zip(cols, list(r.cells) + [""] * len(cols))) if r.cells else {cols[0]: r.label}
            base["Current"] = amt(r.value)
            base["Prior"] = amt(r.prior_value)
            grid.append(base)
        st.dataframe(grid, width="stretch", hide_index=True)
        return
    st.dataframe(
        [{"Line": ("    " * r.indent) + r.label,
          "Amount": ("WITHHELD" if not unit_confirmed else ("—" if r.value is None else f"{r.value:,.2f}"))}
         for r in nv.rows],
        width="stretch", hide_index=True)


# ----------------------------------------------------------------------------- the 6 confirm gates
def _restart(ss) -> None:
    for k in [k for k in ss if str(k).startswith("mfs_")]:
        del ss[k]


def _real_client():
    """The PRODUCTION LLM client for the upload path (never the demo stub — the fence). Returns a real
    LLMClient when an API key is available; None when offline, in which case the DETERMINISTIC preparer /
    heuristic resolvers carry a pre-mapped TB (the AI proposers are the fallback for raw/unfamiliar TBs)."""
    try:
        from ai_accountant.llm.client import LLMClient
        return LLMClient()
    except Exception:
        return None


def _g0_fixture(ss, stores) -> "dict | None":
    """Fixture source — byte-identical to the original G0 (the demo path; _DemoLLM stays fixture-only)."""
    case = st.radio("Demo dataset", list(_FIXTURES), key="mfs_dataset",
                    format_func=lambda k: _FIXTURES[k].label)
    if st.button("Load fixture", key="mfs_load"):
        _restart_downstream(ss)
        ss.mfs_case = case
        ss.mfs_loaded = True
        ss.mfs_mode = "fixture"
    if not ss.get("mfs_loaded"):
        st.info("Load a fixture to begin.")
        st.stop()
    fx = _load_fixture(_FIXTURES[ss.mfs_case], stores)
    st.caption(f"Loaded **{fx.spec.label}** — {len(fx.items)} account label(s).")
    return {"items": fx.items, "tb_rows": fx.tb_rows, "client": fx.client, "is_upload": False,
            "proposer": _DemoLLM(fx), "fx": fx, "bank_label": fx.spec.short, "disclaimer": DISCLAIMER,
            "notes_attempted": False}


_MONTHS = {m[:3].lower(): i for i, m in enumerate(calendar.month_name) if m}   # {'jan':1, …, 'dec':12}


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _period_label(raw):
    """Format a TB period header as a full date for the statement columns: "31 Dec 2024 (SAR 000s)" →
    "31st December 2024". Everything is parsed from the TB's OWN header (nothing hard-coded): the year is any
    19xx/20xx; the day+month come from "DD Month", "Month DD", or "DD-MM"/"DD/MM" — whatever the file uses.
    Falls back to the bare year if only a year is present, to the raw header if no year, and to None (→
    "Current/Prior") if blank."""
    if not raw:
        return None
    s = str(raw)
    ym = re.search(r"(?:19|20)\d{2}", s)
    if not ym:
        return s                                              # no year at all → show the header verbatim
    year, day, month = ym.group(0), None, None
    if (m := re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b", s)) and m.group(2)[:3].lower() in _MONTHS:
        day, month = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()]          # "31 December"
    elif (m := re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2})\b", s)) and m.group(1)[:3].lower() in _MONTHS:
        month, day = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))          # "December 31"
    elif (m := re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](?:19|20)\d{2}", s)):
        day, month = int(m.group(1)), int(m.group(2))                          # "31-12-2024" / "31/12/2024"
    if day and month and 1 <= month <= 12 and 1 <= day <= 31:
        return f"{day}{_ordinal(day)} {calendar.month_name[month]} {year}"
    return year                                               # only a year was resolvable → the bare year


def _reparse_upload(ss) -> None:
    """(Re)load the chosen sheet's grid from the uploaded bytes and re-propose column roles. Clears the
    column/sign confirmations so switching the sheet re-runs the confirm chain cleanly."""
    grid = load_grid(io.BytesIO(ss.mfs_upload_bytes), filename=ss.mfs_upload_name, sheet=ss.get("mfs_sheet"))
    hdr = detect_header_row(grid)
    ss.mfs_grid, ss.mfs_hdr = grid, hdr
    ss.mfs_colroles = propose_column_roles(grid[hdr], grid[hdr + 1:hdr + 6], client=_real_client())
    for k in ("mfs_cols_done", "mfs_sign_done"):
        ss.pop(k, None)


def register_decls(store):
    """The concepts that DECLARE they expect a register (seed mechanism:'register') as [(concept_id, label)].
    Only these are offered a register sheet — the app never tries to consume every sheet."""
    return [(d["concept"], (store.get(d["concept"]).canonical_concept if store.get(d["concept"]) else d["concept"]))
            for d in store.notes() if d.get("mechanism") == "register"]


def propose_register_sheets(store, sheets, tb_sheet, header_of, *, client=None) -> dict:
    """For each register-declaring concept, PROPOSE which non-TB sheet is its register — Layer 0 scored name/
    header match (no model), Layer 1 headers-only AI on a miss (via `propose_register_concept`). `header_of(sheet)`
    returns that sheet's header row (HEADERS ONLY reach the proposer — never a row/value). Returns
    {concept_id: {'sheet': str|None, 'layer': int, 'label': str}}. No sheet-name literal — the candidates are the
    register-declaring concepts (seed data) and the workbook's own sheet names."""
    from ai_accountant.tb_ingest.register import propose_register_concept
    rc = register_decls(store)
    out = {cid: {"sheet": None, "layer": 0, "label": lbl} for cid, lbl in rc}
    for sh in [s for s in sheets if s != tb_sheet]:
        p = propose_register_concept(sh, header_of(sh), rc, client=client)
        cid = p.get("concept_id")
        if cid in out and out[cid]["sheet"] is None:                      # first confident sheet wins per concept
            out[cid] = {"sheet": sh, "layer": p["layer"], "label": out[cid]["label"]}
    return out


def _g0_upload(ss, stores) -> "dict | None":
    """Upload source — the parsing front-end as a confirm chain: U1 propose columns → U2 confirm columns →
    U3 propose+confirm the TB-presentation sign → (items, tb_rows). TB-only, single workbook (xlsx/csv)."""
    st.caption("TB-only, single workbook (xlsx or csv). The AI/heuristic PROPOSES the column roles and the "
               "credit-sign convention; you CONFIRM both; code extracts every number. Live GL / multi-sheet "
               "is the parked slice — roll-forward notes will render 'not generated' (no movement data).")
    up = st.file_uploader("Trial balance", type=["xlsx", "csv"], key="mfs_upload")
    if st.button("Parse", key="mfs_parse") and up is not None:
        _restart_downstream(ss)
        ss.mfs_upload_bytes = up.getvalue()
        ss.mfs_upload_name = getattr(up, "name", "upload.xlsx")
        ss.mfs_sheets = sheet_names(io.BytesIO(ss.mfs_upload_bytes), filename=ss.mfs_upload_name)
        ss.mfs_sheet = best_tb_sheet(ss.mfs_sheets)
        ss.mfs_mode = "upload"
        _reparse_upload(ss)
    if not ss.get("mfs_colroles"):
        st.info("Upload a TB and click Parse.")
        st.stop()

    # multi-sheet workbook → pick WHICH sheet is the TB (reading only the first sheet would silently drop the
    # P&L / OCI sheets). Combining several sheets (TB + GL) is the parked slice — this picks ONE TB sheet.
    if ss.get("mfs_sheets") and len(ss.mfs_sheets) > 1:
        idx = ss.mfs_sheets.index(ss.mfs_sheet) if ss.mfs_sheet in ss.mfs_sheets else 0
        chosen = st.selectbox(f"Which of the {len(ss.mfs_sheets)} sheets is the trial balance?",
                              ss.mfs_sheets, index=idx, key="mfs_sheet_pick")
        if chosen != ss.mfs_sheet:
            ss.mfs_sheet = chosen
            _reparse_upload(ss)
            st.rerun()
        st.caption(f"Reading sheet **{ss.mfs_sheet}**. TB-only, single sheet — combining multiple sheets "
                   "(TB + GL) is the parked next slice.")

    # U2 · confirm column roles (per column — a role from the fixed enum, never a number)
    st.subheader("U2 · Confirm column roles")
    for c in ss.mfs_colroles:
        cols = st.columns([3, 4])
        cols[0].markdown(f"col {c.index} · **{c.header or '(blank)'}** — _{c.evidence}_")
        cols[1].selectbox("role", list(ROLES), index=list(ROLES).index(c.role),
                          key=f"mfs_col_{c.index}", label_visibility="collapsed")
    # Risk-1 (SL-1): when the amount columns can't be told apart by year (identical headers — raw vs adjusted,
    # or current vs prior), the current/prior pick is POSITIONAL. A swap would still balance (the firewall can't
    # catch it), so SHOW the chosen columns' sums + the raw/adjustment bridge and force an EXPLICIT confirm.
    from ai_accountant.tb_ingest.columns import column_amount_audit
    _decisions = {c.index: ss.get(f"mfs_col_{c.index}", c.role) for c in ss.mfs_colroles}
    _schema = confirm_column_roles(ss.mfs_colroles, _decisions)
    if _schema.period_ambiguous and not _schema.missing_required:
        aud = column_amount_audit(_schema, ss.mfs_grid, header_row=ss.mfs_hdr)
        st.warning("⚠ Current vs prior is assigned by POSITION (the amount headers don't carry a distinguishing "
                   "year). A swapped pick would still balance — confirm the columns below are right (a wrong "
                   "choice ties to the WRONG numbers, silently).")
        st.caption(f"**current →** col {aud['current']['index']} `{aud['current']['header']}` · Σ "
                   f"{aud['current']['sum']:,.0f}  ·  sample {aud['current']['sample']}")
        st.caption(f"**prior →** col {aud['prior']['index']} `{aud['prior']['header']}` · Σ "
                   f"{aud['prior']['sum']:,.0f}  ·  sample {aud['prior']['sample']}")
        if aud["adjustments"]:
            st.caption(f"adjustment column(s) detected — the ADJUSTED (post-adjustment) balance is read; raw "
                       f"balances are excluded. {len(aud['adjustments'])} adjustment column(s).")
        st.checkbox("I confirm the current/prior columns above are correct (not swapped)", key="mfs_period_ok")
    if st.button("Confirm columns", key="mfs_confirm_cols"):
        decisions = {c.index: ss.get(f"mfs_col_{c.index}", c.role) for c in ss.mfs_colroles}
        schema = confirm_column_roles(ss.mfs_colroles, decisions)
        if schema.missing_required:
            st.error(f"Missing required role(s): {schema.missing_required} — assign them and re-confirm.")
        elif schema.period_ambiguous and not ss.get("mfs_period_ok"):
            st.error("Tick the current/prior confirmation above — the period assignment is ambiguous and a "
                     "silent swap cannot be caught downstream.")
        else:
            parsed = parse_tb(ss.mfs_grid, schema, header_row=ss.mfs_hdr)
            ss.mfs_parsed_items, ss.mfs_parsed_tbrows = to_engine_inputs(parsed)
            ss.mfs_period = (parsed.period_current or None, parsed.period_prior or None)   # year labels (E1)
            ss.mfs_badrows = parsed.bad_rows
            ss.mfs_cols_done = True
    if not ss.get("mfs_cols_done"):
        st.stop()
    if ss.get("mfs_badrows"):
        st.warning(f"{len(ss.mfs_badrows)} row(s) had an amount but no resolvable account — SURFACED, never "
                   f"dropped: {[b['row'] for b in ss.mfs_badrows][:10]}")
    st.caption(f"Parsed **{len(ss.mfs_parsed_tbrows)}** account rows.")

    # U3 · TB-presentation sign (the balances-while-wrong firewall — confirm, never assume)
    st.subheader("U3 · Confirm the TB sign convention")
    st.caption("A wrong whole-side flip BALANCES while inverted — the balance check can't catch it, so this "
               "confirm is the guard. A section that nets negative is stored as credits → flip to positive.")
    sp = propose_tb_sign(ss.mfs_parsed_tbrows)
    for s in sp.sections:
        cols = st.columns([3, 4])
        cols[0].markdown(f"**{s.section}** ({s.side}) — _{s.evidence}_")
        cols[1].selectbox("sign", ["as_is", "flip"], index=("as_is", "flip").index(s.proposed),
                          key=f"mfs_sign_{s.section}", label_visibility="collapsed")
    # Fix 1(b) — CONSEQUENCE shown: the income/expense sections netted under the CURRENT sign choices. A wrong
    # EXPENSE sign has NO arithmetic anchor (the SOFP balance-check never sees the P&L; the income statement
    # foots under either sign), so showing this figure is the ONLY guard — an implausible value (e.g. ~19.7M vs
    # ~1.8M) reveals a wrong pick BEFORE it is confirmed. Live: it updates as the toggles change.
    _result = [s for s in sp.sections if s.side in ("income", "expense")]
    if _result:
        _net = sum((-s.net_current if ss.get(f"mfs_sign_{s.section}", s.proposed) == "flip" else s.net_current)
                   for s in _result)
        st.info(f"↳ Under the signs above, the income/expense sections net to **{_net:,.0f}** — a sanity check "
                f"on net income (a wrong expense sign makes this implausibly large; the balance check can't "
                f"catch it, so this is the guard).")
    if st.button("Confirm sign", key="mfs_confirm_sign"):
        decisions = {s.section: ss.get(f"mfs_sign_{s.section}", s.proposed) for s in sp.sections}
        conv = confirm_tb_sign(sp, decisions, approver="reviewer", at="upload")
        ss.mfs_tbrows_signed = apply_tb_sign(ss.mfs_parsed_tbrows, conv)
        ss.mfs_sign_done = True
    if not ss.get("mfs_sign_done"):
        st.stop()

    # U4 · current/non-current split source (OPTIONAL, Slice B2b) — point to the balance-sheet face sheet so the
    # engine reads its current/non-current split, RECONCILES it to the TB total, and ties the face. The TB read
    # above is untouched; this is an ADDITIONAL read of a second sheet. '(none)' → the TB-only split (B2a) stands.
    other_sheets = [n for n in (ss.get("mfs_sheets") or []) if n != ss.get("mfs_sheet")]
    if other_sheets:
        st.subheader("U4 · Current/non-current split source (optional)")
        st.caption("If a balance-sheet face sheet carries the current/non-current split the TB lumps, point to "
                   "it — the engine RECONCILES its split to the TB total (nc + c == TB, both years) before "
                   "applying. Leave '(none)' to keep the TB-only split.")
        default_bs = best_bs_sheet(ss.mfs_sheets, exclude=ss.get("mfs_sheet"))
        opts = ["(none)"] + other_sheets
        bs_pick = st.selectbox("Balance-sheet face sheet", opts,
                               index=opts.index(default_bs) if default_bs in opts else 0, key="mfs_bs_pick")
        if bs_pick == "(none)":
            for k in ("mfs_bs_grid", "mfs_bs_hdr", "mfs_bs_colroles", "mfs_bs_schema", "mfs_bs_sheet"):
                ss.pop(k, None)
        else:
            if ss.get("mfs_bs_sheet") != bs_pick:
                bg = load_grid(io.BytesIO(ss.mfs_upload_bytes), filename=ss.mfs_upload_name, sheet=bs_pick)
                bh = detect_header_row(bg)
                ss.mfs_bs_grid, ss.mfs_bs_hdr, ss.mfs_bs_sheet = bg, bh, bs_pick
                ss.mfs_bs_colroles = propose_column_roles(bg[bh], bg[bh + 1:bh + 6], client=_real_client())
                ss.pop("mfs_bs_schema", None)
            for c in ss.mfs_bs_colroles:
                cc = st.columns([3, 4])
                cc[0].markdown(f"col {c.index} · **{c.header or '(blank)'}** — _{c.evidence}_")
                cc[1].selectbox("role", list(ROLES), index=list(ROLES).index(c.role),
                                key=f"mfs_bscol_{c.index}", label_visibility="collapsed")
            if st.button("Confirm BS columns", key="mfs_confirm_bscols"):
                dec = {c.index: ss.get(f"mfs_bscol_{c.index}", c.role) for c in ss.mfs_bs_colroles}
                sch = confirm_column_roles(ss.mfs_bs_colroles, dec)
                if sch.missing_required:
                    st.error(f"BS sheet missing required role(s): {sch.missing_required} — assign and re-confirm.")
                else:
                    ss.mfs_bs_schema = sch
                    ss.pop("mfs_bs_split_confirmed", None)   # a new BS source re-opens the reconcile gate
            if ss.get("mfs_bs_schema"):
                st.caption("BS columns confirmed — the split is reconciled + confirmed after the account mapping (G2).")

    return {"items": ss.mfs_parsed_items, "tb_rows": ss.mfs_tbrows_signed, "client": "uploaded-tb",
            "is_upload": True, "proposer": _real_client(), "fx": None, "bank_label": "uploaded TB",
            "disclaimer": "", "notes_attempted": True}


def render_master_fs(ss) -> None:
    st.title("Master-FS (seed-driven) — DRAFT")
    st.caption("The AI PROPOSES (columns, sign, archetype, account→concept, maturity); a human CONFIRMS at "
               "every gate; the engine computes every number. Each confirm is the simplest shape that fits, "
               "and 'type your own' only ever edits a LABEL — there is no amount box on any reconciling line.")
    if st.button("Restart master-FS", key="mfs_restart"):
        _restart(ss)
        st.rerun()

    stores = load_all_masters()

    # ---- G0 · Data — fixture (demo) OR upload a real TB workbook (xlsx/csv) ----
    st.header("G0 · Data")
    source = st.radio("Source", ["Fixture (demo)", "Upload a TB (.xlsx / .csv)"], key="mfs_source")
    ctx = _g0_upload(ss, stores) if source.startswith("Upload") else _g0_fixture(ss, stores)
    items, tb_rows, client = ctx["items"], ctx["tb_rows"], ctx["client"]
    is_upload, llm = ctx["is_upload"], ctx["proposer"]

    # ---- G1 · Detect → CONFIRM archetype (no default pick; unsure BLOCKS) ----
    st.header("G1 · Detect archetype  ·  CONFIRM (no default)")
    if is_upload:                                        # a pre-mapped TB detects deterministically; else AI
        proposal = propose_archetype_from_mapping(tb_rows, stores) or propose_archetype(items, stores, client=llm)
    else:
        proposal = propose_archetype(items, stores, client=llm)
    for r in proposal.ranked:
        forl = "; ".join(lbl for lbl, _ev in r.matched[:4]) or "—"
        st.markdown(f"- **{r.label}** · score `{r.score:.2f}` · fits ONLY this chart: {forl}"
                    + (f" · signature lines ABSENT: {', '.join(map(str, r.absent[:3]))}" if r.absent else ""))
    if proposal.verdict == "unsure":
        st.error(f"Archetype UNSURE ({proposal.block_reason}) — no seed is selected by default. {proposal.finding}")
    options = [r.seed_id for r in proposal.ranked]
    pick = st.radio("Confirm the archetype (you must pick — nothing is pre-selected)", options, index=None,
                    key="mfs_pick", format_func=lambda sid: next(r.label for r in proposal.ranked if r.seed_id == sid))
    if st.button("Confirm archetype", key="mfs_confirm_arch", disabled=pick is None):
        _restart_downstream(ss)
        ss.mfs_seed_id = confirm_archetype(proposal, pick, approver="demo-reviewer", at="demo")
    if not ss.get("mfs_seed_id"):
        st.info("⬆ Pick and confirm the archetype to continue (a confident WRONG archetype is the worst outcome).")
        st.stop()
    store = load_master_store(seed_id=ss.mfs_seed_id)    # a falsy/never-confirmed id never reaches the store

    # ---- G2 · Map → CONFIRM mappings PER LINE (unreviewed stays AI_ASSUMED, never silently promoted) ----
    st.header("G2 · Map account → concept  ·  CONFIRM per line")
    st.caption("Per line: ✓ confirm the AI proposal, leave it AI-ASSUMED (unreviewed → amber, never BUILT), or "
               "OVERRIDE to a different concept. 'Override' picks a LABEL from the seed's concepts — never a "
               "number. NOT a blanket 'confirm all': a line you don't review stays AI-assumed and not-final.")
    if is_upload:                                       # preparer-first (mapping column), AI for the rest
        proposals = build_upload_proposals(tb_rows, store, client=llm)
        # Fix 3 (SL-1d) — surface the OPTIONAL Source-tag cross-check: where the preparer's note tag groups rows
        # the engine resolves to DIFFERENT concepts (or one concept carries several tags), show it. Advisory only —
        # no auto-route, no balance impact; the human resolves at the per-line gate below. No Source column → no-op.
        _resolved = {r["account"]: (resolve_row(store, r)[0].concept_id if resolve_row(store, r)[0] else None)
                     for r in tb_rows}
        _aud = source_routing_audit(tb_rows, _resolved)
        if _aud["conflicts"] or _aud["split"]:
            msg = "; ".join(f"Source '{c['tag']}' groups rows resolving to {c['concepts']}" for c in _aud["conflicts"][:4])
            msg += ("; " if msg and _aud["split"] else "")
            msg += "; ".join(f"concept {s['concept']} carries tags {s['tags']}" for s in _aud["split"][:4])
            st.warning(f"⚠ Source tag vs engine resolution disagree (advisory — confirm per line): {msg}")
    else:
        proposals = propose_account_concepts(items, store, client=llm)
    leaf_concepts = sorted({c.canonical_concept for c in store.concepts.values()
                            if c.kind == "leaf" and c.concept_id not in store.carry_leaf_ids()})
    _CONFIRM, _ASSUME = "✓ Confirm AI proposal", "Leave AI-assumed (unreviewed)"
    # ONE-CLICK path: confirm every AI proposal at once (no per-line rerun). Per-line review stays below for
    # anyone who wants to leave a line AI-assumed or override its concept.
    if st.button("✓ Confirm ALL AI proposals", key="mfs_confirm_all", type="primary"):
        ms, au = ClientMappingStore(), ProvenanceStore()
        apply_mapping_decisions(proposals, store, client_id=client,
                                decisions={p.code: "confirm" for p in proposals},
                                mapping_store=ms, audit=au, approver="reviewer", at="mfs")
        ss.mfs_stored = _stored_from_mapping(ms, client, store.master_id, tb_rows)
        ss.mfs_mapping_confirmed = True
        st.rerun()
    st.caption("…or review per line below — leave a line AI-assumed (amber, not final) or override its concept.")
    # key per ROW INDEX, never per account code — an uploaded TB's code column can repeat (or be a level),
    # so a code-keyed widget would collide. Account uniqueness for the engine is guaranteed in to_engine_inputs.
    for i, p in enumerate(proposals):
        cols = st.columns([3, 3, 4])
        cols[0].markdown(f"`{p.code}` · {p.label}")
        cols[1].markdown(f"→ **{p.line}** · {p.confidence}" + (f" · _{p.evidence}_" if p.evidence else ""))
        cols[2].selectbox("decision", [_ASSUME, _CONFIRM, *(f"Override → {c}" for c in leaf_concepts)],
                          key=f"mfs_map_{i}", label_visibility="collapsed")
    if st.button("Apply mappings", key="mfs_apply_map"):
        decisions = {}
        for i, p in enumerate(proposals):
            choice = ss.get(f"mfs_map_{i}", _ASSUME)
            if choice == _CONFIRM:
                decisions[p.code] = "confirm"
            elif choice.startswith("Override → "):
                p.line = choice[len("Override → "):]     # type-your-own edits a LABEL only (a concept canonical)
                decisions[p.code] = "confirm"
            else:
                decisions[p.code] = "assume"              # unreviewed → AI_ASSUMED (flagged, never BUILT)
        ms, au = ClientMappingStore(), ProvenanceStore()
        apply_mapping_decisions(proposals, store, client_id=client, decisions=decisions,
                                mapping_store=ms, audit=au, approver="reviewer", at="mfs")
        ss.mfs_stored = _stored_from_mapping(ms, client, store.master_id, tb_rows)
        ss.mfs_mapping_confirmed = True
        ss.pop("mfs_bs_split_confirmed", None)            # a re-map re-opens the BS-split reconcile (it depends on it)
        ss.pop("mfs_sign_corr_confirmed", None)           # …and the sign-correction diagnosis (depends on the mapping)
    if not ss.get("mfs_mapping_confirmed"):
        st.info("⬆ Apply the per-line mapping decisions to continue.")
        st.stop()

    # ---- BS-SPLIT · reconcile the balance-sheet current/non-current split to the TB, then CONFIRM (Slice B2b).
    # Runs only when a BS sheet was read (U4) and its columns confirmed. The reconcile is VISIBLE: ✓ reconciled /
    # ✗ disagree (shown unsplit) / ⚠ BS-only (no TB anchor, injected uncorroborated). Confirm applies it; until
    # then the split is NOT applied and the run is not-final. No BS sheet → this gate is absent (B2a stands).
    if is_upload and ss.get("mfs_bs_schema") and ss.get("mfs_bs_grid") is not None \
            and not ss.get("mfs_bs_split_confirmed"):
        resolved = parse_bs_split(ss.mfs_bs_grid, ss.mfs_bs_schema, store, client=_real_client())
        probe = build_master_fs_export(store, {**ss.mfs_stored, "face_split": resolved, "face_split_confirmed": True})
        finds = {f[0]: f[2] for f in probe.findings}

        def _face(cid):
            return next((l for s in probe.statements.values() for l in s if l.concept_id == cid), None)

        st.header("BS split · reconcile the current/non-current split to the TB")
        st.caption("The balance-sheet face discloses the current/non-current split the trial balance lumps. The "
                   "engine reconciles each split to the TB total (nc + c == TB, BOTH years). Confirm to apply; a "
                   "split that disagrees is shown unsplit (flagged); a BS-only figure is injected but marked "
                   "uncorroborated. The TB is never overwritten — it is the anchor the split is checked against.")
        clean, _amb = store.maturity_pairs()
        pairs = clean + [tuple(p) for p in ss.mfs_stored.get("maturity_pairs_confirmed", [])]
        shown = 0
        for nc, c in pairs:
            if nc not in resolved["amounts"] and c not in resolved["amounts"]:
                continue
            shown += 1
            cap = (store.get(nc) or store.get(c)).canonical_concept.rsplit("—", 1)[0].strip()
            if f"maturity:{nc}" in finds or f"maturity:{c}" in finds:
                st.markdown(f"✗ **{cap}** — {finds.get(f'maturity:{nc}', finds.get(f'maturity:{c}'))}")
            elif f"face_only:{nc}" in finds or f"face_only:{c}" in finds:
                st.markdown(f"⚠ **{cap}** — BS-only, no TB anchor → injected but marked **uncorroborated** "
                            "(shown, never reading as reconciled)")
            else:
                fnc, fc = _face(nc), _face(c)
                vnc = fnc.current if fnc else 0.0
                vc = fc.current if fc else 0.0
                st.markdown(f"✓ **{cap}** — nc {vnc:,.0f} + c {vc:,.0f} = {vnc + vc:,.0f} reconciles to the TB total")
        for ap in resolved.get("ai_proposed", []):           # LIVE-AI-proposed mapping (B2c) — human confirms here
            ac = store.get(ap["concept_id"])
            st.markdown(f"⚙ **AI-proposed mapping** — `{ap['label']}` → **{ac.canonical_concept if ac else ap['concept_id']}** "
                        "(live model; confirming applies it — its amount is still reconciled to the TB below)")
        for u in resolved["unmapped"]:
            st.markdown(f"• unmapped BS line `{u['label']}` — {u.get('reason', 'flagged, not applied')}")
        if not shown and not resolved["unmapped"] and not resolved.get("ai_proposed"):
            st.info("No balance-sheet line resolved to a current/non-current concept pair.")
        bcol, scol = st.columns(2)
        if bcol.button("✓ Confirm & apply the BS split", key="mfs_confirm_bssplit", type="primary"):
            ss.mfs_stored = {**ss.mfs_stored, "face_split": resolved, "face_split_confirmed": True}
            ss.mfs_bs_split_confirmed = True
            st.rerun()
        if scol.button("Skip — keep the TB-only split", key="mfs_skip_bssplit"):
            ss.mfs_bs_split_confirmed = True                 # proceed without applying (B2a stands)
            ss.mfs_stored = {k: v for k, v in ss.mfs_stored.items() if k not in ("face_split", "face_split_confirmed")}
            st.rerun()
        st.stop()

    # ---- S · Note agenda (AI SURVEY) — the AI proposes WHICH notes the TB supports; the engine PROVES each.
    # Live on the upload path (a real model, structure-only payload); with no model it falls to the seed
    # static floor (agenda=None). The agenda only chooses what to ATTEMPT — every figure is re-derived and
    # foot-checked, so a proposed note that doesn't reconcile renders BLOCKED ("proposed but does not
    # reconcile"), never BUILT. The AI guides the agenda; code proves every number. (Feeds C2 its concept list.)
    if is_upload and not ss.get("mfs_agenda_confirmed"):
        survey_client = _real_client()
        if survey_client is not None and "mfs_agenda_proposal" not in ss:
            ms_p = ClientMappingStore()
            for mrec in ss.mfs_stored["mappings"]:
                ms_p.put(client, MappingRecord(account=mrec["account"], concept_id=mrec.get("concept_id"),
                                               client_label=mrec.get("client_label", ""),
                                               provenance=mrec.get("provenance", ""), master_id=store.master_id))
            cur_p = {t["account"]: t["current"] for t in ss.mfs_stored["tb"]}
            lvl_p = {t["account"]: t.get("levels", []) for t in ss.mfs_stored["tb"]}
            ss.mfs_agenda_proposal = propose_note_agenda(
                agenda_payload(store, ms_p, client, cur_p, lvl_p), client=survey_client)
        prop = ss.get("mfs_agenda_proposal")
        if prop:
            st.header("S · Note agenda  ·  AI survey (engine verifies)")
            st.caption("The AI surveyed the TB STRUCTURE (labels + +/− signs + counts — NEVER amounts) and "
                       "proposes which notes it supports. The engine builds each and shows its verdict; a note "
                       "that doesn't FOOT reads 'proposed but does not reconcile', never BUILT. Confirm/trim the "
                       "agenda; the engine proves every number.")
            probe = build_master_fs_export(store, {**ss.mfs_stored, "agenda": {"buildable": prop["buildable"]}},
                                           notes_attempted=True)
            verdict = {v.note_ref: v.status for v in probe.note_views}
            tot = {v.note_ref: (v.rows[-1].raw_sar if v.rows else 0.0) for v in probe.note_views}
            stmt_total = {l.concept_id: l.current for st in probe.statements.values() for l in st if l.kind == "total"}

            def _cap(cid):
                c = store.get(cid)
                return c.canonical_concept if c else cid

            def _pct(cid):                                   # QUANTITATIVE materiality — CODE owns the figures
                c = store.get(cid)
                cov = store.coverage_totals(c.statement) if c else ()
                base = next((stmt_total.get(t) for t in cov if stmt_total.get(t)), None)
                note_t = tot.get(_cap(cid))
                return abs(note_t) / abs(base) * 100 if (base and note_t) else None
            # order the displayed agenda by materiality (AI semantic flag, then code %) — display only, never status
            ordered = sorted(prop["buildable"],
                             key=lambda c: (prop["semantic_material"].get(c, False), _pct(c) or 0.0), reverse=True)
            for cid in ordered:
                cap = _cap(cid)
                eng = verdict.get(cap, "not generated")
                eng_txt = ("proposed but does not reconcile" if eng == "BLOCKED" else eng)   # AI-proposed, engine-rejected
                sem = "material (reader expects a note)" if prop["semantic_material"].get(cid) else "—"
                pct = _pct(cid)
                pct_txt = f"  ·  {pct:.1f}% of statement" if pct is not None else ""
                st.markdown(f"- **{cap}** → AI: _{sem}_{pct_txt}  ·  engine: **{eng_txt}**")
            for nb in prop["not_buildable"]:
                st.caption(f"· not buildable — {_cap(nb['concept_id'])}: {nb['reason']}")
            if st.button("Confirm note agenda", key="mfs_confirm_agenda"):
                ss.mfs_stored = {**ss.mfs_stored, "agenda": prop}
                ss.mfs_agenda_confirmed = True
                st.rerun()
            st.stop()

    # ---- C1 · Close current-year result into retained — DETECT + CONFIRM, never automatic ----
    if store.meta.get("result_close"):
        probe = build_master_fs_export(store, ss.mfs_stored)
        cp = detect_close_state(store, probe)
        if cp.verdict == "pre_close" and not ss.get("mfs_close_done"):
            st.header("C1 · Close current-year result  ·  CONFIRM (pre-close detected)")
            st.warning(cp.finding)
            st.caption("Detected, not assumed — closing the current-year result into retained is the one step "
                       "that BALANCES WHILE WRONG (double-count a post-close TB). Confirm only a PRE-CLOSE TB.")
            cc1, cc2 = st.columns(2)
            if cc1.button("Confirm pre-close — close result into retained", key="mfs_confirm_close"):
                ss.mfs_stored = apply_retained_close(ss.mfs_stored, cp, approver="reviewer", at="mfs")
                ss.mfs_close_done = True
                st.rerun()
            if cc2.button("No — this TB is already post-close (no close)", key="mfs_decline_close"):
                ss.mfs_close_declined = True
            if not ss.get("mfs_close_declined"):
                st.stop()
        elif cp.verdict == "post_close":
            st.caption(f"C1 · {cp.finding}")
        elif cp.verdict == "ambiguous":
            st.warning(f"C1 · {cp.finding}")

    # ---- C2 · Review static-breakdown groupings (path-aware; VISIBLE + explicitly accepted; → not_final) ----
    # the confirmed AI AGENDA supersedes the seed static set on upload; else the seed static floor (headless)
    _agenda = ss.mfs_stored.get("agenda")
    if isinstance(_agenda, dict) and _agenda.get("buildable") is not None:
        static_concepts = list(_agenda["buildable"])
    else:
        static_concepts = [d["concept"] for d in store.meta.get("notes", [])
                           if d.get("mechanism") == "static_breakdown"]
    cur_map = {t["account"]: t["current"] for t in ss.mfs_stored["tb"]}
    lvl_map = {t["account"]: t.get("levels", []) for t in ss.mfs_stored["tb"]}

    def _concept_view(concept):
        mp = {m["account"]: cur_map.get(m["account"], 0.0) for m in ss.mfs_stored["mappings"]
              if m["concept_id"] == concept and m["account"] in cur_map}
        lb = {m["account"]: m.get("client_label", "") for m in ss.mfs_stored["mappings"]
              if m["concept_id"] == concept}
        return mp, lb

    eligible = [(c, *_concept_view(c)) for c in static_concepts]
    eligible = [(c, mp, lb) for c, mp, lb in eligible if len(mp) > 1]       # >1 leaf → a real breakdown to review
    if eligible:
        st.header("C2 · Review breakdown groupings")
        st.caption("Leaf labels are the TB's OWN (never AI). Where the TB carries a clean level hierarchy the "
                   "grouping IS the source structure; otherwise the AI proposes the grouping and you confirm any "
                   "AI-suggested caption (a LABEL, never a number). Accept to finalise — an unreviewed grouping "
                   "renders the note NOT FINAL.")
        if "mfs_bd_proposed" not in ss:                                    # derive ONCE (no per-rerun LLM call)
            ss.mfs_bd_proposed = {}
            for concept, mp, lb in eligible:
                tiers, path = derive_breakdown(store, concept, mp, lb, lvl_map, client=llm)
                ss.mfs_bd_proposed[concept] = {"tiers": tiers, "path": path}
        _PATH_NOTE = {"levels": "the TB level hierarchy (source)", "ai": "an AI proposal — confirm captions",
                      "identity": "each sub-account on its own line"}
        for concept, mp, lb in eligible:
            bd = ss.mfs_bd_proposed[concept]
            cap = store.get(concept).canonical_concept if store.get(concept) else concept
            st.markdown(f"**{cap}**  ·  grouping from: _{_PATH_NOTE.get(bd['path'], bd['path'])}_")
            for ti, t in enumerate(bd["tiers"]):
                if t.get("tier"):
                    st.markdown(f"&nbsp;&nbsp;**{t['tier']}**")
                for li, ln in enumerate(t["lines"]):
                    accts = ln["accounts"]
                    if len(accts) == 1:                                    # leaf line — TB label, NOT editable
                        st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;{lb.get(accts[0], accts[0])}")
                    elif ln.get("caption_source") in ("ai", "confirmed"):  # AI multi-leaf group → human confirms
                        new = st.text_input(f"AI-proposed caption — confirm ({len(accts)} sub-accounts)",
                                            value=ln.get("caption") or "", key=f"mfs_cap_{concept}_{ti}_{li}")
                        ln["caption"], ln["caption_source"] = new, "confirmed"
                    else:
                        st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;{ln.get('caption') or '(group)'}")
        if st.button("Accept breakdown groupings", key="mfs_accept_breakdowns"):
            ss.mfs_breakdowns = dict(ss.mfs_bd_proposed)
            ss.mfs_stored = {**ss.mfs_stored, "breakdowns": ss.mfs_breakdowns}
            st.rerun()
        if not ss.get("mfs_breakdowns"):
            st.info("⬆ Accept the groupings to finalise these notes (they render NOT FINAL until you do).")

    # ---- C3 · Confirm AI-proposed maturity pairings (ONLY when the deterministic matcher couldn't pair) ----
    _clean_pairs, _ambiguous = store.maturity_pairs()
    if _ambiguous and not ss.get("mfs_pairs_confirmed"):
        st.header("C3 · Confirm current/non-current pairings")
        st.caption("The deterministic matcher couldn't cleanly pair these current/non-current halves. The AI "
                   "proposes pairings from the LABELS (never amounts); confirm them — an unconfirmed pairing "
                   "stays flagged 'pairing ambiguous', never silently paired.")
        cands = []
        for amb in _ambiguous:
            for cid in amb.get("nc", []):
                cands.append((cid, store.get(cid).canonical_concept if store.get(cid) else cid, "nc"))
            for cid in amb.get("c", []):
                cands.append((cid, store.get(cid).canonical_concept if store.get(cid) else cid, "c"))
        if "mfs_pairing_proposed" not in ss:
            ss.mfs_pairing_proposed = propose_maturity_pairing(cands, client=llm)
        if ss.mfs_pairing_proposed:
            for nc, c in ss.mfs_pairing_proposed:
                ncl = store.get(nc).canonical_concept if store.get(nc) else nc
                cl = store.get(c).canonical_concept if store.get(c) else c
                st.markdown(f"&nbsp;&nbsp;AI-proposed: **{ncl}** (non-current) ↔ **{cl}** (current)")
            if st.button("Confirm maturity pairings", key="mfs_confirm_pairings"):
                ss.mfs_pairs_confirmed = [list(p) for p in ss.mfs_pairing_proposed]
                ss.mfs_stored = {**ss.mfs_stored, "maturity_pairs_confirmed": ss.mfs_pairs_confirmed}
                st.rerun()
        else:
            st.warning("The AI could not confidently pair these — they remain flagged 'pairing ambiguous'.")

    # ---- U5 · Register enrichment (optional) — DISCOVER which sheets are the registers, propose → confirm ----
    # Post-store, so the register-declaring concepts (seed mechanism:'register') are known. For each, propose which
    # REMAINING sheet is its register (Layer 0 scored name/header → Layer 1 headers-only AI); the user confirms or
    # picks '(none)'. Unmatched → the COARSE TB note (the existing register-presence pick). Reads ANY sheet from the
    # retained workbook bytes (the B2b second-sheet pattern). Only register-declaring concepts are offered a sheet.
    if is_upload and ss.get("mfs_upload_bytes") and register_decls(store):
        other_sheets = [s for s in (ss.get("mfs_sheets") or []) if s != ss.get("mfs_sheet")]
        if other_sheets and not ss.get("mfs_reg_done"):
            st.header("U5 · Register enrichment (optional) — point each note to its sub-ledger register")
            st.caption("The app PROPOSES which sheet is each register (by name/structure — never a hardcoded "
                       "sheet). Confirm, reassign, or '(none)' to keep the coarse TB note. The register's Σ is "
                       "reconciled to the face; attribute columns are carried verbatim.")

            def _hdr_of(sh):
                g = load_grid(io.BytesIO(ss.mfs_upload_bytes), filename=ss.mfs_upload_name, sheet=sh)
                return g[detect_header_row(g)]
            if "mfs_reg_proposal" not in ss:
                ss.mfs_reg_proposal = propose_register_sheets(store, ss.mfs_sheets, ss.mfs_sheet, _hdr_of,
                                                              client=_real_client())
            for cid, info in ss.mfs_reg_proposal.items():
                opts = ["(none)"] + other_sheets
                default = info["sheet"] if info["sheet"] in opts else "(none)"
                cc = st.columns([3, 4])
                cc[0].markdown(f"**{info['label']}** — _proposed: {info['sheet'] or '(none)'} "
                               f"(layer {info['layer']})_")
                cc[1].selectbox("register sheet", opts, index=opts.index(default), key=f"mfs_reg_{cid}",
                                label_visibility="collapsed")
            if st.button("Confirm registers", key="mfs_confirm_reg"):
                from ai_accountant.tb_ingest.register import read_register
                payloads = {}
                for cid in ss.mfs_reg_proposal:
                    pick = ss.get(f"mfs_reg_{cid}")
                    if pick and pick != "(none)":
                        g = load_grid(io.BytesIO(ss.mfs_upload_bytes), filename=ss.mfs_upload_name, sheet=pick)
                        payloads[cid] = read_register(g)
                        aud = payloads[cid]                                # show the detected tie column (transparency)
                        st.caption(f"`{pick}` → tie column **{aud['amount_current_header']}**, "
                                   f"{len(aud['rows'])} rows, {len(aud['columns'])} attribute column(s).")
                ss.mfs_reg_payloads = payloads
                ss.mfs_reg_done = True
            if not ss.get("mfs_reg_done"):
                st.stop()

    # ---- G3 · Unit (figures WITHHELD until set — R11) ----
    st.header("G3 · Presentation unit")
    unit = st.selectbox("Presentation unit — every figure (faces + notes) is WITHHELD until this is set",
                        UNITS, key="mfs_unit")
    unit_confirmed = unit != UNITS[0]

    # ---- G4 · Generate / derive + build notes ----
    st.header("G4 · Generate financial statements")
    payloads = (ss.get("mfs_reg_payloads", {}) if is_upload          # U5 — the confirmed register sheets (enriched notes)
                else _gl_payloads(ctx["fx"], llm, ss.get("mfs_split_confirmed", False)))
    period = ss.get("mfs_period") or (None, None)        # uploaded TB → real year labels; fixture → None fallback
    period = (_period_label(period[0]), _period_label(period[1]))   # show the bare YEAR (2024 / 2023), not the
    #                                                                 verbose header or the generic "Current/Prior"
    model = build_master_fs_export(store, ss.mfs_stored, bank=ctx["bank_label"], gl=payloads,
                                   unit=(unit if unit_confirmed else "SAR'000"),
                                   disclaimer=ctx["disclaimer"], notes_attempted=ctx["notes_attempted"],
                                   period_current=period[0], period_prior=period[1])
    ss.mfs_model = model

    # ---- S6a · Balance does not tie → DETERMINISTIC sign-correction diagnosis (a mis-signed contra) ----
    # Fired only when the SOFP is off AND there is exactly ONE clean candidate (a contra whose sign-flip cancels
    # the imbalance — never a guess; >1 or 0 → stays flagged). On confirm the per-TB correction is stored and the
    # engine REBUILDS + RE-PROVES (the balance-check clears only if it actually ties). Nothing auto-applies.
    if (is_upload and len(model.sign_candidates) == 1 and not ss.get("mfs_sign_corr_confirmed")
            and any(f[0] == "balance check" for f in model.findings)):
        cand = model.sign_candidates[0]
        bal = next((f for f in model.findings if f[0] == "balance check"), None)
        st.header("Balance does not tie  ·  sign-correction diagnosis")
        st.warning(bal[2] if bal else "The statement of financial position does not balance.")
        st.caption(f"Likely cause (deterministic, no AI): **{cand['label']}** is a contra stored with sign "
                   f"`{cand['stored_sign']}` while its roll-up formula applies `{cand['formula_sign']}` — a "
                   f"double-negation (the imbalance is {abs(cand['imbalance_multiple'] or 0)}× this line). Applying "
                   "treats it additively for THIS trial balance; the line still shows its stored sign; the engine "
                   "RE-PROVES the balance — it clears ONLY if it actually ties.")
        bcol, scol = st.columns(2)
        if bcol.button("✓ Apply the sign correction & re-check", key="mfs_confirm_signcorr", type="primary"):
            ss.mfs_stored = {**ss.mfs_stored, "sign_corrections": {cand["concept_id"]: cand["corrected_sign"]},
                             "sign_corrections_confirmed": True}
            ss.mfs_sign_corr_confirmed = True
            st.rerun()
        if scol.button("Skip — show the imbalance as-is (flagged)", key="mfs_skip_signcorr"):
            ss.mfs_sign_corr_confirmed = True
            st.rerun()
        st.stop()

    render_mfs_faces(model, unit_confirmed)

    # ---- G5 · CONFIRM split (management judgment) — building NEVER auto-confirms ----
    split_views = [v for v in model.note_views if v.status in
                   ("JUDGMENT_UNCONFIRMED", "JUDGMENT_CONFIRMED", "SPLIT_UNCONFIRMED", "BLOCKED")
                   and v.note_ref not in store.statement_keys()]
    if any("JUDGMENT" in v.status or v.status == "SPLIT_UNCONFIRMED" for v in model.note_views):
        st.header("G5 · Confirm maturity split  ·  management judgment")
        st.caption("A split renders UNCONFIRMED (amber) by default — building never auto-confirms. Confirm flips "
                   "the engine's provenance AI_ASSUMED → AI_CONFIRMED; a Case-B judgment keeps its persistent "
                   "marker even after confirming (it can never read as independently reconciled).")
        if st.button("Confirm split (management judgment)", key="mfs_confirm_split",
                     disabled=ss.get("mfs_split_confirmed", False)):
            ss.mfs_split_confirmed = True
            st.rerun()

    # ---- Notes (per declared note; status in WORDS) ----
    st.header("Notes")
    for nv in model.note_views:
        render_mfs_note(nv, unit_confirmed)

    # ---- G6 · Export (enabled only once the unit is confirmed) ----
    st.header("G6 · Export")
    if unit_confirmed:
        ecol, pcol = st.columns(2)
        ecol.download_button("Download Excel (.xlsx)", data=export_master_fs_excel_bytes(model),
                             file_name="master_fs.xlsx", key="mfs_dl_xlsx",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        pcol.download_button("Download PDF", data=export_master_fs_pdf_bytes(model),
                             file_name="master_fs.pdf", key="mfs_dl_pdf", mime="application/pdf")
    else:
        st.info("Set the presentation unit (G3) to enable export — figures are withheld until then (R11).")


def _restart_downstream(ss) -> None:
    """Clear everything past G0 so re-loading / re-parsing / re-confirming the archetype starts clean."""
    for k in ("mfs_seed_id", "mfs_mapping_confirmed", "mfs_stored", "mfs_split_confirmed", "mfs_model",
              "mfs_close_done", "mfs_close_declined", "mfs_breakdowns", "mfs_bd_proposed", "mfs_bs_split_confirmed",
              "mfs_sign_corr_confirmed", "mfs_pairing_proposed", "mfs_pairs_confirmed", "mfs_agenda_proposal",
              "mfs_agenda_confirmed", "mfs_reg_done", "mfs_reg_proposal", "mfs_reg_payloads"):
        ss.pop(k, None)
