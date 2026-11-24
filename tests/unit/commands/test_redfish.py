# SPDX-License-Identifier: Apache-2.0

import json
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import redfish

from ._helpers import assert_not_called_before_lock_check, make_command, parse_args

ETHERNET_INTERFACES = [
    {
        "id": "eth0",
        "name": "Ethernet 0",
        "description": "Onboard NIC",
        "mac_address": "aa:bb:cc:dd:ee:00",
        "permanent_mac_address": "aa:bb:cc:dd:ee:00",
        "speed_mbps": 10000,
        "mtu_size": 1500,
        "link_status": "LinkUp",
        "interface_enabled": True,
    },
    {
        "id": "eth1",
        "name": "Ethernet 1",
        "description": "Onboard NIC",
        "mac_address": "aa:bb:cc:dd:ee:01",
        "permanent_mac_address": "aa:bb:cc:dd:ee:01",
        "speed_mbps": 25000,
        "mtu_size": 9000,
        "link_status": "LinkDown",
        "interface_enabled": False,
    },
]


def _cmd():
    return redfish.List(MagicMock(), MagicMock())


# --- _normalize_column_name ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MAC Address", "mac_address"),
        ("mac_address", "mac_address"),
        ("", ""),
        (None, None),
    ],
)
def test_normalize_column_name(raw, expected):
    assert _cmd()._normalize_column_name(raw) == expected


# --- _get_column_mappings ---


def test_column_mappings_ethernet_interfaces():
    mappings = _cmd()._get_column_mappings("EthernetInterfaces")
    assert mappings["ID"] == "id"
    assert mappings["MAC Address"] == "mac_address"
    assert mappings["Speed (Mbps)"] == "speed_mbps"


def test_column_mappings_network_adapters():
    mappings = _cmd()._get_column_mappings("NetworkAdapters")
    assert mappings["Manufacturer"] == "manufacturer"
    assert mappings["Firmware Version"] == "firmware_version"


def test_column_mappings_network_device_functions():
    mappings = _cmd()._get_column_mappings("NetworkDeviceFunctions")
    assert mappings["Ethernet Enabled"] == "ethernet_enabled"
    assert mappings["Adapter Name"] == "adapter_name"


def test_column_mappings_unknown_type_returns_none():
    assert _cmd()._get_column_mappings("Storage") is None


# --- _get_filtered_columns ---


def test_filtered_columns_defaults_to_all():
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")

    headers, data_keys = cmd._get_filtered_columns(mappings, None)
    assert headers == list(mappings.keys())
    assert data_keys == list(mappings.values())

    headers, data_keys = cmd._get_filtered_columns(mappings, [])
    assert headers == list(mappings.keys())
    assert data_keys == list(mappings.values())


def test_filtered_columns_case_insensitive_selection_in_mapping_order():
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")

    headers, data_keys = cmd._get_filtered_columns(mappings, ["mac address", "ID"])
    assert headers == ["ID", "MAC Address"]
    assert data_keys == ["id", "mac_address"]


def test_filtered_columns_unknown_column_warns_but_keeps_valid(loguru_logs):
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")

    headers, data_keys = cmd._get_filtered_columns(mappings, ["bogus", "id"])
    assert headers == ["ID"]
    assert data_keys == ["id"]
    assert any(
        record["level"] == "WARNING"
        and "bogus" in record["message"]
        and "Available columns" in record["message"]
        for record in loguru_logs
    )


def test_filtered_columns_nothing_matches():
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")
    assert cmd._get_filtered_columns(mappings, ["bogus"]) == ([], [])


# --- _filter_json_data ---


def test_filter_json_data_reduces_to_selected_keys():
    data = [{"id": "eth0", "name": "Ethernet 0"}, {"id": "eth1"}]
    filtered = _cmd()._filter_json_data(data, ["id", "name"])
    assert filtered == [
        {"id": "eth0", "name": "Ethernet 0"},
        {"id": "eth1", "name": None},
    ]


def test_filter_json_data_passthrough_on_empty_input():
    cmd = _cmd()
    assert cmd._filter_json_data([], ["id"]) == []
    data = [{"id": "eth0"}]
    assert cmd._filter_json_data(data, []) is data


# --- _filter_and_display_table ---


def test_filter_and_display_table_empty_data_prints_nothing(capsys):
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")
    cmd._filter_and_display_table([], mappings)
    assert capsys.readouterr().out == ""


def test_filter_and_display_table_all_columns_invalid(capsys):
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")
    cmd._filter_and_display_table(ETHERNET_INTERFACES, mappings, ["bogus"])
    assert "No valid columns specified" in capsys.readouterr().out


def test_filter_and_display_table_happy_path(capsys):
    cmd = _cmd()
    mappings = cmd._get_column_mappings("EthernetInterfaces")
    cmd._filter_and_display_table(ETHERNET_INTERFACES, mappings)

    out = capsys.readouterr().out
    assert "MAC Address" in out
    assert "aa:bb:cc:dd:ee:00" in out
    assert "Total items: 2" in out


