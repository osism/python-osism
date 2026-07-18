# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism sonic`` Validate and List commands."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import sonic

SUPPORTED_HWSKU = "Accton-AS7326-56X"


# --- List.take_action ---


def _run_list(devices=None, argv=None, wait_exc=None):
    cmd = sonic.List(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(argv or [])

    task = MagicMock()
    if wait_exc is not None:
        task.wait.side_effect = wait_exc
    else:
        task.wait.return_value = devices or []

    with patch("osism.tasks.conductor.get_sonic_devices") as mock_get:
        mock_get.delay.return_value = task
        result = cmd.take_action(parsed_args)

    return result, mock_get


def test_list_provision_state_derivation_and_sorting(capsys, loguru_logs):
    devices = [
        {
            "name": "sw-d",
            "hwsku": SUPPORTED_HWSKU,
            "provision_state": "active",
            "role_name": "leaf",
            "oob_ip": "10.0.0.4",
            "primary_ip": "192.0.2.4",
            "version": "4.1.1",
        },
        {"name": "sw-b", "hwsku": None},
        {"name": "sw-c", "hwsku": "Bogus-HWSKU"},
        {"name": "sw-a", "hwsku": SUPPORTED_HWSKU, "provision_state": None},
    ]

    result, _ = _run_list(devices)

    assert result == 0
    out = capsys.readouterr().out
    # Rows are sorted by device name.
    assert out.index("sw-a") < out.index("sw-b") < out.index("sw-c") < out.index("sw-d")

    lines = {
        name: line
        for line in out.splitlines()
        for name in ("sw-a", "sw-b", "sw-c", "sw-d")
        if name in line
    }
    assert "N/A" in lines["sw-a"]  # supported HWSKU without provision state
    assert "No HWSKU" in lines["sw-b"]
    assert "Unsupported HWSKU" in lines["sw-c"]
    assert "active" in lines["sw-d"]
    # Missing role/oob_ip/primary_ip/version columns fall back to N/A.
    assert lines["sw-b"].count("N/A") >= 4
    assert "Total: 4 devices" in out
    assert any(
        "unsupported HWSKU: Bogus-HWSKU" in record["message"]
        and record["level"] == "WARNING"
        for record in loguru_logs
    )


def test_list_forwards_device_name():
    _, mock_get = _run_list([], argv=["spine1"])
    mock_get.delay.assert_called_once_with(device_name="spine1")


def test_list_without_devices(capsys):
    result, mock_get = _run_list([])

    assert result == 0
    mock_get.delay.assert_called_once_with(device_name=None)
    assert "No SONiC devices found matching the criteria" in capsys.readouterr().out


def test_list_returns_one_when_task_fails(loguru_logs):
    result, _ = _run_list(wait_exc=Exception("broker down"))

    assert result == 1
    assert any(
        "broker down" in record["message"] and record["level"] == "ERROR"
        for record in loguru_logs
    )


# --- Validate helpers ---


def _make_validate():
    return sonic.Validate(MagicMock(), MagicMock())


def _parse_validate(argv):
    cmd = _make_validate()
    return cmd, cmd.get_parser("test").parse_args(argv)


def _result(valid=True, errors=None, warnings=None, to_dict=None):
    result = MagicMock()
    result.valid = valid
    result.errors = errors or []
    result.warnings = warnings or []
    if to_dict is not None:
        result.to_dict.return_value = to_dict
    return result


@pytest.fixture
def export_settings(monkeypatch):
    monkeypatch.setattr("osism.settings.SONIC_EXPORT_PREFIX", "osism_")
    monkeypatch.setattr("osism.settings.SONIC_EXPORT_SUFFIX", "_config_db.json")


# --- Validate._collect_sources ---


def test_collect_sources_file(tmp_path):
    config = {"PORT": {}}
    path = tmp_path / "config_db.json"
    path.write_text(json.dumps(config))
    cmd, parsed_args = _parse_validate(["--file", str(path)])

    assert cmd._collect_sources(parsed_args) == [(str(path), config)]


def test_collect_sources_from_netbox_requires_hostname():
    cmd, parsed_args = _parse_validate(["--from-netbox"])

    with pytest.raises(ValueError):
        cmd._collect_sources(parsed_args)


def test_collect_sources_from_netbox_one_tuple_per_hostname():
    cmd, parsed_args = _parse_validate(["h1", "h2", "--from-netbox"])
    cmd._config_from_netbox = MagicMock(side_effect=[{"A": {}}, None])

    sources = cmd._collect_sources(parsed_args)

    assert sources == [("h1", {"A": {}}), ("h2", None)]
    assert [c.args[0] for c in cmd._config_from_netbox.call_args_list] == ["h1", "h2"]


def test_collect_sources_generate_requires_hostname():
    cmd, parsed_args = _parse_validate(["--generate"])

    with pytest.raises(ValueError):
        cmd._collect_sources(parsed_args)


def test_collect_sources_generate_labels():
    cmd, parsed_args = _parse_validate(["h1", "--generate"])
    cmd._config_from_generate = MagicMock(return_value={"B": {}})

    assert cmd._collect_sources(parsed_args) == [("h1 (generated)", {"B": {}})]
    cmd._config_from_generate.assert_called_once_with("h1")


def test_collect_sources_export_dir_explicit(tmp_path):
    cmd, parsed_args = _parse_validate(["--from-export-dir", str(tmp_path)])
    cmd._configs_from_export_dir = MagicMock(return_value=[])

    cmd._collect_sources(parsed_args)

    cmd._configs_from_export_dir.assert_called_once_with(str(tmp_path), [])


def test_collect_sources_export_dir_falls_back_to_setting(monkeypatch, tmp_path):
    monkeypatch.setattr("osism.settings.SONIC_EXPORT_DIR", str(tmp_path))
    cmd, parsed_args = _parse_validate(["--from-export-dir"])
    cmd._configs_from_export_dir = MagicMock(return_value=[])

    cmd._collect_sources(parsed_args)

    cmd._configs_from_export_dir.assert_called_once_with(str(tmp_path), [])


# --- Validate._configs_from_export_dir ---


def test_configs_from_export_dir_missing_dir(export_settings, tmp_path):
    cmd = _make_validate()

    with pytest.raises(ValueError):
        cmd._configs_from_export_dir(str(tmp_path / "missing"), [])


def test_configs_from_export_dir_collects_matching_files(
    export_settings, tmp_path, loguru_logs
):
    (tmp_path / "osism_sw2_config_db.json").write_text('{"B": {}}')
    (tmp_path / "osism_sw1_config_db.json").write_text('{"A": {}}')
    (tmp_path / "README.txt").write_text("skip me")
    (tmp_path / "osism_bad_config_db.json").write_text("{not json")

    sources = _make_validate()._configs_from_export_dir(str(tmp_path), [])

    assert sources == [
        (str(tmp_path / "osism_bad_config_db.json"), None),
        (str(tmp_path / "osism_sw1_config_db.json"), {"A": {}}),
        (str(tmp_path / "osism_sw2_config_db.json"), {"B": {}}),
    ]
    assert any("Could not read" in record["message"] for record in loguru_logs)


def test_configs_from_export_dir_filters_by_hostname(export_settings, tmp_path):
    (tmp_path / "osism_sw1_config_db.json").write_text('{"A": {}}')
    (tmp_path / "osism_sw2_config_db.json").write_text('{"B": {}}')

    sources = _make_validate()._configs_from_export_dir(str(tmp_path), ["sw2"])

    assert sources == [(str(tmp_path / "osism_sw2_config_db.json"), {"B": {}})]


# --- Validate._config_from_netbox ---


def test_config_from_netbox_without_device():
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(return_value=None)

    assert cmd._config_from_netbox("h1") is None


def test_config_from_netbox_without_context():
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value=None)

    assert cmd._config_from_netbox("h1") is None


