"""TB ingestion front-end (Slice I1) — turn an uploaded TB workbook (xlsx or csv), of ANY column
layout, into the `(items, tb_rows)` the master-FS confirm chain already consumes.

Structure-agnostic by discipline: the column-role proposer keys off header/sample MEANING (never
position), the human CONFIRMS every column and the TB-presentation sign, and code owns every number.
This is a parsing FRONT-END only — everything from archetype-detection onward is the existing engine.
GL movement data / multi-file / multi-sheet / streaming is the explicit NEXT slice, out here.
"""
from __future__ import annotations

from ai_accountant.tb_ingest.grid import best_bs_sheet, best_tb_sheet, load_grid, sheet_names
from ai_accountant.tb_ingest.columns import (ColumnRole, ResolvedTBSchema, confirm_column_roles,
                                             heuristic_column_roles, propose_column_roles)
from ai_accountant.tb_ingest.parse import ParsedRow, ParsedTB, detect_header_row, parse_tb, to_engine_inputs
from ai_accountant.tb_ingest.bs_split import parse_bs_split
from ai_accountant.tb_ingest.sign import (TBSignConvention, TBSignProposal, apply_tb_sign,
                                          confirm_tb_sign, propose_tb_sign)

__all__ = ["load_grid", "sheet_names", "best_tb_sheet", "best_bs_sheet", "ColumnRole", "ResolvedTBSchema",
           "confirm_column_roles", "heuristic_column_roles", "propose_column_roles", "ParsedRow", "ParsedTB",
           "detect_header_row", "parse_tb", "to_engine_inputs", "parse_bs_split", "TBSignConvention",
           "TBSignProposal", "apply_tb_sign", "confirm_tb_sign", "propose_tb_sign"]
