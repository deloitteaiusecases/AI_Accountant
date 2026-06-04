"""Phase 8 QA: generate a multi-format test battery and run every scenario through the pipeline.

Generates real files into qa_data/ (so they can also be uploaded in the UI) covering: full
multi-level, L4-only, L3-only, L4 split across files, foreign column names, opening+L4,
missing classifications, adjacent tables (no blank line), multi-sheet Excel, and a large
streamed holdings file. Then runs each and prints a summary.

    python scripts/qa_suite.py
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from ai_accountant.compute.note5 import run_note5_from_files, run_note5_from_path  # noqa: E402
from ai_accountant.config import SAMPLE_NOTE5_CSV  # noqa: E402
from ai_accountant.ingestion.table_detect import detect_tables, read_rows_from_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa_data"
QA.mkdir(exist_ok=True)


class Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._buf = io.BytesIO(data)

    def __getattr__(self, item):
        return getattr(self.__dict__["_buf"], item)


def _from_file(p: Path) -> Upload:
    return Upload(p.name, p.read_bytes())


# --- parse the sample into tables we can recombine -------------------------------
TABLES = detect_tables(read_rows_from_path(str(SAMPLE_NOTE5_CSV)))


def _by(level=None, has=None):
    out = []
    for t in TABLES:
        if level and t.level != level:
            continue
        if has and not t.has_columns(has):
            continue
        out.append(t)
    return out


def _write_csv(path: Path, tables, blank_between=True, drop_class=False, rename=None):
    rows: list[list[str]] = []
    for t in tables:
        headers = list(t.headers)
        if rename:
            headers = [rename.get(h, h) for h in headers]
        if t.title:
            rows.append([t.title])
        rows.append(headers)
        for rec in t.records:
            row = []
            for h in t.headers:
                val = rec.get(h, "")
                if drop_class and h == "Classification":
                    val = ""
                row.append(val)
            rows.append(row)
        if blank_between:
            rows.append([])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def generate() -> dict[str, list[Path]]:
    l3 = _by(level="L3")[0]
    l4 = _by(level="L4")
    purchases = next(t for t in l4 if t.has_columns("Total_Cost_000"))
    mtm = next(t for t in l4 if t.has_columns("MtM_Change_000"))
    eir = next(t for t in l4 if t.has_columns("Monthly_Amort_000"))

    scenarios: dict[str, list[Path]] = {}

    # 1) Full multi-level (copy of the sample).
    p = QA / "01_full_multilevel.csv"
    p.write_text(SAMPLE_NOTE5_CSV.read_text(encoding="utf-8-sig"), encoding="utf-8")
    scenarios["01 full multi-level"] = [p]

    # 2) L4-only (all L4 tables).
    p = QA / "02_l4_only.csv"
    _write_csv(p, l4)
    scenarios["02 L4-only"] = [p]

    # 3) L3-only sub-ledger.
    p = QA / "03_l3_only.csv"
    _write_csv(p, [l3])
    scenarios["03 L3-only"] = [p]

    # 4) L4 split across 3 files.
    pa, pb, pc = QA / "04a_purchases.csv", QA / "04b_mtm.csv", QA / "04c_eir.csv"
    _write_csv(pa, [purchases]); _write_csv(pb, [mtm]); _write_csv(pc, [eir])
    scenarios["04 L4 split across files"] = [pa, pb, pc]

    # 5) Foreign column names (L3).
    p = QA / "05_foreign_columns.csv"
    _write_csv(p, [l3], rename={"Holding_ID": "Security ID", "Carrying_Value_000": "Carrying Value",
                                "Classification": "Asset Class", "Security_Name": "Instrument"})
    scenarios["05 foreign column names"] = [p]

    # 6) Opening balances + L4.
    op = QA / "06a_opening.csv"
    with open(op, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Classification", "Opening_000"])
        w.writerow(["FVTPL", "2200000"]); w.writerow(["FVOCI", "10800000"]); w.writerow(["AC", "8500000"])
    p_l4 = QA / "06b_l4.csv"
    _write_csv(p_l4, l4)
    scenarios["06 opening + L4"] = [op, p_l4]

    # 7) Missing classifications (L3 with blank Classification).
    p = QA / "07_missing_class.csv"
    _write_csv(p, [l3], drop_class=True)
    scenarios["07 missing classifications"] = [p]

    # 8) Adjacent tables, no blank line between them.
    p = QA / "08_adjacent_tables.csv"
    _write_csv(p, [l3], blank_between=False)
    # append a second small table directly after (no blank line)
    with open(p, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Txn_ID", "Holding_ID", "Classification", "Total_Cost_000"])
        w.writerow(["PUR-X1", "AC-001", "AC", "1000"])
        w.writerow(["PUR-X2", "OCI-001", "FVOCI", "2000"])
    scenarios["08 adjacent tables (no blank)"] = [p]

    # 9) Multi-sheet Excel (L3 + each L4 table on its own sheet).
    px = QA / "09_multisheet.xlsx"
    with pd.ExcelWriter(px, engine="openpyxl") as xw:
        pd.DataFrame(l3.records).to_excel(xw, sheet_name="holdings", index=False)
        for i, t in enumerate(l4):
            pd.DataFrame(t.records).to_excel(xw, sheet_name=f"L4_{i+1}", index=False)
    scenarios["09 multi-sheet Excel"] = [px]

    # 10) Large streamed holdings file (> 5 MB -> streaming path).
    p = QA / "10_large_holdings.csv"
    classes = ["FVTPL", "FVOCI", "AC"]
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Holding_ID", "Security_Name", "Classification", "Carrying_Value_000"])
        for i in range(300_000):
            w.writerow([f"H-{i}", f"Security {i}", classes[i % 3], 1000])
    scenarios["10 large (streamed)"] = [p]

    return scenarios


def _run(name: str, files: list[Path]):
    try:
        if len(files) == 1 and files[0].suffix == ".csv" and "full" in files[0].stem:
            res = run_note5_from_path(str(files[0]))
        else:
            res = run_note5_from_files([_from_file(p) for p in files])
        c = res.cascade
        recon = "n/a"
        stated = [s for s in res.reconciliation_report if "stated" in s.source]
        if stated:
            recon = "ties" if all(s.matched for s in stated) else "variance"
        return {
            "scenario": name, "files": len(files), "tables": len(res.tables),
            "FVTPL": c.l1.get("FVTPL", 0), "TOTAL": c.l1.get("TOTAL", 0),
            "partial": c.partial, "recon": recon,
            "confidence": res.confidence.level, "classified": len(res.classifications),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"scenario": name, "files": len(files), "error": repr(exc)[:80]}


def main():
    scenarios = generate()
    print(f"Generated {sum(len(v) for v in scenarios.values())} files in {QA}\n")
    rows = [_run(name, files) for name, files in scenarios.items()]
    df = pd.DataFrame(rows)
    cols = ["scenario", "files", "tables", "FVTPL", "TOTAL", "partial", "recon",
            "confidence", "classified", "error"]
    df = df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.max_columns", None, "display.width", 200,
                           "display.float_format", lambda v: f"{v:,.0f}"):
        print(df.to_string(index=False))
    errors = [r for r in rows if r.get("error")]
    print(f"\n{len(rows)} scenarios run, {len(errors)} error(s).")


if __name__ == "__main__":
    main()
