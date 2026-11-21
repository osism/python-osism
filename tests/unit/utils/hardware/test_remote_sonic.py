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