# --- take_action ---


def _run(args, result, lock_mock=None):
    cmd = _cmd()
    parsed_args = cmd.get_parser("test").parse_args(args)

    task = MagicMock()
    task.delay.return_value.get.return_value = result
    if lock_mock is None:
        lock_mock = MagicMock()
    with patch(
        "osism.commands.redfish.utils.check_task_lock_and_exit", lock_mock
    ), patch("osism.tasks.conductor.get_redfish_resources", task):
        rc = cmd.take_action(parsed_args)
    return rc, task


def test_take_action_checks_task_lock_before_dispatch():
    cmd = _cmd()
    parsed_args = cmd.get_parser("test").parse_args(["host1", "EthernetInterfaces"])

    task = MagicMock()
    task.delay.return_value.get.return_value = []
    lock_mock = MagicMock(side_effect=assert_not_called_before_lock_check(task.delay))
    with patch(
        "osism.commands.redfish.utils.check_task_lock_and_exit", lock_mock
    ), patch("osism.tasks.conductor.get_redfish_resources", task):
        cmd.take_action(parsed_args)

    lock_mock.assert_called_once_with()
    task.delay.assert_called_once_with("host1", "EthernetInterfaces")


def test_take_action_json_full_dump(capsys):
    _run(["host1", "EthernetInterfaces", "--format", "json"], ETHERNET_INTERFACES)
    out = capsys.readouterr().out
    assert out.strip() == json.dumps(ETHERNET_INTERFACES, indent=2)


def test_take_action_json_with_columns(capsys):
    _run(
        [
            "host1",
            "EthernetInterfaces",
            "--format",
            "json",
            "--column",
            "mac address",
        ],
        ETHERNET_INTERFACES,
    )
    out = capsys.readouterr().out
    assert json.loads(out) == [
        {"mac_address": "aa:bb:cc:dd:ee:00"},
        {"mac_address": "aa:bb:cc:dd:ee:01"},
    ]


def test_take_action_json_all_invalid_columns_prints_message(capsys, loguru_logs):
    # Consistent with the table path: an all-invalid column selection must
    # not silently fall back to dumping every field.
    _run(
        ["host1", "EthernetInterfaces", "--format", "json", "--column", "bogus"],
        ETHERNET_INTERFACES,
    )
    out = capsys.readouterr().out
    assert "No valid columns specified" in out
    assert "aa:bb:cc:dd:ee:00" not in out
    assert any(
        record["level"] == "WARNING"
        and "bogus" in record["message"]
        and "Available columns" in record["message"]
        for record in loguru_logs
    )


def test_take_action_json_columns_unknown_type_dumps_everything(capsys):
    result = [{"id": "x", "capacity": 42}]
    _run(["host1", "Storage", "--format", "json", "--column", "id"], result)
    out = capsys.readouterr().out
    assert json.loads(out) == result


def test_take_action_json_empty_result(capsys):
    _run(["host1", "EthernetInterfaces", "--format", "json"], [])
    assert capsys.readouterr().out.strip() == "[]"


def test_take_action_table_ethernet_interfaces(capsys):
    _run(["host1", "EthernetInterfaces"], ETHERNET_INTERFACES)
    out = capsys.readouterr().out
    assert "MAC Address" in out
    assert "Total items: 2" in out


def test_take_action_table_network_adapters(capsys):
    adapters = [{"id": "nic1", "manufacturer": "ACME", "model": "X540"}]
    _run(["host1", "NetworkAdapters"], adapters)
    out = capsys.readouterr().out
    assert "Manufacturer" in out
    assert "ACME" in out


def test_take_action_table_network_device_functions(capsys):
    functions = [{"id": "fn1", "adapter_name": "Adapter 1"}]
    _run(["host1", "NetworkDeviceFunctions"], functions)
    out = capsys.readouterr().out
    assert "Adapter Name" in out
    assert "Adapter 1" in out


def test_take_action_table_unknown_type_logs_result(capsys, loguru_logs):
    _run(["host1", "Storage"], [{"id": "x"}])
    assert capsys.readouterr().out == ""
    assert any("Retrieved resources" in record["message"] for record in loguru_logs)


def test_take_action_table_no_result(capsys):
    _run(["host1", "EthernetInterfaces"], None)
    out = capsys.readouterr().out
    assert "No EthernetInterfaces resources found for host1" in out


# --- Clock ---

CLOCK_ROW = {
    "manager_id": "1",
    "datetime": "2026-11-24T10:15:32+00:00",
    "datetime_local_offset": "+00:00",
    "conductor_datetime": "2026-11-24T10:15:31.000+00:00",
    "offset_seconds": 1.0,
    "error": None,
}


def _clock_row(**overrides):
    return {**CLOCK_ROW, **overrides}


def _clock_task(result=None):
    task = MagicMock()
    task.delay.return_value.get.return_value = result
    return task