def test_config_from_netbox_without_sonic_config(loguru_logs):
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"management": {}})

    assert cmd._config_from_netbox("h1") is None
    assert any("sonic_config" in record["message"] for record in loguru_logs)


def test_config_from_netbox_returns_config():
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"sonic_config": {"PORT": {}}})

    assert cmd._config_from_netbox("h1") == {"PORT": {}}


# --- Validate._config_from_generate ---


def _device_with(custom_fields):
    return SimpleNamespace(custom_fields=custom_fields)


def test_config_from_generate_without_hwsku(loguru_logs):
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(return_value=_device_with({}))

    with patch(
        "osism.tasks.conductor.sonic.config_generator.generate_sonic_config"
    ) as mock_generate:
        assert cmd._config_from_generate("h1") is None

    mock_generate.assert_not_called()
    assert any("no HWSKU configured" in record["message"] for record in loguru_logs)


def test_config_from_generate_unsupported_hwsku(loguru_logs):
    cmd = _make_validate()
    cmd._get_device_from_netbox = MagicMock(
        return_value=_device_with({"sonic_parameters": {"hwsku": "Bogus"}})
    )

    with patch(
        "osism.tasks.conductor.sonic.config_generator.generate_sonic_config"
    ) as mock_generate:
        assert cmd._config_from_generate("h1") is None

    mock_generate.assert_not_called()
    assert any("is not supported" in record["message"] for record in loguru_logs)


