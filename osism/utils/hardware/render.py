# SPDX-License-Identifier: Apache-2.0

"""Rendering of hardware reports as table, CSV or JSON.

A report is a list of flat rows (dicts). Columns describe which keys of a
row are shown and under which header. The table uses the headers, CSV uses
the keys, and JSON is built by the command itself, because it is nested per
device instead of flat.
"""

import csv
from dataclasses import dataclass
import io
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from loguru import logger
from tabulate import tabulate

from osism.utils.hardware import natural_key

FORMATS = ["table", "csv", "json"]


class RenderError(Exception):
    """The requested output cannot be produced."""


@dataclass(frozen=True)
class Column:
    """One column of a report.

    Attributes:
        key: Key of the value in a flat row, also the CSV header
        header: Header in the table
        default: Shown without ``--long`` or ``--column``
    """

    key: str
    header: str
    default: bool = True


def add_output_arguments(parser) -> None:
    """Add the output options shared by the hardware reports."""
    parser.add_argument(
        "--format",
        type=str,
        choices=FORMATS,
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--column",
        action="append",
        metavar="NAME",
        help="Column to include in output (can be used multiple times)",
    )
    parser.add_argument(
        "--long",
        action="store_true",
        help="Show all columns",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write the report to a file instead of stdout",
    )


def normalize_column_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def select_columns(
    columns: Sequence[Column],
    selected: Optional[Sequence[str]] = None,
    long: bool = False,
) -> List[Column]:
    """Return the columns to show.

    Explicitly selected columns win over ``long`` and are returned in the
    order they were requested. A name matches the key or the header of a
    column, ignoring case and treating spaces and dashes as underscores.

    Raises:
        RenderError: None of the selected names is a column
    """
    if not selected:
        return [column for column in columns if long or column.default]

    by_name: Dict[str, Column] = {}
    for column in columns:
        by_name.setdefault(normalize_column_name(column.key), column)
        by_name.setdefault(normalize_column_name(column.header), column)

    result: List[Column] = []
    for name in selected:
        found = by_name.get(normalize_column_name(name))
        if found is None:
            logger.warning(f"Column '{name}' not found")
        elif found not in result:
            result.append(found)

    if not result:
        names = ", ".join(column.key for column in columns)
        raise RenderError(f"No valid columns specified. Available columns: {names}")
    return result


def flatten(record: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dicts, joining keys with ``_``.

    ``{"transceiver": {"vendor": "X"}}`` becomes ``{"transceiver_vendor":
    "X"}``. Lists are kept as values.
    """
    flat: Dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}_"))
        else:
            flat[name] = value
    return flat


def cell(value: Any) -> str:
    """Return the text shown for a value in a table or CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(cell(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def sort_rows(rows: Iterable[Dict[str, Any]], *keys: str) -> List[Dict[str, Any]]:
    """Sort rows by the given keys in natural order (Ethernet2 < Ethernet10)."""
    return sorted(rows, key=lambda row: [natural_key(row.get(key)) for key in keys])


def render_table(
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[Column],
    footer: Optional[Sequence[str]] = None,
) -> str:
    """Render rows as a ``psql`` table followed by footer lines."""
    table = tabulate(
        [[cell(row.get(column.key)) for column in columns] for row in rows],
        headers=[column.header for column in columns],
        tablefmt="psql",
        # Serial numbers such as 1E5 must not be turned into numbers
        disable_numparse=True,
    )
    if footer:
        return "\n".join([table, "", *footer])
    return table


def render_csv(rows: Sequence[Dict[str, Any]], columns: Sequence[Column]) -> str:
    """Render rows as CSV with a header row of column keys."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([column.key for column in columns])
    for row in rows:
        writer.writerow([cell(row.get(column.key)) for column in columns])
    return buffer.getvalue().rstrip("\n")


def render_json(document: Any) -> str:
    """Render a document as indented JSON."""
    return json.dumps(document, indent=2)


def write_output(text: str, path: Optional[str] = None) -> None:
    """Print the report, or write it to a file when a path is given."""
    if path:
        Path(path).write_text(text + "\n")
        logger.info(f"Report written to {path}")
    else:
        print(text)
