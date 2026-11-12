from __future__ import annotations

from pathlib import Path
from typing import Any

from .format_detection import read_metadata


def read_ncnr_legacy_file(path: str, max_rows: int | None = None) -> dict[str, Any]:
    """Read NCNR legacy BT-4/BT-9/NG5-style metadata and numeric table rows.

    This is a Python 3 port boundary for the useful read-only behavior in the
    historical tripleaxisproject readncnr.py reader. It intentionally avoids
    reduction logic and writes no files.
    """

    text = _read_text(path)
    lines = text.splitlines()
    metadata = read_metadata(path, header="\n".join(lines[:32]))
    columns, rows, skipped = _read_legacy_columns(lines, max_rows=max_rows)
    return {
        "path": path,
        "metadata": metadata,
        "columns": columns,
        "row_count": len(rows),
        "rows": rows,
        "column_stats": _column_stats(columns, rows),
        "skipped_non_tabular_lines": skipped,
        "reader_strategy": "ncnr_legacy_python3_port",
        "source_reader": "tripleaxisproject/tripleaxisproject/eclipse/src/utilities/readncnr.py",
    }


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _read_legacy_columns(lines: list[str], max_rows: int | None = None) -> tuple[list[str], list[dict[str, float]], int]:
    header_index = _column_header_index(lines)
    if header_index is None:
        return [], [], 0

    columns = [_normalize_column_name(value) for value in lines[header_index].split()]
    rows: list[dict[str, float]] = []
    skipped = 0
    for line in lines[header_index + 1 :]:
        values = line.split()
        if not values:
            continue
        if len(values) != len(columns):
            skipped += 1
            continue
        try:
            numeric = [float(value) for value in values]
        except ValueError:
            skipped += 1
            continue
        rows.append(dict(zip(columns, numeric)))
        if max_rows is not None and len(rows) >= int(max_rows):
            break
    return columns, rows, skipped


def _column_header_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "q(x)" in lowered and "q(y)" in lowered and "counts" in lowered:
            return index
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "#columns" in lowered:
            return index
    return None


def _normalize_column_name(value: str) -> str:
    lower = value.strip().lower()
    aliases = {
        "q(x)": "qx",
        "q(y)": "qy",
        "q(z)": "qz",
        "t-act": "temp",
    }
    if lower == "#columns":
        return "index"
    return aliases.get(lower, lower)


def _column_stats(columns: list[str], rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for column in columns:
        values = [row[column] for row in rows if column in row]
        if not values:
            continue
        stats[column] = {
            "min": min(values),
            "max": max(values),
            "first": values[0],
            "last": values[-1],
        }
    return stats
