"""Audit trail: trace every L1 number down to its source rows.

For each classification bucket, list the L3 holdings that compose it, and for each holding the
L4 transactions (purchases, sales, income, MtM, amortisation) that reference it — so any figure
on the financial statement can be drilled all the way back to the transactions behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ai_accountant.compute.cascade import CascadeResult

# (label, id column, amount column) for each L4 transaction table.
_TXN_SOURCES = [
    ("purchase", "Txn_ID", "Total_Cost_000"),
    ("sale/maturity", "Txn_ID", "Proceeds_000"),
    ("income", "Income_ID", "Net_000"),
    ("mark-to-market", "Reval_ID", "MtM_Change_000"),
    ("amortisation", "Amort_ID", "Monthly_Amort_000"),
]
_NAME_COLS = ("Security_Name", "Security", "Issuer")


@dataclass
class HoldingTrace:
    holding_id: str
    name: str
    bucket: str
    value: float
    transactions: list[dict] = field(default_factory=list)


@dataclass
class BucketTrace:
    bucket: str
    total: float
    holdings: list[HoldingTrace] = field(default_factory=list)


@dataclass
class AuditTrail:
    buckets: list[BucketTrace] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.buckets


def _txn_index(tables) -> dict[str, list[dict]]:
    """Map Holding_ID -> list of {type, ref, amount} across all L4 transaction tables."""
    index: dict[str, list[dict]] = {}
    for label, id_col, amt_col in _TXN_SOURCES:
        for t in tables:
            if not (t.has_columns("Holding_ID", amt_col)):
                continue
            for rec in t.records:
                hid = str(rec.get("Holding_ID", "")).strip()
                if not hid:
                    continue
                amt = pd.to_numeric(str(rec.get(amt_col, "")).replace(",", ""), errors="coerce")
                index.setdefault(hid, []).append({
                    "type": label,
                    "ref": str(rec.get(id_col, "")).strip(),
                    "amount": float(amt) if pd.notna(amt) else 0.0,
                })
    return index


def build_audit_trail(tables, cascade: CascadeResult) -> AuditTrail:
    """Build bucket -> holdings -> transactions trace from the cascade's sub-ledger + L4."""
    l3 = cascade.l3_holdings
    if l3 is None or l3.empty or "Holding_ID" not in l3.columns or "Bucket" not in l3.columns:
        return AuditTrail()

    name_col = next((c for c in _NAME_COLS if c in l3.columns), None)
    index = _txn_index(tables)

    buckets: list[BucketTrace] = []
    for bucket in ("FVTPL", "FVOCI", "Amortised Cost"):
        rows = l3[l3["Bucket"] == bucket]
        if rows.empty:
            continue
        holdings = []
        for _, r in rows.iterrows():
            hid = str(r["Holding_ID"]).strip()
            holdings.append(HoldingTrace(
                holding_id=hid,
                name=str(r[name_col]) if name_col else "",
                bucket=bucket,
                value=float(pd.to_numeric(r.get("Carrying_Value_000", 0), errors="coerce") or 0),
                transactions=index.get(hid, []),
            ))
        total = float(sum(h.value for h in holdings))
        buckets.append(BucketTrace(bucket=bucket, total=total, holdings=holdings))
    return AuditTrail(buckets=buckets)
