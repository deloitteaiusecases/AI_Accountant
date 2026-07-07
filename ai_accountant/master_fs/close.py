"""Result-to-retained close — DETECT + CONFIRM, never automatic (the most dangerous TB-ingest step).

Closing the current-year comprehensive result into retained earnings is the one operation that can
BALANCE WHILE WRONG: if a TB is already post-close and the engine ALSO adds the result, equity is
overstated by exactly the result. So the engine DETECTS pre/post-close and SURFACES the evidence; a
human CONFIRMS; the close runs ONLY on a confirmed pre-close. Seed-declared (engine.result_close), no
literal here.

Double-count prevention (exact):
  * "the result" = the DERIVED `result_total` (the SCI total `tc_total_ci`), which already includes net
    profit ONCE via the carry-leaf (derive.apply_carries); no line is summed twice.
  * OCI lives in the comprehensive-income statement, never on a BS equity leaf, so the close does not
    also inflate other reserves.
  * the close writes a SINGLE synthetic, audited tb-row into `retained` (source rows untouched), runs
    once, gated on confirmed pre-close.
  * post-close / unconfirmed / ambiguous → NO close. (Secondary catch: wrongly closing a clean
    post-close TB then fails the SOFP balance check by exactly the result — surfaced, never auto-fixed.)
"""
from __future__ import annotations

from dataclasses import dataclass

_TOL = 0.5                                                  # SAR'000 — derived sums are exact; guards float noise


@dataclass
class CloseProposal:
    verdict: str                      # not_declared | pre_close | post_close | ambiguous
    declared: bool
    retained_concept: "str | None" = None
    result_total_current: float = 0.0
    result_total_prior: "float | None" = None
    imbalance_current: float = 0.0
    opening_retained_current: float = 0.0
    finding: str = ""

    @property
    def closing_retained_current(self) -> float:
        return round(self.opening_retained_current + self.result_total_current, 2)


def _line(model, concept_id):
    for lines in model.statements.values():
        for l in lines:
            if l.concept_id == concept_id:
                return l
    return None


def detect_close_state(store, model) -> CloseProposal:
    """Read the built (pre-close) faces and decide pre/post/ambiguous, surfacing the evidence numbers."""
    rc = store.meta.get("result_close")
    if not rc:
        return CloseProposal(verdict="not_declared", declared=False)
    bc = store.balance_check() or {}
    ta, toe = _line(model, bc.get("assets_total")), _line(model, bc.get("liab_equity_total"))
    res, ret = _line(model, rc.get("result_total")), _line(model, rc.get("retained_concept"))
    if ta is None or toe is None or res is None or ret is None:
        return CloseProposal(verdict="ambiguous", declared=True, retained_concept=rc.get("retained_concept"),
                             finding="cannot locate balance/result/retained concepts to assess the close")
    imbalance = round((ta.current or 0.0) - (toe.current or 0.0), 2)
    result_cur = round(res.current or 0.0, 2)
    result_pri = None if res.prior is None else round(res.prior, 2)
    open_ret = round(ret.current or 0.0, 2)
    base = dict(declared=True, retained_concept=rc.get("retained_concept"),
                result_total_current=result_cur, result_total_prior=result_pri,
                imbalance_current=imbalance, opening_retained_current=open_ret)
    if abs(imbalance) < _TOL:
        return CloseProposal(verdict="post_close", finding=(
            f"SOFP already balances (imbalance {imbalance:,.0f}). The current-year result "
            f"({result_cur:,.0f}) is already in retained earnings — no close needed."), **base)
    if abs(result_cur) >= _TOL and abs(imbalance - result_cur) < _TOL:
        return CloseProposal(verdict="pre_close", finding=(
            f"PRE-CLOSE detected: SOFP is off by {imbalance:,.0f}, which equals the current-year result "
            f"{result_cur:,.0f}. Closing it into retained: opening {open_ret:,.0f} + result {result_cur:,.0f} "
            f"= closing {round(open_ret + result_cur):,.0f}."), **base)
    return CloseProposal(verdict="ambiguous", finding=(
        f"SOFP is off by {imbalance:,.0f}, which does NOT equal the current-year result {result_cur:,.0f} — "
        f"the imbalance is something else. No close; investigate before generating."), **base)


_CLOSE_ACCOUNT = "__result_close__"


def apply_retained_close(stored: dict, proposal: CloseProposal, *, approver="", at="", audit=None) -> dict:
    """Write the single synthetic, audited close row into retained (current + prior). Call ONLY on a
    confirmed pre_close. Source rows are untouched; the engine sums this row into the retained concept."""
    if proposal.verdict != "pre_close" or not proposal.retained_concept:
        raise ValueError("apply_retained_close requires a confirmed pre_close proposal")
    out = dict(stored)
    out["tb"] = list(stored.get("tb", [])) + [{
        "account": _CLOSE_ACCOUNT, "label": "Current-year result closed to retained earnings",
        "current": proposal.result_total_current, "prior": proposal.result_total_prior}]
    out["mappings"] = list(stored.get("mappings", [])) + [{
        "account": _CLOSE_ACCOUNT, "concept_id": proposal.retained_concept,
        "client_label": "Current-year result closed to retained earnings", "provenance": "result_close"}]
    if audit is not None:
        from ai_accountant.master_fs.model import AuditRecord
        audit.log(AuditRecord(action="close_result_to_retained", target=proposal.retained_concept,
                              client_id=stored.get("client", ""), provenance="result_close", confidence="",
                              approver=approver, at=at,
                              detail=(f"opening {proposal.opening_retained_current:,.0f} + result "
                                      f"{proposal.result_total_current:,.0f} = closing "
                                      f"{proposal.closing_retained_current:,.0f}")))
    return out
