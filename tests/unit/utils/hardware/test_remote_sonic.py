# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SONiC collector ``osism.utils.hardware.remote_sonic``."""

import io
import json

from osism.utils.hardware import remote_sonic

PORT_DUMP = {"PORT|Ethernet0": {"type": "hash", "value": {"alias": "Eth1/1"}}}


def _runner(responses, calls=None):
    """Answer ``sonic-db-dump`` calls from ``{(sudo, db, pattern): result}``."""

    def run(argv, timeout=30):
        if calls is not None:
            calls.append(argv)
        sudo = argv[0] == "sudo"
        # sudo has a -n of its own, so look behind the command name
        dump = argv[argv.index("sonic-db-dump") :]
        database = dump[dump.index("-n") + 1]
        pattern = dump[dump.index("-k") + 1]
        result = responses.get((sudo, database, pattern))
        if result is None:
            return {"rc": 1, "out": "", "err": "no such table"}
        if isinstance(result, dict) and "rc" in result:
            return result
        return {"rc": 0, "out": json.dumps(result), "err": ""}

    return run


def test_db_dump_reads_as_the_login_user_first():
    calls = []
    runner = _runner({(False, "CONFIG_DB", "PORT|*"): PORT_DUMP}, calls)

    dump, access, error = remote_sonic.db_dump("CONFIG_DB", "PORT|*", runner)

    assert (dump, access, error) == (PORT_DUMP, "user", None)
    assert calls == [["sonic-db-dump", "-n", "CONFIG_DB", "-y", "-k", "PORT|*"]]


def test_db_dump_retries_with_sudo():
    calls = []
    runner = _runner(
        {
            (False, "CONFIG_DB", "PORT|*"): {"rc": 1, "out": "", "err": "denied"},
            (True, "CONFIG_DB", "PORT|*"): PORT_DUMP,
        },
        calls,
    )

    dump, access, error = remote_sonic.db_dump("CONFIG_DB", "PORT|*", runner)

    assert (dump, access, error) == (PORT_DUMP, "sudo", None)
    assert calls[1][:2] == ["sudo", "-n"]


def test_db_dump_returns_the_last_error():
    runner = _runner(
        {
            (False, "CONFIG_DB", "PORT|*"): {"rc": 0, "out": "garbage", "err": ""},
            (True, "CONFIG_DB", "PORT|*"): {
                "rc": 1,
                "out": "",
                "err": "sudo: a password is required",
            },
        }
    )

    dump, access, error = remote_sonic.db_dump("CONFIG_DB", "PORT|*", runner)

    assert dump is None and access is None
    assert error == "sudo: a password is required"


def test_db_dump_treats_empty_output_as_an_empty_table():
    runner = _runner({(False, "STATE_DB", "X|*"): {"rc": 0, "out": "", "err": ""}})

    assert remote_sonic.db_dump("STATE_DB", "X|*", runner) == ({}, "user", None)


def test_collect_dumps_the_tables_of_the_section(tmp_path):
    eth0 = tmp_path / "eth0"
    eth0.mkdir()
    (eth0 / "address").write_text("0c:29:ef:d1:a0:01\n")
    (eth0 / "operstate").write_text("up\n")
    runner = _runner(
        {
            (False, "CONFIG_DB", "PORT|*"): PORT_DUMP,
            (False, "APPL_DB", "PORT_TABLE:*"): {"PORT_TABLE:Ethernet0": {"value": {}}},
        }
    )

    document = remote_sonic.collect(["ports"], str(tmp_path), runner)

    assert document["collector"] == "sonic"
    assert document["db"]["CONFIG_DB"]["PORT"] == PORT_DUMP
    assert "PORT_TABLE" in document["db"]["APPL_DB"]
    assert document["db_access"] == "user"
    # Optional tables that cannot be read are recorded, not fatal
    assert document["errors"] == {"CONFIG_DB DEVICE_METADATA": "no such table"}
    assert document["mgmt"]["eth0"]["address"] == "0c:29:ef:d1:a0:01"
    assert document["mgmt"]["eth0"]["carrier"] is None


def test_collect_without_management_port_omits_it(tmp_path):
    runner = _runner({(False, "CONFIG_DB", "PORT|*"): PORT_DUMP})

    assert "mgmt" not in remote_sonic.collect(["ports"], str(tmp_path), runner)


