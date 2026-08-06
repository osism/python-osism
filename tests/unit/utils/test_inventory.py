# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from osism.utils.inventory import (
    HostContextResolutionError,
    get_hosts_from_inventory,
    get_inventory_path,
    resolve_in_host_context,
)


def _make_base(tmp_path):
    base = tmp_path / "hosts.yml"
    base.write_text("---\n")
    return base


def test_get_inventory_path_minified_preferred(tmp_path):
    base = _make_base(tmp_path)
    minified = tmp_path / "hosts-minified.yml"
    minified.write_text("---\n")

    assert get_inventory_path(str(base)) == str(minified)


def test_get_inventory_path_minified_ignored_when_not_preferred(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "hosts-minified.yml").write_text("---\n")

    assert get_inventory_path(str(base), prefer_minified=False) == str(base)


def test_get_inventory_path_fast_directory(tmp_path):
    base = _make_base(tmp_path)
    fast = tmp_path / "fast"
    fast.mkdir()

    assert get_inventory_path(str(base)) == str(fast)


def test_get_inventory_path_fallback_to_base(tmp_path):
    base = _make_base(tmp_path)

    assert get_inventory_path(str(base)) == str(base)


def test_get_inventory_path_minified_wins_over_fast(tmp_path):
    base = _make_base(tmp_path)
    minified = tmp_path / "hosts-minified.yml"
    minified.write_text("---\n")
    (tmp_path / "fast").mkdir()

    assert get_inventory_path(str(base), prefer_minified=True) == str(minified)


def test_get_inventory_path_fast_wins_when_minified_not_preferred(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "hosts-minified.yml").write_text("---\n")
    fast = tmp_path / "fast"
    fast.mkdir()

    assert get_inventory_path(str(base), prefer_minified=False) == str(fast)


def test_get_inventory_path_fast_as_file_is_ignored(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "fast").write_text("not a directory\n")

    assert get_inventory_path(str(base)) == str(base)


