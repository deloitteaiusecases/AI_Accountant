"""AI mapping proposers the seed engine uses — relocated GL-free under master_fs (Slice 3).

The AI proposes a LABEL→line mapping (and a contra flag), never a figure: the model is shown only account
labels + a candidate vocabulary and returns a verdict + its evidence; a proposal stays unapplied until a
human confirms it. The seed path uses exactly three symbols from the former `fs_notes.ai_propose`:
`FaceMappingProposal`, `propose_seed_mapping` (+ its `SeedMappingProposal`), and `ConfirmedPPEAccount`.
The `confirm_seed_mapping` helper (the only piece that depended on the GL `hierarchy` package) was NOT on
the seed path and is gone.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_accountant.llm.client import LLMClient


@dataclass
class FaceMappingProposal:
    code: str
    label: str
    line: str               # a candidate caption, or "unsure"
    confidence: str
    evidence: str

    @property
    def is_confident(self) -> bool:
        return self.line.lower() != "unsure" and self.confidence != "low"


@dataclass
class ConfirmedPPEAccount:
    """A human-confirmed movement-note structural fact (R8): account → (asset_class, role), stored and
    then re-applied deterministically. Identification is judgment (AI proposes, human confirms); the
    netting that consumes this — cost + accumulated contra → NBV — is arithmetic and stays deterministic.
    `role` is the mechanism role: 'cost' | 'accumulated_contra'."""
    asset_class: str
    role: str                       # "cost" | "accumulated_contra"
    approver: str
    approved_at: str


_SEED_SYSTEM = (
    "You map an accounting account to where it belongs in the financial statements, from its LABEL — "
    "never its code (codes can be renumbered, foreign, or absent) and never any amount. For each "
    "account return: the note/face line it belongs to (chosen from the candidate list, verbatim, or "
    "'unsure'); whether it is a CONTRA account (an allowance / impairment / accumulated-depreciation "
    "that offsets an asset) — contra accounts get classification 'contra-asset (...)' and natural sign "
    "'Cr'; otherwise classification like 'financial asset' / 'current asset' and sign 'Dr'; and a short "
    "sub_class hint if obvious. Rules:\n"
    "1. Read the LABEL. An 'ECL allowance' / 'impairment' / 'accumulated depreciation' is a CONTRA.\n"
    "2. If the label is too vague to place confidently, return note_ref='unsure', confidence='low' — "
    "never force a mapping.\n"
    "3. Cite the label words that drove the decision.\n"
    "4. Output EXACTLY one JSON object: {\"proposals\":[{\"account\":..,\"note_ref\":..,"
    "\"face_caption\":..,\"classification\":..,\"sign\":\"Dr|Cr\",\"sub_class\":..,"
    "\"confidence\":\"high|medium|low\",\"evidence\":..}]}"
)


@dataclass
class SeedMappingProposal:
    account: str
    note_ref: str               # a candidate note/face line, or "unsure"
    face_caption: str
    classification: str
    sign: str
    sub_class: str
    confidence: str
    evidence: str

    @property
    def is_confident(self) -> bool:
        return self.note_ref.strip().lower() not in ("", "unsure") and self.confidence != "low"


def propose_seed_mapping(items: list, candidates: list, client: "LLMClient | None" = None) -> list:
    """items: (account, label). candidates: the note/face-line vocabulary. Propose where each account
    belongs + whether it is a contra, from the LABEL. 'unsure' is valid; figures are never sent. Same
    propose/confirm/store shape as the other proposers."""
    client = client or LLMClient()
    cand = "\n".join(f"- {c}" for c in candidates)
    rows = "\n".join(f"{a}\t{lbl}" for a, lbl in items)
    prompt = (f"Candidate notes / face lines (verbatim, or 'unsure'):\n{cand}\n\n"
              f"Accounts (account <tab> label):\n{rows}")
    raw = client.complete_json(prompt, system=_SEED_SYSTEM)
    by_acct = {str(p.get("account", "")).strip(): p for p in raw.get("proposals", []) if isinstance(p, dict)}
    out: list = []
    for a, _lbl in items:
        p = by_acct.get(a, {})
        out.append(SeedMappingProposal(
            account=a, note_ref=str(p.get("note_ref", "unsure")),
            face_caption=str(p.get("face_caption", "")), classification=str(p.get("classification", "")),
            sign=str(p.get("sign", "Dr")), sub_class=str(p.get("sub_class", "")),
            confidence=str(p.get("confidence", "low")), evidence=str(p.get("evidence", ""))))
    return out
