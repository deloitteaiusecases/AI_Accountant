"""TB-presentation sign — RECORD + CONFIRM (a silent-failure firewall).

A raw trial balance stores one side as credits (negative): assets debit-positive, but liabilities /
equity / income credit-negative (and expenses, grouped under the result section, debit-positive). The
master-FS seed expects PRESENTATION sign (assets +, liab +, equity +, income +, expense −), so the
credit sides must be flipped. The AI/heuristic PROPOSES which sections are credit-stored (from the
per-section sign pattern, never summing for a figure), the human CONFIRMS, code flips deterministically.

WHY THE CONFIRM IS THE GUARD: a wrong whole-side flip balances while inverted — assets vs a
sign-flipped liabilities+equity can tie at zero while upside-down — so the balance check CANNOT catch
it. The human confirm is the only guard. Recorded with provenance, like every other confirmed input.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_accountant.master_fs.model import AI_ASSUMED, AI_CONFIRMED


@dataclass
class SectionSign:
    section: str
    side: str                 # asset | liability | equity | income | result | unknown (a hint, by keyword)
    net_current: float        # the section's net sign signal (NOT a presented figure)
    proposed: str             # 'flip' | 'as_is'
    evidence: str


@dataclass
class TBSignProposal:
    sections: list = field(default_factory=list)          # [SectionSign]

    @property
    def any_flip(self) -> bool:
        return any(s.proposed == "flip" for s in self.sections)


@dataclass
class TBSignConvention:
    by_section: dict = field(default_factory=dict)        # section -> 'flip' | 'as_is'
    provenance: str = AI_ASSUMED
    approver: str = ""
    at: str = ""


def _side_of(section: str) -> str:
    s = str(section).lower()
    if "asset" in s:
        return "asset"
    if "liab" in s:
        return "liability"
    # EXPENSE is checked BEFORE income: its presentation TARGET sign is NEGATIVE (the engine's net-lines add
    # expenses with '+' on already-negative values), the OPPOSITE of income — so they cannot share one rule.
    if "expense" in s or "cost of" in s:
        return "expense"
    if "current year" in s or "current-year" in s or "p&l" in s or "profit" in s or "oci" in s \
            or "income" in s or "revenue" in s or "comprehensive" in s:
        return "income"
    if "equity" in s or "reserve" in s or "capital" in s or "retained" in s:
        return "equity"
    return "unknown"


def propose_tb_sign(tb_rows, *, client=None) -> TBSignProposal:
    """Per-L0-section proposal: a section whose amounts net NEGATIVE is credit-stored → propose 'flip';
    a section netting positive is already presentation sign → 'as_is'. Assets are kept as-is. This reads
    the SIGN PATTERN (a structural signal), it does not compute or present any figure. `client` is the
    interface for an LLM second opinion on ambiguous sections; the heuristic is the offline path."""
    by_section: dict = {}
    for r in tb_rows:
        sec = r.get("section", "") or "(unsectioned)"
        by_section.setdefault(sec, 0.0)
        by_section[sec] += float(r.get("current") or 0.0)
    sections = []
    for sec, net in by_section.items():
        side = _side_of(sec)
        # Propose against each side's TARGET presentation sign (assets +, liab +, equity +, INCOME +,
        # EXPENSE −) by reading the section's stored net sign — flip iff stored OPPOSITE to the target.
        # Data-driven, never a blanket flip: the same rule keeps a NEGATIVE-stored expense as-is and flips a
        # POSITIVE-stored expense (the two-convention safety — a positive- and a negative-expense TB both right).
        if side == "asset":
            proposed, ev = "as_is", "asset section — debit-positive (target +), kept as-is"
        elif side == "expense":                            # TARGET NEGATIVE — flip a positive-stored (debit) section
            if net > 0:
                proposed, ev = "flip", "expense section nets POSITIVE (debit-stored) → flip to presentation-NEGATIVE"
            else:
                proposed, ev = "as_is", "expense section already nets negative (presentation sign), kept as-is"
        elif net < 0:                                      # income / liability / equity — TARGET POSITIVE
            proposed, ev = "flip", f"{side} section nets negative → credit-stored, flip to presentation-positive"
        else:
            proposed, ev = "as_is", f"{side} section nets positive → already presentation sign (target +)"
        sections.append(SectionSign(section=sec, side=side, net_current=round(net, 2),
                                    proposed=proposed, evidence=ev))
    return TBSignProposal(sections=sections)


def confirm_tb_sign(proposal: TBSignProposal, decisions=None, *, approver="", at="", audit=None) -> TBSignConvention:
    """Apply per-section human overrides (section → 'flip'|'as_is') and record the convention with
    provenance. The confirm is the firewall — a wrong flip balances while inverted."""
    decisions = decisions or {}
    by_section = {s.section: decisions.get(s.section, s.proposed) for s in proposal.sections}
    conv = TBSignConvention(by_section=by_section, provenance=AI_CONFIRMED, approver=approver, at=at)
    if audit is not None:
        from ai_accountant.master_fs.model import AuditRecord
        audit.log(AuditRecord(action="record_tb_sign", target="tb_presentation_sign", client_id="",
                              provenance=AI_CONFIRMED, confidence="", approver=approver, at=at,
                              detail=f"flips={[s for s, v in by_section.items() if v == 'flip']}"))
    return conv


def apply_tb_sign(tb_rows, conv: TBSignConvention) -> list:
    """Deterministically flip each row's amounts where its section is confirmed credit-stored. Code owns
    the number; the AI only proposed the classification."""
    out = []
    for r in tb_rows:
        flip = conv.by_section.get(r.get("section", "") or "(unsectioned)") == "flip"
        s = -1.0 if flip else 1.0
        new = dict(r)
        new["current"] = round(s * float(r.get("current") or 0.0), 2)
        new["prior"] = None if r.get("prior") is None else round(s * float(r.get("prior")), 2)
        out.append(new)
    return out
