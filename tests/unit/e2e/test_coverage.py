# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the E2E config_db coverage report.

Both halves of tests/e2e/coverage.py are pure functions over a directory
tree, so they are tested here as part of the regular unit suite. The
emitted-table regex carries most of the risk: it produces the denominator
of the "N of M config_db tables covered" claim and decides the exit code,
and a silent widening or narrowing of it would otherwise go unnoticed.
"""

import json

from tests.e2e import coverage
from tests.e2e.coverage import covered_tables, emitted_tables, main


class TestEmittedTables:
    @staticmethod
    def _write(directory, name, source):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)

    def test_direct_assignment_is_an_emission(self, tmp_path):
        self._write(tmp_path, "port.py", 'config["PORT"] = {}\n')

        assert emitted_tables(tmp_path) == {"PORT"}

    def test_cfg_alias_is_recognised(self, tmp_path):
        self._write(tmp_path, "vlan.py", 'cfg["VLAN"] = {}\n')

        assert emitted_tables(tmp_path) == {"VLAN"}

    def test_nested_item_assignment_is_an_emission(self, tmp_path):
        self._write(tmp_path, "acl.py", 'config["ACL_TABLE"]["SSH_ONLY"] = {}\n')

        assert emitted_tables(tmp_path) == {"ACL_TABLE"}

    def test_update_call_is_an_emission(self, tmp_path):
        self._write(tmp_path, "meta.py", 'config["DEVICE_METADATA"].update(other)\n')

        assert emitted_tables(tmp_path) == {"DEVICE_METADATA"}

    def test_membership_read_is_not_an_emission(self, tmp_path):
        self._write(tmp_path, "versions.py", 'if "DATABASE" in config["VERSIONS"]:\n')

        assert emitted_tables(tmp_path) == set()

    def test_equality_comparison_is_not_an_emission(self, tmp_path):
        self._write(tmp_path, "guard.py", 'if config["PORT"] == {}:\n')

        assert emitted_tables(tmp_path) == set()

    def test_read_on_the_right_hand_side_is_not_an_emission(self, tmp_path):
        self._write(
            tmp_path, "copy.py", 'config["INTERFACE"]["x"] = config["PORT"]["y"]\n'
        )

        assert emitted_tables(tmp_path) == {"INTERFACE"}

    def test_commented_out_assignment_is_ignored(self, tmp_path):
        self._write(tmp_path, "todo.py", '    # config["VXLAN_TUNNEL"] = {}\n')

        assert emitted_tables(tmp_path) == set()

    def test_generated_schema_package_is_excluded(self, tmp_path):
        self._write(tmp_path, "_generated/schema.py", 'config["SFLOW"] = {}\n')

        assert emitted_tables(tmp_path) == set()

    def test_subdirectories_are_searched(self, tmp_path):
        self._write(tmp_path, "sub/bgp.py", 'config["BGP_NEIGHBOR"] = {}\n')

        assert emitted_tables(tmp_path) == {"BGP_NEIGHBOR"}

    def test_non_python_files_are_ignored(self, tmp_path):
        self._write(tmp_path, "notes.txt", 'config["MIRROR_SESSION"] = {}\n')

        assert emitted_tables(tmp_path) == set()

    def test_lowercase_keys_are_not_table_names(self, tmp_path):
        self._write(tmp_path, "local.py", 'config["scratch"] = {}\n')

        assert emitted_tables(tmp_path) == set()

    def test_tables_accumulate_across_files(self, tmp_path):
        self._write(tmp_path, "a.py", 'config["PORT"] = {}\n')
        self._write(tmp_path, "b.py", 'config["VLAN"] = {}\n')

        assert emitted_tables(tmp_path) == {"PORT", "VLAN"}


class TestCoveredTables:
    @staticmethod
    def _write(directory, name, config):
        (directory / name).write_text(json.dumps(config))

    def test_populated_table_is_covered(self, tmp_path):
        self._write(tmp_path, "sw1.json", {"PORT": {"Ethernet0": {"speed": "100000"}}})

        assert covered_tables(tmp_path) == {"PORT"}

    def test_empty_table_is_not_covered(self, tmp_path):
        self._write(tmp_path, "sw1.json", {"PORT": {"Ethernet0": {}}, "VLAN": {}})

        assert covered_tables(tmp_path) == {"PORT"}

    def test_table_empty_in_every_file_is_not_covered(self, tmp_path):
        self._write(tmp_path, "sw1.json", {"VXLAN_TUNNEL": {}})
        self._write(tmp_path, "sw2.json", {"VXLAN_TUNNEL": {}})

        assert covered_tables(tmp_path) == set()

    def test_coverage_accumulates_across_files(self, tmp_path):
        # A table populated on one device and empty on another is covered:
        # this is how VLAN and BGP_NEIGHBOR reach the count in the real set.
        self._write(tmp_path, "sw1.json", {"VLAN": {}, "PORT": {"Ethernet0": {}}})
        self._write(tmp_path, "sw2.json", {"VLAN": {"Vlan100": {}}, "PORT": {}})

        assert covered_tables(tmp_path) == {"VLAN", "PORT"}

    def test_non_json_files_are_ignored(self, tmp_path):
        self._write(tmp_path, "sw1.json", {"PORT": {"Ethernet0": {}}})
        (tmp_path / "notes.txt").write_text('{"VLAN": {"Vlan100": {}}}')

        assert covered_tables(tmp_path) == {"PORT"}


class TestMain:
    @staticmethod
    def _stub(monkeypatch, emitted, covered):
        monkeypatch.setattr(coverage, "emitted_tables", lambda: set(emitted))
        monkeypatch.setattr(coverage, "covered_tables", lambda: set(covered))

    def test_full_coverage_returns_zero_and_prints_counts(self, monkeypatch, capsys):
        self._stub(monkeypatch, {"PORT", "VLAN"}, {"PORT", "VLAN"})

        rc = main()

        assert rc == 0
        assert "generator emits 2 tables; 2 non-empty" in capsys.readouterr().out

    def test_uncovered_tables_fail_and_are_listed_sorted(self, monkeypatch, capsys):
        self._stub(monkeypatch, {"PORT", "VXLAN_TUNNEL", "BREAKOUT_CFG"}, {"PORT"})

        rc = main()
        out = capsys.readouterr().out

        assert rc == 1
        assert "not covered by any golden file:" in out
        assert out.splitlines()[-2:] == ["  BREAKOUT_CFG", "  VXLAN_TUNNEL"]

    def test_covered_table_the_generator_cannot_emit_is_not_a_failure(
        self, monkeypatch, capsys
    ):
        self._stub(monkeypatch, {"PORT"}, {"PORT", "HAND_WRITTEN_TABLE"})

        rc = main()

        assert rc == 0
        assert "generator emits 1 tables; 2 non-empty" in capsys.readouterr().out
