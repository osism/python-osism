# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism get`` commands.

The first tests focus on the exit-code contract: a command must return a
non-zero exit status when the underlying query cannot be run (e.g. the
inventory cannot be loaded), but must keep returning success when the query
runs fine and simply yields an empty result.

The later tests cover the rendering paths: container versions read via the
Docker API, active and scheduled Celery tasks, cached Ansible facts and local
state facts from Redis, and the inventory-backed host and hostvars listings.
"""

import json
import pprint
import subprocess
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import docker
from tabulate import tabulate

from osism import utils
from osism.commands import get
from osism.utils.hostvars import Row


def _make(cls):
    return cls(MagicMock(), MagicMock())


# --- Hosts.take_action ---


def test_hosts_returns_nonzero_when_inventory_cannot_be_loaded():
    cmd = _make(get.Hosts)
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ansible-inventory"),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_hosts_returns_success_for_empty_inventory():
    cmd = _make(get.Hosts)
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"_meta": {"hostvars": {}}}).encode(),
    ), patch(
        "osism.commands.get.get_hosts_from_inventory", return_value=[]
    ):
        result = cmd.take_action(parsed_args)

    assert not result


# --- Hostvars.take_action ---


def test_hostvars_returns_nonzero_when_inventory_query_fails():
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost", "--raw"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ansible-inventory"),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_hostvars_returns_success_when_variable_absent_from_result():
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost", "missingvar", "--raw"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"present": "value"}).encode(),
    ):
        result = cmd.take_action(parsed_args)

    assert not result


def test_hostvars_prints_requested_variable(capsys):
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost", "myvar", "--raw"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"myvar": "value1", "other": "x"}).encode(),
    ):
        result = cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert not result
    assert "somehost" in out
    assert "myvar" in out
    assert "'value1'" in out
    assert "other" not in out


def test_hostvars_lists_all_variables_without_variable_argument(capsys):
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost", "--raw"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"var_a": 1, "var_b": "two"}).encode(),
    ):
        result = cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert not result
    assert "var_a" in out
    assert "var_b" in out
    assert "'two'" in out


def test_hosts_prints_host_table(capsys):
    cmd = _make(get.Hosts)
    parsed_args = cmd.get_parser("test").parse_args([])

    inventory = {"_meta": {"hostvars": {"node2": {}, "node1": {}}}}
    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps(inventory).encode(),
    ):
        result = cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert not result
    assert "Host" in out
    assert "node1" in out
    assert "node2" in out


# --- VersionsManager.take_action ---


def _container(labels):
    container = MagicMock()
    container.labels = labels
    return container


def test_versions_manager_lists_module_versions_and_releases(capsys):
    cmd = _make(get.VersionsManager)
    parsed_args = cmd.get_parser("test").parse_args([])

    containers = {
        "osism-ansible": _container({"org.opencontainers.image.version": "9.0.0"}),
        "ceph-ansible": _container(
            {
                "org.opencontainers.image.version": "9.1.0",
                "de.osism.release.ceph": "18.2.4",
            }
        ),
        "kolla-ansible": _container(
            {
                "org.opencontainers.image.version": "9.2.0",
                "de.osism.release.openstack": "2025.1",
            }
        ),
    }
    client = MagicMock()
    client.containers.get.side_effect = lambda name: containers[name]

    with patch("docker.from_env", return_value=client):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    for name in containers:
        assert name in out
    assert "18.2.4" in out
    assert "2025.1" in out


def test_versions_manager_skips_missing_containers(capsys):
    cmd = _make(get.VersionsManager)
    parsed_args = cmd.get_parser("test").parse_args([])

    labels = {
        "osism-ansible": {"org.opencontainers.image.version": "9.0.0"},
        "kolla-ansible": {
            "org.opencontainers.image.version": "9.2.0",
            "de.osism.release.openstack": "2025.1",
        },
    }

    def get_container(name):
        if name == "ceph-ansible":
            raise docker.errors.NotFound("no such container")
        return _container(labels[name])

    client = MagicMock()
    client.containers.get.side_effect = get_container

    with patch("docker.from_env", return_value=client):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert "osism-ansible" in out
    assert "kolla-ansible" in out
    assert "ceph-ansible" not in out


# --- Tasks.take_action ---


def _run_tasks(active, scheduled):
    cmd = _make(get.Tasks)
    parsed_args = cmd.get_parser("test").parse_args([])

    inspect = MagicMock()
    inspect.active.return_value = active
    inspect.scheduled.return_value = scheduled

    with patch("celery.Celery") as mock_celery:
        mock_celery.return_value.control.inspect.return_value = inspect
        cmd.take_action(parsed_args)


def test_tasks_lists_active_and_scheduled_tasks(capsys):
    start = 1750000000.0
    active = {
        "worker-a": [
            {
                "id": "task-1",
                "name": "osism.tasks.ansible.run",
                "time_start": start,
                "args": ["generic", "facts"],
            }
        ]
    }
    scheduled = {
        "worker-b": [
            {
                "id": "task-2",
                "name": "osism.tasks.conductor.sync_sonic",
                "time_start": start,
                "args": [],
            }
        ]
    }

    _run_tasks(active, scheduled)

    out = capsys.readouterr().out
    assert "worker-a" in out
    assert "task-1" in out
    assert "osism.tasks.ansible.run" in out
    assert "ACTIVE" in out
    assert "worker-b" in out
    assert "task-2" in out
    assert "SCHEDULED" in out
    assert str(datetime.fromtimestamp(start)) in out
    assert "generic" in out


def test_tasks_renders_empty_table_when_no_tasks_are_reported(capsys):
    _run_tasks({}, {})

    out = capsys.readouterr().out
    assert "Worker" in out
    assert "ACTIVE" not in out
    assert "SCHEDULED" not in out


# --- Facts.take_action / States.take_action ---


def _fake_redis(monkeypatch, value):
    """Install a fake Redis client as the ``utils.redis`` module attribute.

    ``utils.redis`` is created lazily by ``osism.utils.__getattr__`` (which
    would open a real connection) and then cached in the module globals.
    Seeding the module dict directly avoids the connection attempt and is
    undone by ``monkeypatch`` afterwards.
    """
    fake = MagicMock()
    fake.get.return_value = value
    monkeypatch.setitem(vars(utils), "redis", fake)
    return fake


def test_facts_logs_error_when_no_facts_cached(monkeypatch, loguru_logs, capsys):
    _fake_redis(monkeypatch, None)
    cmd = _make(get.Facts)
    parsed_args = cmd.get_parser("test").parse_args(["testhost"])

    cmd.take_action(parsed_args)

    assert any(
        record["level"] == "ERROR"
        and "No facts found in cache for testhost." in record["message"]
        for record in loguru_logs
    )
    assert capsys.readouterr().out == ""


def test_facts_prints_single_requested_fact(monkeypatch, capsys):
    fake = _fake_redis(
        monkeypatch, json.dumps({"ansible_hostname": "testhost", "other": 1})
    )
    cmd = _make(get.Facts)
    parsed_args = cmd.get_parser("test").parse_args(["testhost", "ansible_hostname"])

    cmd.take_action(parsed_args)

    assert fake.get.call_args_list == [
        call("ansible_factss1_testhost"),
        call("ansible_factstesthost"),
    ]
    out = capsys.readouterr().out
    assert "ansible_hostname" in out
    assert "'testhost'" in out
    assert "other" not in out


def test_facts_logs_error_for_unknown_fact(monkeypatch, loguru_logs, capsys):
    _fake_redis(monkeypatch, json.dumps({"ansible_hostname": "testhost"}))
    cmd = _make(get.Facts)
    parsed_args = cmd.get_parser("test").parse_args(["testhost", "missing_fact"])

    cmd.take_action(parsed_args)

    assert any(
        record["level"] == "ERROR"
        and "Fact missing_fact not found in cache for testhost." in record["message"]
        for record in loguru_logs
    )
    assert capsys.readouterr().out == ""


def test_facts_listing_truncates_ssh_host_key_facts(monkeypatch, capsys):
    key_facts = {
        "ansible_ssh_host_key_dsa_public": "ssh-dss " + "D" * 45,
        "ansible_ssh_host_key_ecdsa_public": "ecdsa-sha2 " + "E" * 45,
        "ansible_ssh_host_key_ed25519_public": "ssh-ed25519 " + "F" * 45,
        "ansible_ssh_host_key_rsa_public": "ssh-rsa " + "R" * 45,
    }
    _fake_redis(monkeypatch, json.dumps({"ansible_hostname": "testhost", **key_facts}))
    cmd = _make(get.Facts)
    parsed_args = cmd.get_parser("test").parse_args(["testhost"])

    cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    for value in key_facts.values():
        formatted = pprint.pformat(value, indent=2, width=60, compact=True)
        assert f"{formatted[0:40]}..." in out
        assert formatted not in out
    assert "'testhost'" in out


def test_states_lists_roles_and_skips_bootstrap(monkeypatch, capsys):
    facts = {
        "ansible_local": {
            "osism": {
                "bootstrap": {"state": "ok", "timestamp": "2026-01-01 00:00:00"},
                "docker": {"state": "ok", "timestamp": "2026-01-02 00:00:00"},
                "frr": {"state": "configured", "timestamp": "2026-01-03 00:00:00"},
            }
        }
    }
    _fake_redis(monkeypatch, json.dumps(facts))
    cmd = _make(get.States)
    parsed_args = cmd.get_parser("test").parse_args(["testhost"])

    cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert "docker" in out
    assert "frr" in out
    assert "configured" in out
    assert "2026-01-02 00:00:00" in out
    assert "bootstrap" not in out


def test_states_prints_nothing_without_local_osism_facts(monkeypatch, capsys):
    _fake_redis(monkeypatch, json.dumps({"ansible_local": {}}))
    cmd = _make(get.States)
    parsed_args = cmd.get_parser("test").parse_args(["testhost"])

    cmd.take_action(parsed_args)

    assert capsys.readouterr().out == ""


def test_states_prints_nothing_without_cache_entry(monkeypatch, capsys):
    _fake_redis(monkeypatch, None)
    cmd = _make(get.States)
    parsed_args = cmd.get_parser("test").parse_args(["testhost"])

    cmd.take_action(parsed_args)

    assert capsys.readouterr().out == ""


# --- MariadbBackupHost.take_action ---


def _backup_line(selected, resolved):
    return (
        "ok: [testbed-node-0] => {\n"
        f'    "msg": "mariadb_backup_host={selected} resolved={resolved}"\n'
        "}\n"
    )


def _run_backup_host(args, output=None, side_effect=None):
    cmd = _make(get.MariadbBackupHost)
    parsed_args = cmd.get_parser("test").parse_args(args)

    task = MagicMock()
    if side_effect is not None:
        task.get.side_effect = side_effect
    else:
        task.get.return_value = output

    with patch("osism.commands.get.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.kolla.run"
    ) as mock_run:
        mock_run.delay.return_value = task
        result = cmd.take_action(parsed_args)

    return result, mock_run


def test_mariadb_backup_host_runs_the_play_without_publishing(capsys):
    result, mock_run = _run_backup_host(
        [], output=_backup_line("testbed-node-0", "testbed-node-0")
    )

    assert not result
    mock_run.delay.assert_called_once_with(
        "kolla", "mariadb-backup-host", [], publish=False
    )
    assert "testbed-node-0" in capsys.readouterr().out


def test_mariadb_backup_host_script_format_prints_bare_host(capsys):
    # Colour codes as the worker emits them must not leak into the host name.
    output = "\x1b[0;32m" + _backup_line("testbed-node-1", "testbed-node-1") + "\x1b[0m"

    result, _ = _run_backup_host(["--format", "script"], output=output)

    assert not result
    assert capsys.readouterr().out == "testbed-node-1\n"


def test_mariadb_backup_host_ignores_other_shards(capsys):
    # Every shard resolves a host; only the default shard's is backed up.
    output = _backup_line("db-0", "db-0,db-shard1-0")

    result, _ = _run_backup_host(["--format", "script"], output=output)

    assert not result
    assert capsys.readouterr().out == "db-0\n"


def test_mariadb_backup_host_fails_when_no_backup_would_be_taken(loguru_logs, capsys):
    result, _ = _run_backup_host([], output=_backup_line("", "db-shard1-0"))

    assert result == 1
    assert capsys.readouterr().out == ""
    assert any(
        r["level"] == "ERROR" and "db-shard1-0" in r["message"] for r in loguru_logs
    )


def test_mariadb_backup_host_fails_without_a_report(loguru_logs):
    result, _ = _run_backup_host([], output="PLAY RECAP\n")

    assert result == 1
    assert any("did not report a backup host" in r["message"] for r in loguru_logs)


def test_mariadb_backup_host_fails_when_the_play_fails(loguru_logs):
    from osism.tasks import AnsibleFailure

    result, _ = _run_backup_host(
        [], side_effect=AnsibleFailure("kolla-ansible play failed with rc 1")
    )

    assert result == 1
    assert any("osism apply -e kolla" in r["message"] for r in loguru_logs)


def test_mariadb_backup_host_fails_on_timeout(loguru_logs):
    from celery.exceptions import TimeoutError as CeleryTimeoutError

    result, mock_run = _run_backup_host(
        ["--timeout", "5"], side_effect=CeleryTimeoutError()
    )

    assert result == 1
    assert any("Timeout" in r["message"] for r in loguru_logs)
    mock_run.delay.return_value.forget.assert_called_once_with()


# --- Hostvars rendered path ---


def _hv(mocker, rows=None, inv_ok=True, vault_ok=True):
    mocker.patch.object(get, "list_environments", return_value=["ceph", "kolla"])
    mocker.patch.object(get, "get_inventory_path", return_value="/inv/hosts.yml")

    def fake_check_output(cmd, **kw):
        if not inv_ok:
            raise subprocess.CalledProcessError(5, cmd)
        return b'{"_meta": {"hostvars": {}}}' if "--list" in cmd else b"{}"

    mocker.patch.object(get.subprocess, "check_output", side_effect=fake_check_output)
    if vault_ok:
        mocker.patch.object(get.utils, "get_ansible_vault_password", return_value="pw")
    else:
        mocker.patch.object(
            get.utils, "get_ansible_vault_password", side_effect=ValueError("k")
        )
    mocker.patch.dict(
        vars(utils), {"redis": mocker.Mock(get=mocker.Mock(return_value=None))}
    )
    return mocker.patch.object(get, "effective_rows", return_value=rows or [])


def _run(cls_args):
    cmd = _make(get.Hostvars)
    parser = cmd.get_parser("dump inventory")
    return cmd.take_action(parser.parse_args(cls_args))


def test_hostvars_rendered_table_has_notes_column(mocker, capsys):
    note = "fallback: n undefined here, a role may define it"
    _hv(mocker, [Row("h", "a", None, "x", False, [note], False)])
    assert not _run(["h", "a"])
    out = capsys.readouterr().out
    assert "Notes" in out and "fallback: n undefined" in out and "'x'" in out


def test_hostvars_render_reads_facts_in_the_new_cache_schema(mocker):
    effective_rows = _hv(mocker, [Row("h", "a", None, "x", False, [], False)])
    entry = json.dumps({"__payload__": json.dumps({"ansible_hostname": "h"})})
    store = {"ansible_factss1_h": entry}
    mocker.patch.dict(
        vars(utils), {"redis": mocker.Mock(get=mocker.Mock(side_effect=store.get))}
    )
    assert not _run(["h", "a"])
    assert effective_rows.call_args.kwargs["facts"] == {"ansible_hostname": "h"}


def test_hostvars_environment_row_label(mocker, capsys):
    _hv(
        mocker,
        [
            Row("h", "a", None, "g", False, [], False),
            Row("h", "a", "kolla", "k", False, [], False),
        ],
    )
    _run(["h", "a"])
    assert "a [kolla]" in capsys.readouterr().out


def test_hostvars_value_format_ambiguous_exits_1(mocker, capsys):
    _hv(
        mocker,
        [
            Row("h", "a", None, "g", False, [], False),
            Row("h", "a", "kolla", "k", False, [], False),
        ],
    )
    assert _run(["h", "a", "--format", "value"]) == 1


def test_hostvars_value_format_masked_exits_1(mocker):
    _hv(mocker, [Row("h", "a", None, "***", True, ["masked: derived from p"], False)])
    assert _run(["h", "a", "--format", "value"]) == 1


def test_hostvars_value_format_prints_bare(mocker, capsys):
    _hv(mocker, [Row("h", "a", None, "x", False, [], False)])
    assert not _run(["h", "a", "--format", "value"])
    assert capsys.readouterr().out == "x\n"


def test_hostvars_json_format(mocker, capsys):
    _hv(mocker, [Row("h", "a", "kolla", "k", False, [], False)])
    _run(["h", "a", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == [
        {
            "host": "h",
            "variable": "a",
            "environment": "kolla",
            "value": "k",
            "masked": False,
            "notes": [],
        }
    ]


def test_hostvars_absent_variable_exits_0(mocker, capsys):
    _hv(mocker, [])
    assert not _run(["h", "nope"])
    assert not _run(["h", "nope", "--format", "value"])
    capsys.readouterr()
    assert not _run(["h", "nope", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == []


def test_hostvars_failed_single_variable_exits_1(mocker):
    _hv(mocker, [Row("h", "a", None, None, False, ["render failed: x"], True)])
    assert _run(["h", "a"]) == 1


def test_hostvars_failed_row_in_full_dump_exits_0(mocker, capsys):
    _hv(mocker, [Row("h", "a", None, None, False, ["render failed: x"], True)])
    assert not _run(["h"])
    assert "render failed: x" in capsys.readouterr().out


def test_hostvars_vault_unavailable_exits_1_without_detail(mocker, capsys):
    _hv(mocker, vault_ok=False)
    assert _run(["h", "a"]) == 1
    out = capsys.readouterr()
    assert "k)" not in out.out + out.err


def test_hostvars_unknown_host_exits_1(mocker):
    _hv(mocker, inv_ok=False)
    assert _run(["h", "a"]) == 1


def test_hostvars_unknown_environment_exits_1(mocker):
    m = _hv(mocker)
    m.side_effect = get.HostvarsError(
        "unknown environment nope; available: ceph, kolla"
    )
    assert _run(["h", "a", "--environment", "nope"]) == 1


def test_hostvars_help_lists_environments(mocker):
    mocker.patch.object(get, "list_environments", return_value=["ceph", "kolla"])
    parser = _make(get.Hostvars).get_parser("dump inventory")
    assert "Available: ceph, kolla" in " ".join(parser.format_help().split())


def test_hostvars_raw_table_is_unchanged(mocker, capsys):
    data = {"a": "{{ b }}", "b": "x"}
    mocker.patch.object(get, "get_inventory_path", return_value="/inv/hosts.yml")
    mocker.patch.object(
        get.subprocess, "check_output", return_value=json.dumps(data).encode()
    )
    assert not _run(["h", "--raw"])
    expected = tabulate(
        [
            ["h", "a", pprint.pformat("{{ b }}", indent=2, width=60, compact=True)],
            ["h", "b", pprint.pformat("x", indent=2, width=60, compact=True)],
        ],
        headers=["Host", "Variable", "Value"],
        tablefmt="grid",
    )
    assert capsys.readouterr().out == expected + "\n"


def test_hostvars_raw_uses_argv_list(mocker):
    mocker.patch.object(get, "get_inventory_path", return_value="/inv/hosts.yml")
    spy = mocker.patch.object(get.subprocess, "check_output", return_value=b"{}")
    _run(["node;x", "--raw"])
    cmd = spy.call_args[0][0]
    assert isinstance(cmd, list) and "node;x" in cmd
    assert spy.call_args.kwargs.get("shell") is not True


def test_hostvars_raw_json_format(mocker, capsys):
    mocker.patch.object(get, "get_inventory_path", return_value="/inv/hosts.yml")
    mocker.patch.object(get.subprocess, "check_output", return_value=b'{"a": 1}')
    _run(["h", "a", "--raw", "--format", "json"])
    assert json.loads(capsys.readouterr().out) == [
        {
            "host": "h",
            "variable": "a",
            "environment": None,
            "value": 1,
            "masked": False,
            "notes": [],
        }
    ]


def test_hostvars_variable_must_be_an_identifier(mocker, loguru_logs):
    # Final review minor 3: the name must never reach Ansible as an
    # expression.
    m = _hv(mocker)
    assert _run(["h", "a ~ db_password"]) == 1
    assert not m.called
    assert any(
        "not a valid variable name: a ~ db_password" in r["message"]
        for r in loguru_logs
    )


def test_hostvars_value_format_masked_message(mocker, loguru_logs):
    _hv(mocker, [Row("h", "a", None, "***", True, ["masked: derived from p"], False)])
    assert _run(["h", "a", "--format", "value"]) == 1
    assert [r["message"] for r in loguru_logs if r["level"] == "ERROR"] == [
        "value is masked (derived from p); pass --show-secrets"
    ]