def test_main_fails_with_a_clear_message_when_the_port_table_is_unreadable(
    tmp_path, capsys
):
    code = remote_sonic.main([], sys_net=str(tmp_path), runner=_runner({}))

    assert code == 1
    assert "cannot read CONFIG_DB PORT: no such table" in capsys.readouterr().err


def test_main_prints_one_json_document(tmp_path):
    stream = io.StringIO()
    runner = _runner({(False, "CONFIG_DB", "PORT|*"): PORT_DUMP})

    code = remote_sonic.main(
        ["--sections", "ports"], sys_net=str(tmp_path), runner=runner, stream=stream
    )

    assert code == 0
    assert json.loads(stream.getvalue())["db"]["CONFIG_DB"]["PORT"] == PORT_DUMP


def test_main_rejects_unknown_sections(tmp_path, capsys):
    code = remote_sonic.main(["--sections", "bogus"], sys_net=str(tmp_path))

    assert code == 2
    assert "unknown section(s): bogus" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Hardware sections
# ---------------------------------------------------------------------------

INFO_DUMP = {"TRANSCEIVER_INFO|Ethernet0": {"value": {"manufacturer": "ACME"}}}
DOM_DUMP = {"TRANSCEIVER_DOM_SENSOR|Ethernet0": {"value": {"temperature": "30"}}}
EEPROM_DUMP = {"EEPROM_INFO|0x21": {"value": {"Name": "Product Name", "Value": "X"}}}


def _show_runner(responses, calls):
    """Answer ``sonic-db-dump`` from ``responses`` and record ``show`` calls."""
    dump = _runner(responses)

    def run(argv, timeout=30):
        if argv[0] == "show":
            calls.append(" ".join(argv))
            return {"rc": 0, "out": "output of " + " ".join(argv), "err": ""}
        return dump(argv, timeout)

    return run


def test_transceiver_and_dom_sections_dump_state_db(tmp_path):
    runner = _runner(
        {
            (False, "STATE_DB", "TRANSCEIVER_INFO|*"): INFO_DUMP,
            (False, "STATE_DB", "TRANSCEIVER_DOM_SENSOR|*"): DOM_DUMP,
        }
    )

    document = remote_sonic.collect(["transceiver", "dom"], str(tmp_path), runner)

    assert document["db"]["STATE_DB"]["TRANSCEIVER_INFO"] == INFO_DUMP
    assert document["db"]["STATE_DB"]["TRANSCEIVER_DOM_SENSOR"] == DOM_DUMP
    # The firmware table only exists on newer releases
    assert document["errors"] == {"STATE_DB TRANSCEIVER_FIRMWARE_INFO": "no such table"}


def test_system_section_prefers_files_and_tables_over_show_commands(
    tmp_path, monkeypatch
):
    version = tmp_path / "sonic_version.yml"
    version.write_text("build_version: '4.5.0'\n")
    monkeypatch.setattr(remote_sonic, "VERSION_FILE", str(version))
    calls = []
    runner = _show_runner({(False, "STATE_DB", "EEPROM_INFO|*"): EEPROM_DUMP}, calls)

    document = remote_sonic.collect(["system"], str(tmp_path), runner)

    assert document["files"]["sonic_version"] == "build_version: '4.5.0'"
    assert calls == ["show platform firmware status"]
    assert sorted(document["commands"]) == ["show platform firmware status"]


def test_system_section_falls_back_to_show_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_sonic, "VERSION_FILE", str(tmp_path / "missing.yml"))
    calls = []

    document = remote_sonic.collect(["system"], str(tmp_path), _show_runner({}, calls))

    assert document["files"]["sonic_version"] is None
    assert calls == [
        "show version",
        "show platform syseeprom",
        "show platform firmware status",
    ]
    assert document["commands"]["show version"]["out"] == "output of show version"


def test_main_accepts_the_hardware_sections(tmp_path):
    stream = io.StringIO()
    runner = _runner({(False, "CONFIG_DB", "PORT|*"): PORT_DUMP})

    code = remote_sonic.main(
        ["--sections", "ports,transceiver,dom,system"],
        sys_net=str(tmp_path),
        runner=lambda argv, timeout=30: (
            {"rc": 1, "out": "", "err": "n/a"} if argv[0] == "show" else runner(argv)
        ),
        stream=stream,
    )

    assert code == 0
    assert json.loads(stream.getvalue())["sections"] == [
        "ports",
        "transceiver",
        "dom",
        "system",
    ]


