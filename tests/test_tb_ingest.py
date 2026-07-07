"""Slice I1 unit guards: the TB parsing front-end is structure-agnostic and surfaces, never drops.

Proves the column-role proposer keys off MEANING (not position) — a reshaped xlsx-style grid AND a CSV
parse identically; two periods are both extracted; a row with an amount but no account is FLAGGED into
bad_rows, never dropped; and the TB-presentation sign is proposed + flipped deterministically.

    python tests/test_tb_ingest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_accountant.tb_ingest import (apply_tb_sign, confirm_column_roles, confirm_tb_sign,  # noqa: E402
                                     detect_header_row, load_grid, parse_tb, propose_column_roles,
                                     propose_tb_sign, to_engine_inputs)

ROOT = Path(__file__).resolve().parent.parent


def _roles(grid):
    hdr = detect_header_row(grid)
    schema = confirm_column_roles(propose_column_roles(grid[hdr], grid[hdr + 1:hdr + 6], client=None))
    return hdr, schema


def test_column_proposer_is_structure_agnostic_across_layouts():
    # layout A — label first, a level column, a single current period, oddly-named amount header
    a = [["Particulars", "Level 1", "Balance 31-12-2024 (SAR'000)"],
         ["Property and equipment", "Non-Current Assets", 18851032],
         ["Cash and cash equivalents", "Current Assets", 1399542]]
    _h, sa = _roles(a)
    assert sa.label_index == 0 and sa.level_indices == [1] and sa.current_index == 2
    assert sa.prior_index is None and not sa.missing_required    # single period → no prior column

    # layout B — different ORDER and different header words; two periods; code column
    b = [["FY2023 (SAR000)", "GL Code", "Account Name", "FY2024 (SAR000)"],
         [16762681, "1001", "Revenue", 18206447]]
    _h, sb = _roles(b)
    assert sb.code_index == 1 and sb.label_index == 2
    assert sb.current_index == 3 and sb.prior_index == 0          # latest year = current, by header year


def test_csv_normalises_to_the_same_grid_and_parses():
    csv_text = "Account Name,L0,2024 (SAR'000)\nRevenue,Income,18206447\nCash and cash equivalents,Assets,1399542\n"
    p = ROOT / "tests" / "fixtures" / "tb_upload" / "_tmp_reshaped.csv"
    p.write_text(csv_text, encoding="utf-8")
    try:
        grid = load_grid(str(p))
        hdr, schema = _roles(grid)
        assert schema.label_index == 0 and schema.level_indices == [1] and schema.current_index == 2
        parsed = parse_tb(grid, schema, header_row=hdr)
        labels = {r.label for r in parsed.rows}
        assert "Revenue" in labels and "Cash and cash equivalents" in labels
    finally:
        p.unlink(missing_ok=True)


def test_two_periods_both_extracted():
    grid = [["Account", "2024 (SAR'000)", "2023 (SAR'000)"],
            ["Revenue", 18206447, 16762681]]
    hdr, schema = _roles(grid)
    assert schema.current_index == 1 and schema.prior_index == 2
    row = parse_tb(grid, schema, header_row=hdr).rows[0]
    assert row.current == 18206447 and row.prior == 16762681


def test_period_header_captured_inline():
    # the comparative-column label comes from the TB's OWN period header — captured at parse, both periods
    grid = [["Account", "31 Dec 2024 (SAR'000)", "31 Dec 2023 (SAR'000)"],
            ["Revenue", 18206447, 16762681]]
    hdr, schema = _roles(grid)
    parsed = parse_tb(grid, schema, header_row=hdr)
    assert "2024" in parsed.period_current and "2023" in parsed.period_prior


def test_period_header_survives_the_real_uploaded_bytes_path():
    """Self-uploading a TB must label the columns with its years too: load_grid from uploaded BYTES (BytesIO +
    filename — the actual file_uploader path, not a pre-seeded grid) still captures the period header, and
    fsgen's _period_label reduces it to the bare year (2024 / 2023)."""
    import io

    import fsgen_mfs
    tb = ROOT / "tests" / "fixtures" / "tb_upload" / "tb_test.xlsx"
    if not tb.exists():
        print("[skip] tb_test fixture absent")
        return
    grid = load_grid(io.BytesIO(tb.read_bytes()), filename="tb_test.xlsx")   # the uploaded-bytes loader
    hdr, schema = _roles(grid)
    parsed = parse_tb(grid, schema, header_row=hdr)
    assert parsed.period_current and parsed.period_prior                     # captured from the uploaded bytes
    assert fsgen_mfs._period_label(parsed.period_current) == "31st December 2024"
    assert fsgen_mfs._period_label(parsed.period_prior) == "31st December 2023"