def _run_clock(args, task, lock_mock=None):
    cmd, parsed_args = parse_args(redfish.Clock, args)
    with patch(
        "osism.commands.redfish.utils.check_task_lock_and_exit",
        lock_mock or MagicMock(),
    ), patch("osism.tasks.conductor.get_redfish_clock", task):
        return cmd.take_action(parsed_args)


def test_clock_parser_defaults_to_table():
    _, parsed_args = parse_args(redfish.Clock, ["host1"])
    assert parsed_args.hostname == "host1"
    assert parsed_args.format == "table"


def test_clock_parser_accepts_json():
    _, parsed_args = parse_args(redfish.Clock, ["host1", "--format", "json"])
    assert parsed_args.format == "json"


def test_clock_parser_rejects_unknown_format():
    parser = make_command(redfish.Clock).get_parser("test")
    with pytest.raises(SystemExit):
        parser.parse_args(["host1", "--format", "xml"])


def test_clock_checks_task_lock_before_dispatch():
    task = _clock_task([])
    lock_mock = MagicMock(side_effect=assert_not_called_before_lock_check(task.delay))

    _run_clock(["host1"], task, lock_mock)

    lock_mock.assert_called_once_with()
    task.delay.assert_called_once_with("host1")


def test_clock_table_shows_headers_and_row(capsys):
    _run_clock(["host1"], _clock_task([CLOCK_ROW]))

    out = capsys.readouterr().out
    assert "+=" in out
    for text in [
        "Manager",
        "Redfish Time",
        "Redfish UTC Offset",
        "Conductor Time",
        "Offset (s)",
        "Error",
        "| 1 ",
        "2026-11-24T10:15:32+00:00",
        "| +00:00 ",
        "2026-11-24T10:15:31.000+00:00",
        "| +1 ",
    ]:
        assert text in out
    assert "Local Time" not in out


@pytest.mark.parametrize(
    "offset, rendered",
    [
        (1.0, "| +1 "),
        (-3.0, "| -3 "),
        (1.6, "| +2 "),
        (-0.4, "| +0 "),
    ],
)
def test_clock_table_renders_offset_in_whole_seconds(capsys, offset, rendered):
    _run_clock(["host1"], _clock_task([_clock_row(offset_seconds=offset)]))
    assert rendered in capsys.readouterr().out


def test_clock_table_shows_error_row(capsys):
    error_row = _clock_row(
        manager_id="/redfish/v1/Managers/1",
        datetime=None,
        datetime_local_offset=None,
        conductor_datetime=None,
        offset_seconds=None,
        error="Unable to connect to https://bmc. Error: timed out",
    )

    _run_clock(["host1"], _clock_task([error_row, CLOCK_ROW]))

    out = capsys.readouterr().out
    assert "/redfish/v1/Managers/1" in out
    assert "Unable to connect to https://bmc. Error: timed out" in out
    assert out.count("N/A") == 4
    assert "No manager clock found" not in out


def test_clock_table_renders_missing_values_as_na(capsys):
    row = _clock_row(datetime=None, datetime_local_offset=None, offset_seconds=None)
    _run_clock(["host1"], _clock_task([row]))
    # The Error column stays empty for a row that was read
    assert capsys.readouterr().out.count("N/A") == 3


def test_clock_json_keeps_numbers_and_nulls(capsys):
    result = [
        CLOCK_ROW,
        _clock_row(manager_id="2", datetime=None, offset_seconds=None),
        _clock_row(
            manager_id="/redfish/v1/Managers/3",
            datetime=None,
            datetime_local_offset=None,
            conductor_datetime=None,
            offset_seconds=None,
            error="timed out",
        ),
    ]

    rc = _run_clock(["host1", "--format", "json"], _clock_task(result))

    out = capsys.readouterr().out
    assert out == json.dumps(result, indent=2) + "\n"
    assert '"offset_seconds": 1.0' in out
    assert '"offset_seconds": null' in out
    assert '"error": null' in out
    assert '"error": "timed out"' in out
    assert rc is None


@pytest.mark.parametrize("result", [[], None])
def test_clock_table_empty_result_prints_notice(capsys, result):
    rc = _run_clock(["host1"], _clock_task(result))
    assert capsys.readouterr().out == "No manager clock found for host1\n"
    assert rc is None


@pytest.mark.parametrize("result", [[], None])
def test_clock_json_empty_result_prints_empty_array(capsys, result):
    rc = _run_clock(["host1", "--format", "json"], _clock_task(result))
    assert capsys.readouterr().out == "[]\n"
    assert rc is None


def test_clock_large_offset_prints_only_the_table(capsys):
    rc = _run_clock(["host1"], _clock_task([_clock_row(offset_seconds=86400.0)]))

    out = capsys.readouterr().out
    assert rc is None
    assert "| +86400 " in out
    assert all(line.startswith(("+", "|")) for line in out.splitlines())


def test_clock_propagates_task_error(capsys):
    error = RuntimeError("boom")
    task = _clock_task()
    task.delay.return_value.get.side_effect = error

    with pytest.raises(RuntimeError) as excinfo:
        _run_clock(["host1"], task)

    assert excinfo.value is error
    assert capsys.readouterr().out == ""