# ---------------------------------------------------------------------------
# LLDP section
# ---------------------------------------------------------------------------


def _lldp_runner(entries, calls, lldpctl_rc=0):
    """Serve LLDP_ENTRY_TABLE and record the lldpctl calls."""
    dump = _runner({(False, "APPL_DB", "LLDP_ENTRY_TABLE:*"): entries})

    def run(argv, timeout=30):
        if "lldpctl" in argv:
            calls.append(argv)
            if argv[0] != "sudo" and lldpctl_rc:
                return {"rc": lldpctl_rc, "out": "", "err": "permission denied"}
            return {"rc": 0, "out": '{"lldp": {}}', "err": ""}
        return dump(argv, timeout)

    return run


def test_lldp_section_dumps_the_entry_table(tmp_path):
    entries = {
        "LLDP_ENTRY_TABLE:Ethernet0": {"value": {"lldp_rem_sys_name": "a"}},
        "LLDP_ENTRY_TABLE:eth0": {"value": {"lldp_rem_sys_name": "mgmt-1"}},
    }
    calls = []

    document = remote_sonic.collect(
        ["lldp"], str(tmp_path), _lldp_runner(entries, calls)
    )

    assert document["db"]["APPL_DB"]["LLDP_ENTRY_TABLE"] == entries
    # The table lists the management port, so lldpctl is not needed
    assert calls == []
    assert "lldpctl" not in document


def test_lldp_section_finds_the_management_port_under_a_key_with_mac(tmp_path):
    """Enterprise SONiC 4.5 appends the MAC address of the neighbour."""
    entries = {
        "LLDP_ENTRY_TABLE:Ethernet0:02:00:00:00:00:01": {"value": {}},
        "LLDP_ENTRY_TABLE:eth0:02:00:00:00:00:17": {"value": {}},
    }
    calls = []

    document = remote_sonic.collect(
        ["lldp"], str(tmp_path), _lldp_runner(entries, calls)
    )

    assert calls == []
    assert "lldpctl" not in document


def test_lldp_section_does_not_take_another_port_for_the_management_port(tmp_path):
    entries = {"LLDP_ENTRY_TABLE:eth01": {"value": {}}}
    calls = []

    document = remote_sonic.collect(
        ["lldp"], str(tmp_path), _lldp_runner(entries, calls)
    )

    assert calls == [["docker", "exec", "lldp", "lldpctl", "-f", "json"]]
    assert document["lldpctl"]["rc"] == 0


def test_lldp_section_asks_lldpctl_when_the_management_port_is_not_listed(tmp_path):
    entries = {"LLDP_ENTRY_TABLE:Ethernet0": {"value": {"lldp_rem_sys_name": "a"}}}
    calls = []

    document = remote_sonic.collect(
        ["lldp"], str(tmp_path), _lldp_runner(entries, calls)
    )

    assert calls == [["docker", "exec", "lldp", "lldpctl", "-f", "json"]]
    assert document["lldpctl"]["rc"] == 0


def test_lldp_section_retries_lldpctl_with_sudo(tmp_path):
    calls = []

    document = remote_sonic.collect(
        ["lldp"], str(tmp_path), _lldp_runner({}, calls, lldpctl_rc=1)
    )

    assert calls == [
        ["docker", "exec", "lldp", "lldpctl", "-f", "json"],
        ["sudo", "-n", "docker", "exec", "lldp", "lldpctl", "-f", "json"],
    ]
    assert document["lldpctl"] == {"rc": 0, "out": '{"lldp": {}}', "err": ""}


def test_lldp_section_keeps_going_without_the_table(tmp_path):
    calls = []

    def run(argv, timeout=30):
        if "lldpctl" in argv:
            calls.append(argv)
            return {"rc": 0, "out": '{"lldp": {}}', "err": ""}
        return {"rc": 1, "out": "", "err": "no such table"}

    document = remote_sonic.collect(["lldp"], str(tmp_path), run)

    assert document["errors"] == {"APPL_DB LLDP_ENTRY_TABLE": "no such table"}
    assert document["lldpctl"]["rc"] == 0
    assert len(calls) == 1
