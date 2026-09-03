from __future__ import annotations

from pathlib import Path

import openpyxl


def read_xlsx_rows(path: str | Path, sheet_name: str | None = None) -> list[dict[str, str]]:
    """First row of the chosen sheet is the header. Cell values are stringified - price/quantity
    parsing into Decimal happens in validation.py, this module just gets rows out of the file."""
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook.active

    rows_iter = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows_iter)]

    rows = []
    for raw_row in rows_iter:
        if all(cell is None for cell in raw_row):
            continue
        row = {header[i]: raw_row[i] for i in range(len(header)) if i < len(raw_row)}
        rows.append({k: ("" if v is None else str(v)) for k, v in row.items()})
    workbook.close()
    return rows
