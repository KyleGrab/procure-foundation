from __future__ import annotations

import csv
from io import StringIO


def read_csv_rows(content: str) -> list[dict[str, str]]:
    """Returns list of row dicts keyed by the file's own header row - mapping to canonical
    fields happens in mapping.py, this module only knows how to read the file."""
    reader = csv.DictReader(StringIO(content))
    return [dict(row) for row in reader]