def test_period_label_formats_full_date_dynamically_from_any_header():
    """_period_label reads the day/month/year from the TB's OWN header (no hard-coded years) and renders the
    full date; only-a-year stays a bare year; no-year stays the raw header; blank → None (→ 'Current/Prior')."""
    import fsgen_mfs as f
    assert f._period_label("31 Dec 2024 (SAR 000s)") == "31st December 2024"
    assert f._period_label("31 December 2023") == "31st December 2023"
    assert f._period_label("December 31, 2025") == "31st December 2025"
    assert f._period_label("30 June 2026") == "30th June 2026"
    assert f._period_label("Year ended 31-03-2030") == "31st March 2030"
    assert f._period_label("1/1/2022") == "1st January 2022"
    assert f._period_label("FY2024") == "2024"                # only a year resolvable → bare year
    assert f._period_label("Amount") == "Amount"              # no year → raw header verbatim
    assert f._period_label("") is None                        # blank → fall back to Current/Prior


def test_bad_row_with_amount_but_no_identity_is_surfaced_not_dropped():
    grid = [["Account", "2024 (SAR'000)"],
            ["Revenue", 18206447],
            ["", 999999]]                                        # amount, no account → must be FLAGGED
    hdr, schema = _roles(grid)
    parsed = parse_tb(grid, schema, header_row=hdr)
    assert len(parsed.rows) == 1                                 # the good row
    assert len(parsed.bad_rows) == 1 and parsed.bad_rows[0]["row"] == 2   # the bad row surfaced, not dropped


def test_multi_sheet_workbook_picks_the_tb_sheet_not_the_first():
    # a workbook with BS first and a 'TB Mapping' sheet must NOT silently read sheet 0 (BS) — the default
    # guess is the TB sheet, and load_grid reads the chosen one (the cause of the P&L/OCI-are-0 bug)
    import io

    import openpyxl

    from ai_accountant.tb_ingest import best_tb_sheet, load_grid, sheet_names
    wb = openpyxl.Workbook()
    wb.active.title = "BS"
    wb.active.append(["Account", "2024 (SAR'000)"])
    wb.active.append(["Total assets", 100])
    tb = wb.create_sheet("TB Mapping")
    tb.append(["GL Number", "2024 (SAR'000)"])
    tb.append(["1", 18206447])
    buf = io.BytesIO()
    wb.save(buf)
    names = sheet_names(io.BytesIO(buf.getvalue()))
    assert names[0] == "BS" and best_tb_sheet(names) == "TB Mapping"        # not the first sheet
    grid = load_grid(io.BytesIO(buf.getvalue()), filename="x.xlsx", sheet="TB Mapping")
    assert any("18206447" in str(c) or c == 18206447 for row in grid for c in row)


def test_non_unique_codes_become_unique_accounts():
    # a TB where the 'identity' column repeats (e.g. a level/section used as the id) must NOT collapse —
    # each row stays a distinct engine account (the engine sums by CONCEPT, not account), no key collision
    grid = [["Section", "2024 (SAR'000)"],
            ["Non-Current Assets", 100], ["Non-Current Assets", 200], ["Current Assets", 50]]
    hdr = detect_header_row(grid)
    # force the section column to be the account identity (the failure shape the user hit)
    from ai_accountant.tb_ingest.columns import confirm_column_roles, propose_column_roles
    roles = propose_column_roles(grid[hdr], grid[hdr + 1:], client=None)
    schema = confirm_column_roles(roles, {0: "account_code"})
    items, _tb = to_engine_inputs(parse_tb(grid, schema, header_row=hdr))
    accounts = [a for a, _l in items]
    assert len(accounts) == len(set(accounts)) == 3        # 3 distinct accounts despite the repeated code


