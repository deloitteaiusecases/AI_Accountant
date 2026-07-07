"""Slice SL-1 Risk-1: the dual-balance / Adjustment column layout must not silently pick the wrong column.

The real AlJazira TB has FOUR "Balance '000 SAR (..)" headers (raw + adjusted, two years) + two "Adjustment"
columns. The OLD ranking matched all four as amounts and ranked by year — picking the TWO 2025 columns
(raw AND adjusted) as current/prior: both 2025, a silent wrong-prior. The hardening:
  * recognizes "Adjustment" columns (role 'adjustment'), never reads them as the amount;
  * prefers the ADJUSTED balance — the raw balance immediately before an adjustment is demoted (visible, not
    dropped);
  * when two amount columns carry NO year to disambiguate, marks `period_ambiguous` (current/prior is a
    positional guess — a swap would still balance, so the build forces an explicit values-shown confirm);
  * `column_amount_audit` exposes each chosen column's SUM so a wrong/swapped pick is VISIBLE before it ties.

    python tests/test_sub_ledger_columns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.tb_ingest.columns import (column_amount_audit, confirm_column_roles,   # noqa: E402
                                             heuristic_column_roles)

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "Draft Data for working.xlsx"


def _roles(headers, rows):
    return confirm_column_roles(heuristic_column_roles(headers, rows))


# ============================================================ the real dual-balance/adjustment layout
def test_real_tb_demotes_raw_prefers_adjusted_and_picks_by_year():
    if not REAL.exists():
        print("[skip] real TB absent"); return
    from ai_accountant.tb_ingest.grid import load_grid
    from ai_accountant.tb_ingest.parse import detect_header_row
    grid = load_grid(str(REAL), sheet="Trial Balance")
    hr = detect_header_row(grid)
    schema = _roles(grid[hr], grid[hr + 1:hr + 5])
    roles = {c.index: c.role for c in schema.roles}
    assert roles[2] == "adjustment" and roles[5] == "adjustment"        # the two Adjustment columns recognised
    assert roles[1] == "ignore" and roles[4] == "ignore"               # raw balances demoted (superseded)
    assert schema.current_index == 3 and schema.prior_index == 6        # the ADJUSTED balances, by year
    cur = next(c for c in schema.roles if c.index == 3)
    pri = next(c for c in schema.roles if c.index == 6)
    assert cur.year == 2025 and pri.year == 2024                        # current=2025, prior=2024 (year-disambiguated)
    assert schema.period_ambiguous is False                            # the year disambiguates → not a guess
    aud = column_amount_audit(schema, grid, header_row=hr)
    assert aud["current"]["sum"] != aud["prior"]["sum"]                # distinct → a swap would be visible
    assert len(aud["adjustments"]) == 2


# ============================================================ the dangerous case: identical headers, NO year
def test_identical_headers_no_year_flags_period_ambiguous():
    # two amount columns, identical headers, no year → current/prior is a positional guess → flagged
    headers = ["GL", "Balance", "Adjustment", "Balance", "Balance", "Adjustment", "Balance", "L2"]
    rows = [["1", "100", "0", "100", "90", "0", "90", "Cash"],
            ["2", "200", "0", "200", "180", "0", "180", "Loans"]]
    schema = _roles(headers, rows)
    assert schema.period_ambiguous is True                            # cannot disambiguate by year → flagged
    cur = next(c for c in schema.roles if c.role == "amount_current")
    assert cur.confidence == "low" and "PERIOD UNCONFIRMED" in cur.evidence
    assert [c.index for c in schema.roles if c.role == "adjustment"] == [2, 5]
    assert schema.current_index == 3 and schema.prior_index == 6      # adjusted balances (raw 1,4 demoted)
    assert {c.index for c in schema.roles if c.role == "ignore"} >= {1, 4}


def test_swap_visible_in_audit_distinct_sums():
    headers = ["GL", "Balance", "Adjustment", "Balance", "Balance", "Adjustment", "Balance"]
    grid = [headers,
            ["1", "100", "0", "100", "90", "0", "90"],
            ["2", "200", "0", "200", "180", "0", "180"]]
    schema = _roles(headers, grid[1:])
    aud = column_amount_audit(schema, grid, header_row=0)
    assert aud["current"]["sum"] == 300.0 and aud["prior"]["sum"] == 270.0   # the human SEES 300 vs 270
    assert aud["period_ambiguous"] is True and aud["swap_safe"] is False     # swap NOT arithmetically catchable


# ============================================================ regression: a normal 2-col year TB is unchanged
def test_normal_two_column_year_tb_unchanged():
    headers = ["Account", "Label", "2024", "2023"]
    rows = [["1000", "Cash", "500", "450"], ["2000", "Loans", "300", "280"]]
    schema = _roles(headers, rows)
    assert schema.current_index == 2 and schema.prior_index == 3       # latest year = current (unchanged)
    assert schema.period_ambiguous is False                           # years present → not ambiguous
    assert not [c for c in schema.roles if c.role == "adjustment"]     # no adjustment columns invented


def test_single_amount_column_not_ambiguous():
    headers = ["Account", "Amount"]
    schema = _roles(headers, [["1000", "500"]])
    assert schema.current_index == 1 and schema.prior_index is None
    assert schema.period_ambiguous is False                           # no prior → no swap possible


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[pass] {name}")
            except AssertionError as exc:
                failures += 1
                print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                import traceback
                failures += 1
                print(f"[ERROR] {name}: {exc}")
                traceback.print_exc()
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
