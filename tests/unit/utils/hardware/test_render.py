# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.render``."""

import argparse
import csv
import io
import json

import pytest

from osism.utils.hardware.render import (
    Column,
    RenderError,
    add_output_arguments,
    cell,
    flatten,
    render_csv,
    render_json,
    render_table,
    select_columns,
    sort_rows,
    write_output,
)

COLUMNS = [
    Column("device_name", "Device"),
    Column("interface_name", "Interface"),
    Column("transceiver_vendor", "Vendor"),
    Column("transceiver_part_number", "Part Number", default=False),
]
ROWS = [
    {
        "device_name": "leaf-1a",
        "interface_name": "Ethernet0",
        "transceiver_vendor": "ACME",
        "transceiver_part_number": "1E5",
    },
    {
        "device_name": "leaf-1a",
        "interface_name": "Ethernet4",
        "transceiver_vendor": None,
    },
]


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def test_output_arguments():
    parser = argparse.ArgumentParser()
    add_output_arguments(parser)

    args = parser.parse_args([])
    assert (args.format, args.column, args.long, args.output) == (
        "table",
        None,
        False,
        None,
    )

    args = parser.parse_args(
        ["--format", "csv", "--column", "a", "--column", "b", "--long", "--output", "f"]
    )
    assert (args.format, args.column, args.long, args.output) == (
        "csv",
        ["a", "b"],
        True,
        "f",
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["--format", "yaml"])


def test_default_columns_and_long():
    assert [c.key for c in select_columns(COLUMNS)] == [
        "device_name",
        "interface_name",
        "transceiver_vendor",
    ]
    assert len(select_columns(COLUMNS, long=True)) == 4


def test_selected_columns_match_key_or_header_in_requested_order():
    columns = select_columns(
        COLUMNS, ["Part Number", "device-name", "VENDOR", "device_name"], long=True
    )

    assert [c.key for c in columns] == [
        "transceiver_part_number",
        "device_name",
        "transceiver_vendor",
    ]


def test_unknown_column_is_reported(loguru_logs):
    columns = select_columns(COLUMNS, ["device_name", "bogus"])

    assert [c.key for c in columns] == ["device_name"]
    assert _has_log(loguru_logs, "WARNING", "Column 'bogus' not found")


def test_no_valid_column_is_an_error():
    with pytest.raises(RenderError, match="Available columns: device_name"):
        select_columns(COLUMNS, ["bogus"])


def test_flatten_joins_nested_keys():
    record = {
        "name": "Ethernet0",
        "transceiver": {"vendor": "ACME", "dom": {"temperature": 31.5}},
        "altnames": ["a", "b"],
    }

    assert flatten(record) == {
        "name": "Ethernet0",
        "transceiver_vendor": "ACME",
        "transceiver_dom_temperature": 31.5,
        "altnames": ["a", "b"],
    }
    assert flatten({"vendor": "X"}, "nic_") == {"nic_vendor": "X"}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ""),
        (True, "yes"),
        (False, "no"),
        (25000, "25000"),
        (["a", None, 2], "a, , 2"),
        ({"b": 1, "a": 2}, '{"a": 2, "b": 1}'),
        ("text", "text"),
    ],
)
def test_cell(value, expected):
    assert cell(value) == expected


def test_sort_rows_uses_natural_order():
    rows = [
        {"device": "leaf-2", "interface": "Ethernet2"},
        {"device": "leaf-10", "interface": "Ethernet0"},
        {"device": "leaf-2", "interface": "Ethernet10"},
        {"device": "leaf-2", "interface": None},
    ]

    ordered = sort_rows(rows, "device", "interface")

    assert [(r["device"], r["interface"]) for r in ordered] == [
        ("leaf-2", None),
        ("leaf-2", "Ethernet2"),
        ("leaf-2", "Ethernet10"),
        ("leaf-10", "Ethernet0"),
    ]


def test_render_table_with_footer():
    text = render_table(
        ROWS, select_columns(COLUMNS, long=True), ["Devices: 1", "Ports: 2"]
    )

    lines = text.splitlines()
    assert lines[0].startswith("+--")
    assert "| Device" in lines[1] and "Part Number" in lines[1]
    # The serial-like value stays a string instead of becoming 100000.0
    assert "| 1E5 " in text
    assert lines[-3:] == ["", "Devices: 1", "Ports: 2"]


def test_render_table_without_footer_and_rows():
    text = render_table([], COLUMNS[:2])

    assert "Device" in text
    assert not text.endswith("\n")


def test_render_csv_has_a_key_header_and_no_footer():
    text = render_csv(ROWS, select_columns(COLUMNS, long=True))

    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed == [
        [
            "device_name",
            "interface_name",
            "transceiver_vendor",
            "transceiver_part_number",
        ],
        ["leaf-1a", "Ethernet0", "ACME", "1E5"],
        ["leaf-1a", "Ethernet4", "", ""],
    ]


def test_render_csv_quotes_separators():
    text = render_csv([{"device_name": "a,b"}], COLUMNS[:1])

    assert list(csv.reader(io.StringIO(text)))[1] == ["a,b"]


def test_render_json_round_trips():
    document = {"devices": [{"name": "leaf-1a", "interfaces": []}], "failed": []}

    assert json.loads(render_json(document)) == document


def test_write_output_prints_to_stdout(capsys):
    write_output("report")

    assert capsys.readouterr().out == "report\n"


def test_write_output_writes_a_file_and_keeps_stdout_clean(
    tmp_path, capsys, loguru_logs
):
    path = tmp_path / "report.csv"

    write_output("a,b\n1,2", str(path))

    assert path.read_text() == "a,b\n1,2\n"
    assert capsys.readouterr().out == ""
    assert _has_log(loguru_logs, "INFO", f"Report written to {path}")