def test_get_hosts_from_inventory_hostvars_only():
    data = {
        "_meta": {"hostvars": {"host-b": {}, "host-a": {}}},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_groups_only():
    data = {
        "webservers": {"hosts": ["host-b", "host-a"]},
        "dbservers": {"hosts": ["host-c"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b", "host-c"]


def test_get_hosts_from_inventory_union_deduplicated():
    data = {
        "_meta": {"hostvars": {"host-a": {}, "host-b": {}}},
        "webservers": {"hosts": ["host-b", "host-c"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b", "host-c"]


def test_get_hosts_from_inventory_empty():
    assert get_hosts_from_inventory({}) == []


def test_get_hosts_from_inventory_ignores_non_dict_and_missing_hosts():
    data = {
        "_meta": {"hostvars": {"host-a": {}}},
        "all": ["not", "a", "dict"],
        "empty_group": {},
        "group_with_children_only": {"children": ["other"]},
        "webservers": {"hosts": ["host-b"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_result_is_sorted():
    data = {
        "_meta": {"hostvars": {"zeta": {}, "alpha": {}}},
        "group": {"hosts": ["mike", "bravo"]},
    }

    assert get_hosts_from_inventory(data) == ["alpha", "bravo", "mike", "zeta"]


def test_get_hosts_from_inventory_meta_without_hostvars_key():
    data = {
        "_meta": {},
        "webservers": {"hosts": ["host-a"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a"]


def test_get_hosts_from_inventory_duplicates_within_group_deduplicated():
    data = {
        "webservers": {"hosts": ["host-a", "host-a", "host-b"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_group_with_hosts_and_children():
    data = {
        "webservers": {
            "hosts": ["host-a"],
            "children": ["other-group"],
        },
    }

    assert get_hosts_from_inventory(data) == ["host-a"]


class TestResolveInHostContext:
    """``resolve_in_host_context`` delegates templating to Ansible.

    The subprocess is mocked: what matters here is the command that gets built,
    that facts travel as an extra-vars file, and that the value is read back from
    the file Ansible writes rather than parsed out of its output -- the callback
    format differs between the ansible-core versions this package runs under.
    """

    @staticmethod
    def _run(mocker, returncode=0, value=None, stdout="", stderr="", capture=None):
        """Patch subprocess.run, optionally writing the value file."""

        def fake_run(command, **kwargs):
            args = json.loads(command[command.index("-a") + 1])
            if capture is not None:
                # The temp dir is gone by the time the test inspects anything,
                # so read the extra-vars file here.
                extra_vars = None
                if "-e" in command:
                    with open(command[command.index("-e") + 1][1:]) as fp:
                        extra_vars = json.load(fp)
                capture.append((command, kwargs, args, extra_vars))
            if value is not None:
                with open(args["dest"], "w") as fp:
                    fp.write(value)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        return mocker.patch(
            "osism.utils.inventory.subprocess.run", side_effect=fake_run
        )

    def test_returns_templated_value(self, mocker):
        self._run(mocker, value="10.0.0.5")

        assert resolve_in_host_context("host1", "some_expression", "/inv") == "10.0.0.5"

    def test_value_is_returned_byte_exact(self, mocker):
        # No stripping: the helper is generic, and Ansible's copy writes the
        # content without adding a trailing newline.
        self._run(mocker, value="a b  c")

        assert resolve_in_host_context("host1", "expr", "/inv") == "a b  c"

    def test_command_wraps_expression_and_passes_inventory(self, mocker):
        calls = []
        self._run(mocker, value="10.0.0.5", capture=calls)

        resolve_in_host_context("host1", "internal_interface", "/inv/hosts.yml")

        command, kwargs, args, _ = calls[0]
        assert command[:2] == ["ansible", "host1"]
        assert command[command.index("-i") + 1] == "/inv/hosts.yml"
        assert command[command.index("-m") + 1] == "copy"
        # -c local keeps the module on the controller, so a host that is down
        # still resolves and no SSH is attempted.
        assert command[command.index("-c") + 1] == "local"
        assert args["content"] == "{{ internal_interface }}"
        assert kwargs["env"]["ANSIBLE_GATHERING"] == "explicit"

    def test_module_args_are_json_not_key_value(self, mocker):
        # key=value args would split a value containing spaces.
        calls = []
        self._run(mocker, value="x", capture=calls)

        resolve_in_host_context("host1", "expr", "/inv")

        raw = calls[0][0][calls[0][0].index("-a") + 1]
        assert json.loads(raw)  # parses as JSON

    def test_facts_are_passed_as_extra_vars_file(self, mocker):
        calls = []
        self._run(mocker, value="10.0.0.5", capture=calls)
        facts = {"ansible_local": {"testbed_network_devices": {"management": "eth3"}}}

        resolve_in_host_context("host1", "expr", "/inv", facts=facts)

        command, _, _, extra_vars = calls[0]
        assert command[command.index("-e") + 1].startswith("@")
        assert extra_vars == facts

    def test_no_extra_vars_argument_without_facts(self, mocker):
        calls = []
        self._run(mocker, value="10.0.0.5", capture=calls)

        resolve_in_host_context("host1", "expr", "/inv")

        assert "-e" not in calls[0][0]

    def test_nonzero_exit_raises_with_ansible_message(self, mocker):
        # Ansible names the undefined attribute; that is what the operator needs.
        self._run(mocker, returncode=2, stdout="has no attribute 'ansible_vlan999'")

        with pytest.raises(HostContextResolutionError, match="ansible_vlan999"):
            resolve_in_host_context("host1", "expr", "/inv")

    def test_nonzero_exit_falls_back_to_stderr(self, mocker):
        # 2.18 and 2.19 do not agree on which stream carries the error.
        self._run(mocker, returncode=4, stderr="could not match supplied host pattern")

        with pytest.raises(HostContextResolutionError, match="host pattern"):
            resolve_in_host_context("host1", "expr", "/inv")

    def test_success_without_value_file_raises(self, mocker):
        self._run(mocker, returncode=0)

        with pytest.raises(HostContextResolutionError, match="no value"):
            resolve_in_host_context("host1", "expr", "/inv")

    def test_timeout_raises(self, mocker):
        mocker.patch(
            "osism.utils.inventory.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ansible", 60),
        )

        with pytest.raises(HostContextResolutionError, match="timed out"):
            resolve_in_host_context("host1", "expr", "/inv")

    def test_temporary_directory_is_cleaned_up(self, mocker):
        calls = []
        self._run(mocker, value="10.0.0.5", capture=calls)

        resolve_in_host_context("host1", "expr", "/inv", facts={"a": 1})

        assert not os.path.exists(os.path.dirname(calls[0][2]["dest"]))