def test_tb_sign_proposed_and_flipped_deterministically():
    tb_rows = [{"account": "a", "current": 100.0, "prior": 90.0, "section": "Assets"},
               {"account": "l", "current": -60.0, "prior": -50.0, "section": "Liabilities"},
               {"account": "e", "current": -40.0, "prior": -40.0, "section": "Equity"}]
    sp = propose_tb_sign(tb_rows)
    by = {s.section: s.proposed for s in sp.sections}
    assert by["Assets"] == "as_is" and by["Liabilities"] == "flip" and by["Equity"] == "flip"
    conv = confirm_tb_sign(sp, approver="t", at="t")
    flipped = {r["account"]: r["current"] for r in apply_tb_sign(tb_rows, conv)}
    assert flipped["a"] == 100.0 and flipped["l"] == 60.0 and flipped["e"] == 40.0   # credits → presentation +


# ============================================================ Slice S5a-resolve — layered resolve_concept
def test_layer1_suffix_strip_maps_suffix_variants():
    from ai_accountant.master_fs.seed import load_master_store
    from ai_accountant.tb_ingest.resolve import resolve_concept
    bank = load_master_store(seed_id="ksa_bank")
    # Layer 1 (S5a-resolve): a short level label maps to its ", net"-qualified canonical with NO model
    assert resolve_concept(bank, "Investments").concept_id == "bs_investments"          # ↔ "Investments, net"
    assert resolve_concept(bank, "Loans / financing").concept_id == "bs_loans"          # ↔ "Loans / financing, net"
    # Layer 0 (exact) still maps the full canonical
    assert resolve_concept(bank, "Customers' deposits").concept_id == "bs_deposits"
    assert resolve_concept(bank, "Investments, net").concept_id == "bs_investments"


def test_overmatch_negative_other_does_not_map_to_other_assets_or_liabilities():
    # the heightened guard: a misplaced AMOUNT is worse than flat presentation. "Other" must NOT map.
    from ai_accountant.master_fs.seed import load_master_store
    from ai_accountant.tb_ingest.resolve import resolve_concept
    bank = load_master_store(seed_id="ksa_bank")
    assert resolve_concept(bank, "Other") is None                                       # not "Other assets"/"…liabilities"
    # a genuine SYNONYM is also not force-mapped (it stays for the live AI) — "with SAMA" ≠ "with the central bank"
    assert resolve_concept(bank, "Cash and balances with SAMA") is None


def test_maturity_suffix_never_stripped_bare_label_does_not_map_a_pair():
    # stripping "— current"/"— non-current" would map a current amount to the non-current concept — must NOT happen
    from ai_accountant.master_fs.seed import load_master_store
    from ai_accountant.tb_ingest.resolve import resolve_concept
    tel = load_master_store(seed_id="telecom_mobily")
    assert resolve_concept(tel, "Contract costs") is None     # neither "Contract costs — non-current" nor "— current"


def test_strip_collision_is_ambiguous_returns_none_never_guesses():
    # a strip-COLLISION (two leaves, same statement, stripping to the same) routes through the EXISTING
    # disambiguation → None, never a guessed pick (the inherited :54-71 guard).
    import types

    from ai_accountant.tb_ingest.resolve import resolve_concept
    leaf = lambda canon: types.SimpleNamespace(kind="leaf", canonical_concept=canon, label_aliases={},
                                               statement="balance_sheet")
    store = types.SimpleNamespace(concepts={"a": leaf("Receivables, net"), "b": leaf("Receivables, gross")})
    assert resolve_concept(store, "Receivables") is None      # strips to two concepts, same statement → None


def test_b2c_ai_coverage_preserved_foreign_label_still_falls_to_the_ai():
    # GUARD the slice didn't hollow out B2c's AI test: its foreign label is NOT a strip-variant, so resolve_concept
    # returns None (Layer 0+1 miss) and it STILL falls to the live/_Fake proposer — the AI path stays exercised.
    from ai_accountant.master_fs.seed import load_master_store
    from ai_accountant.tb_ingest.resolve import resolve_concept
    tel = load_master_store(seed_id="telecom_mobily")
    assert resolve_concept(tel, "Long-term other financial assets") is None
    assert resolve_concept(tel, "Short-term other financial assets") is None


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
