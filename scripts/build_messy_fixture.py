"""Write the hand-built messy fixture to an .xlsx so a human can open the actual mess.

The test (`tests/test_parsing_frontend.py`) drives the detector on the in-memory grid (the unit under
test is region detection over a grid, already past the proven pandas read). This script materialises
the SAME grid to a real workbook for manual inspection — title row, the "(in SAR '000)" subheader, the
"Finance team to update column F/G" instruction row, blank separators, an INTERNAL blank inside the
data, and two trailing footer subtotals.

    python scripts/build_messy_fixture.py   ->   TB/Messy_Fixture_XYZ.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd                                                            # noqa: E402

from test_parsing_frontend import _messy_grid                                 # noqa: E402


def main():
    out = ROOT / "TB" / "Messy_Fixture_XYZ.xlsx"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(_messy_grid()).to_excel(out, header=False, index=False)
    print(f"wrote {out}")
    print("known answer: header_row=5, data_start=6, data_end=12; "
          "footers rows 14–15 excluded; internal blank row 9 kept inside the span")


if __name__ == "__main__":
    main()
