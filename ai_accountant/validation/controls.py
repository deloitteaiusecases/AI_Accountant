"""Internal accounting controls — confidence WITHOUT an answer key.

In production the user uploads L4 only and we *generate* L1, so there is no expected L1 to
reconcile against. Trust then comes from the same internal controls a real accountant uses to
close the books: completeness, double-entry integrity, sub-ledger↔GL agreement, and anomaly
checks. The output is a CONFIDENCE report ("N controls passed, M to review"), not pass/fail
against a known answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from ai_accountant.compute.cascade import CascadeResult
from ai_accountant.notes.registry import DEFAULT_NOTE as _NOTE

# (amount column, id column, label) for transaction tables whose holdings MUST exist in the
# sub-ledger. Sales/maturities are excluded from the orphan check — they reference disposed
# positions that are intentionally gone from L3.
_TXN_SOURCES = [
    ("Total_Cost_000", "Txn_ID", "purchase"),
    ("Net_000", "Income_ID", "income"),
    ("MtM_Change_000", "Reval_ID", "mark-to-market"),
    ("Monthly_Amort_000", "Amort_ID", "amortisation"),
]
_SALES_SOURCE = ("Proceeds_000", "Txn_ID", "sale/maturity")
# GL control accounts → bucket (for sub-ledger ↔ GL tie-out) — from the active note definition.
_GL_ACCOUNTS = _NOTE.gl_accounts


@dataclass
class ControlResult:
    name: str
    status: str            # "pass" | "warn" | "fail"
    detail: str
    items: list = field(default_factory=list)


@dataclass
class ConfidenceReport:
    controls: list[ControlResult] = field(default_factory=list)

    @property
    def level(self) -> str:
        if not self.controls:
            return "Unknown"
        if any(c.status == "fail" for c in self.controls):
            return "Low"
        if any(c.status == "warn" for c in self.controls):
            return "Medium"
        return "High"

    @property
    def passed(self) -> int:
        return sum(1 for c in self.controls if c.status == "pass")

    @property
    def flagged(self) -> int:
        return sum(1 for c in self.controls if c.status != "pass")


def _num(x) -> float:
    s = str(x).strip().replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find(tables, *cols):
    for t in tables:
        if t.has_columns(*cols):
            return t
    return None


def run_controls(tables, cascade: CascadeResult) -> ConfidenceReport:
    """Run the internal controls and return a confidence report."""
    controls: list[ControlResult] = []
    l3 = cascade.l3_holdings
    has_l3 = l3 is not None and not l3.empty and "Holding_ID" in l3.columns
    holding_ids = {str(h).strip() for h in l3["Holding_ID"]} if has_l3 else set()

    # 1) Completeness — orphan transactions (purchase/income/MtM/amortisation).
    if holding_ids:
        orphans = []
        for amt_col, id_col, label in _TXN_SOURCES:
            t = _find(tables, "Holding_ID", amt_col)
            if t is None:
                continue
            for rec in t.records:
                hid = str(rec.get("Holding_ID", "")).strip()
                if hid and hid not in holding_ids:
                    orphans.append({
                        "holding": hid, "transaction": rec.get(id_col, ""), "type": label,
                        "reason": (f"This {label} transaction refers to holding '{hid}', which is "
                                   "not in the sub-ledger — usually a prior-period (opening) "
                                   "position that wasn't uploaded, or a mistyped Holding_ID."),
                    })
        controls.append(ControlResult(
            "Completeness — orphan transactions",
            "pass" if not orphans else "warn",
            ("Every purchase/income/MtM/amortisation transaction maps to a known holding."
             if not orphans else
             f"{len(orphans)} transaction(s) reference a holding not in the sub-ledger "
             "(expected when only L4 is uploaded without opening positions)."),
            orphans[:25],
        ))

    # 2) Completeness — classification coverage.
    if has_l3 and "Classification" in l3.columns:
        name_col = next((c for c in ("Security_Name", "Security", "Issuer") if c in l3.columns), None)
        missing = []
        for _, r in l3.iterrows():
            if not str(r.get("Classification", "")).strip():
                missing.append({
                    "holding": str(r.get("Holding_ID", "")),
                    "security": str(r.get(name_col, "")) if name_col else "",
                    "reason": ("No classification was stated, and neither a policy rule nor IFRS 9 "
                               "inference matched the security description — it would be excluded "
                               "from the bucket totals."),
                })
        controls.append(ControlResult(
            "Completeness — classification coverage",
            "pass" if not missing else "warn",
            "All positions are classified." if not missing
            else f"{len(missing)} position(s) lack a classification.",
            missing[:25],
        ))

    # 3) Double-entry integrity (GL journals).
    je = _find(tables, "JE_ID", "GL_Debit", "GL_Credit") or _find(tables, "GL_Debit", "GL_Credit", "Amount_000")
    if je is not None and "Amount_000" in je.headers:
        malformed = [{
            "journal": rec.get("JE_ID", ""),
            "debit": rec.get("GL_Debit", ""), "credit": rec.get("GL_Credit", ""),
            "reason": "Missing a debit and/or credit account — not a valid balanced double-entry.",
        } for rec in je.records
            if not str(rec.get("GL_Debit", "")).strip() or not str(rec.get("GL_Credit", "")).strip()]
        total = sum(_num(rec.get("Amount_000", 0)) for rec in je.records)
        controls.append(ControlResult(
            "Double-entry integrity (GL journals)",
            "pass" if not malformed else "warn",
            (f"{len(je.records)} journal entries; debits = credits by construction "
             f"(total {total:,.0f} SAR '000). "
             + ("All rows well-formed." if not malformed
                else f"{len(malformed)} row(s) missing an account.")),
            malformed[:25],
        ))

        # 4) Sub-ledger ↔ GL postings (informational tie-out).
        net = {b: 0.0 for b in _GL_ACCOUNTS.values()}
        for rec in je.records:
            amt = _num(rec.get("Amount_000", 0))
            d, c = str(rec.get("GL_Debit", "")).strip(), str(rec.get("GL_Credit", "")).strip()
            if d in _GL_ACCOUNTS:
                net[_GL_ACCOUNTS[d]] += amt
            if c in _GL_ACCOUNTS:
                net[_GL_ACCOUNTS[c]] -= amt
        detail = "; ".join(f"{b}: net {v:,.0f}" for b, v in net.items())
        controls.append(ControlResult(
            "Sub-ledger ↔ GL postings",
            "pass" if any(net.values()) else "warn",
            f"Net GL postings to investment control accounts captured — {detail}.",
            [],
        ))

    # 5) No duplicate transaction IDs.
    dups = []
    for amt_col, id_col, label in _TXN_SOURCES + [_SALES_SOURCE]:
        t = _find(tables, id_col, amt_col)
        if t is None:
            continue
        seen: set[str] = set()
        for rec in t.records:
            rid = str(rec.get(id_col, "")).strip()
            if rid and rid in seen:
                dups.append({"id": rid, "type": label,
                             "reason": "This transaction ID appears more than once — possible "
                                       "double-count or a re-used reference."})
            seen.add(rid)
    controls.append(ControlResult(
        "No duplicate transaction IDs",
        "pass" if not dups else "warn",
        "All transaction IDs are unique." if not dups else f"{len(dups)} duplicate ID(s) found.",
        dups[:25],
    ))

    # 6) No negative carrying values.
    if has_l3 and "Carrying_Value_000" in l3.columns:
        cv = pd.to_numeric(l3["Carrying_Value_000"], errors="coerce")
        negs = [{"holding": str(h), "carrying_value": float(v),
                 "reason": "Negative carrying value is invalid for an investment position — "
                           "likely a data error or an over-applied disposal/write-down."}
                for h, v in zip(l3["Holding_ID"], cv) if pd.notna(v) and v < 0]
        controls.append(ControlResult(
            "No negative carrying values",
            "pass" if not negs else "warn",
            "All carrying values are non-negative." if not negs
            else f"{len(negs)} holding(s) have a negative carrying value.",
            negs[:25],
        ))

    return ConfidenceReport(controls)


def narrate_confidence(report: ConfidenceReport, api_key: str) -> str:
    """Optional plain-English summary of the ALREADY-EVALUATED controls (key-gated).

    Strictly a presentation layer: the LLM only narrates the deterministic results — it never
    re-judges a status, invents controls, or does arithmetic. Best-effort: returns "" on failure.
    """
    from ai_accountant.llm.client import LLMClient

    payload = [{"name": c.name, "status": c.status, "detail": c.detail,
                "flagged_items": len(c.items)} for c in report.controls]
    prompt = f"""