@pytest.mark.parametrize("config_version", [None, "4.1.1"])
def test_config_from_generate_calls_generator(config_version):
    cmd = _make_validate()
    sonic_parameters = {"hwsku": SUPPORTED_HWSKU}
    if config_version:
        sonic_parameters["config_version"] = config_version
    device = _device_with({"sonic_parameters": sonic_parameters})
    cmd._get_device_from_netbox = MagicMock(return_value=device)

    with patch(
        "osism.tasks.conductor.sonic.config_generator.generate_sonic_config",
        return_value={"PORT": {}},
    ) as mock_generate:
        assert cmd._config_from_generate("h1") == {"PORT": {}}

    mock_generate.assert_called_once_with(device, SUPPORTED_HWSKU, None, config_version)


# --- Validate.take_action ---


def test_take_action_returns_two_on_value_error():
    cmd, parsed_args = _parse_validate(["--from-netbox"])

    assert cmd.take_action(parsed_args) == 2


def test_take_action_returns_two_without_sources(loguru_logs):
    cmd, parsed_args = _parse_validate(["h1", "--from-netbox"])
    cmd._collect_sources = MagicMock(return_value=[])

    assert cmd.take_action(parsed_args) == 2
    assert any("No configurations found" in record["message"] for record in loguru_logs)


def test_take_action_all_valid_returns_zero(capsys):
    cmd, parsed_args = _parse_validate(["h1", "--from-netbox"])
    cmd._collect_sources = MagicMock(return_value=[("h1", {"PORT": {}})])

    with patch(
        "osism.tasks.conductor.sonic.validator.validate_config",
        return_value=_result(valid=True),
    ) as mock_validate:
        assert cmd.take_action(parsed_args) == 0

    mock_validate.assert_called_once_with({"PORT": {}})
    assert "[OK]" in capsys.readouterr().out


def test_take_action_invalid_returns_one(capsys):
    cmd, parsed_args = _parse_validate(["h1", "h2", "--from-netbox"])
    cmd._collect_sources = MagicMock(
        return_value=[("h1", {"PORT": {}}), ("h2", {"VLAN": {}})]
    )
    invalid = _result(
        valid=False,
        errors=[SimpleNamespace(message="bad", table="PORT", path=None)],
    )

    with patch(
        "osism.tasks.conductor.sonic.validator.validate_config",
        side_effect=[_result(valid=True), invalid],
    ):
        assert cmd.take_action(parsed_args) == 1


def test_take_action_none_config_returns_two_despite_valid_results(capsys):
    cmd, parsed_args = _parse_validate(["h1", "h2", "--from-netbox"])
    cmd._collect_sources = MagicMock(return_value=[("h1", {"PORT": {}}), ("h2", None)])

    with patch(
        "osism.tasks.conductor.sonic.validator.validate_config",
        return_value=_result(valid=True),
    ) as mock_validate:
        assert cmd.take_action(parsed_args) == 2

    # The unavailable configuration is never passed to the validator.
    mock_validate.assert_called_once_with({"PORT": {}})


def test_take_action_json_format(capsys):
    cmd, parsed_args = _parse_validate(
        ["h1", "h2", "--from-netbox", "--format", "json"]
    )
    cmd._collect_sources = MagicMock(return_value=[("h1", {"PORT": {}}), ("h2", None)])
    to_dict = {"valid": True, "errors": [], "warnings": []}

    with patch(
        "osism.tasks.conductor.sonic.validator.validate_config",
        return_value=_result(valid=True, to_dict=to_dict),
    ):
        assert cmd.take_action(parsed_args) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["h1"] == to_dict
    assert payload["h2"] == {
        "valid": False,
        "errors": [{"message": "config not available"}],
    }


# --- Validate._print_text_report ---


def _error(message, table=None, path=None):
    return SimpleNamespace(message=message, table=table, path=path)


def test_print_text_report_formats_results(capsys):
    results = [
        ("good", SimpleNamespace(valid=True, errors=[], warnings=["minor issue"])),
        (
            "bad",
            SimpleNamespace(
                valid=False,
                errors=[
                    _error("wrong speed", table="PORT", path="Ethernet0.speed"),
                    _error("missing key", table="VLAN"),
                    _error("just broken"),
                ],
                warnings=[],
            ),
        ),
        ("missing", None),
    ]

    _make_validate()._print_text_report(results)

    out = capsys.readouterr().out
    assert "[OK]    good" in out
    assert "[WARN]  good: minor issue" in out
    assert "[FAIL]  bad: 3 error(s)" in out
    assert "- wrong speed (PORT.Ethernet0.speed)" in out
    assert "- missing key (VLAN)" in out
    assert "- just broken" in out
    assert "[ERROR] missing: configuration not available" in out
    assert "Summary: 1 valid, 2 failed, 3 total" in out