Internal accounting controls for a Note 5 (Investments) figure set have ALREADY been evaluated
deterministically. Summarize them in plain English for a finance user.

Hard rules (do not break):
- Do NOT change, re-judge, or contradict any control's status.
- Do NOT invent numbers, securities, or controls beyond those listed.
- Do NOT perform any calculation.
- 2–4 short sentences: state the overall confidence ({report.level}), what broadly passed, and
  for any 'warn'/'fail' control explain in lay terms what it means and what to review.

Overall confidence: {report.level}
Controls (already evaluated, do not alter):
{json.dumps(payload, indent=2)}

Return strictly JSON: {{"summary": "<plain-English summary>"}}
"""
    try:
        out = LLMClient(api_key=api_key).complete_json(prompt)
        return str(out.get("summary", "")).strip()
    except Exception:  # noqa: BLE001 - narration is optional, never blocks
        return ""


def explain_flagged_items(report: ConfidenceReport, api_key: str, max_items: int = 60) -> None:
    """Replace each flagged item's `reason` with an LLM explanation (in place, best-effort).

    Why LLM here: the explanation generalizes across data types / future notes, whereas a fixed
    string can't. The CONTROL's verdict stays deterministic — the LLM only explains an
    already-decided finding, grounded in the item's facts, and never re-judges it. One batched
    call for all flagged items. If no key / failure, the deterministic `reason` is left intact.
    """
    from ai_accountant.llm.client import LLMClient

    payload, refs = [], []
    for ci, c in enumerate(report.controls):
        for ii, item in enumerate(c.items):
            if len(payload) >= max_items:
                break
            payload.append({
                "id": len(payload),
                "control": c.name,
                "finding": {k: v for k, v in item.items() if k != "reason"},
            })
            refs.append((ci, ii))
    if not payload:
        return

    prompt = f"""
Internal accounting controls have ALREADY flagged the items below as issues (do not re-judge or
say any item is fine). For EACH item, write ONE short plain-English sentence explaining why it was
flagged and what it usually indicates, for a finance user.

Rules:
- Explain only — never reverse or soften the finding.
- Do not invent identifiers, amounts, securities, or facts beyond the finding provided.
- One clear sentence per item.

Findings:
{json.dumps(payload, indent=2, default=str)}

Return strictly JSON: {{"explanations": {{"<id>": "<one-sentence explanation>"}}}}
"""
    try:
        out = LLMClient(api_key=api_key).complete_json(prompt)
        explanations = out.get("explanations", {})
        for idx, (ci, ii) in enumerate(refs):
            text = explanations.get(str(idx))
            if text:
                report.controls[ci].items[ii]["reason"] = str(text).strip()
    except Exception:  # noqa: BLE001 - explanation is optional, never blocks
        return
