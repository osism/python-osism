# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the E2E golden-file comparator.

The comparator itself (tests/e2e/compare.py) is pure logic and independent
of any infrastructure, so it is tested here as part of the regular unit
suite.
"""

import json

from tests.e2e.compare import compare_dirs, diff_paths, main, regenerate


class TestDiffPaths:
    def test_equal_configs_yield_no_paths(self):
        config = {"PORT": {"Ethernet0": {"speed": "100000"}}}

        assert diff_paths(config, config) == []

    def test_value_mismatch_reports_table_entry_attribute_path(self):
        golden = {"PORT": {"Ethernet4": {"speed": "100000"}}}
        actual = {"PORT": {"Ethernet4": {"speed": "100"}}}

        assert diff_paths(golden, actual) == [
            "PORT|Ethernet4.speed: golden '100000', actual '100'"
        ]

    def test_entry_only_in_golden(self):
        golden = {"PORT": {"Ethernet4": {"speed": "100000"}}}
        actual = {"PORT": {}}

        assert diff_paths(golden, actual) == ["PORT|Ethernet4: only in golden"]

    def test_entry_only_in_actual(self):
        golden = {"PORT": {}}
        actual = {"PORT": {"Ethernet4": {"speed": "100000"}}}

        assert diff_paths(golden, actual) == ["PORT|Ethernet4: only in actual"]

    def test_table_only_in_golden(self):
        golden = {"VLAN": {"Vlan100": {}}}
        actual = {}

        assert diff_paths(golden, actual) == ["VLAN: only in golden"]

    def test_array_order_is_significant(self):
        golden = {"PORT": {"Ethernet0": {"valid_speeds": ["100000", "50000"]}}}
        actual = {"PORT": {"Ethernet0": {"valid_speeds": ["50000", "100000"]}}}

        paths = diff_paths(golden, actual)

        assert paths == [
            "PORT|Ethernet0.valid_speeds[0]: golden '100000', actual '50000'",
            "PORT|Ethernet0.valid_speeds[1]: golden '50000', actual '100000'",
        ]

    def test_array_length_difference_reported(self):
        golden = {"PORT": {"Ethernet0": {"valid_speeds": ["100000"]}}}
        actual = {"PORT": {"Ethernet0": {"valid_speeds": ["100000", "50000"]}}}

        assert diff_paths(golden, actual) == [
            "PORT|Ethernet0.valid_speeds[1]: only in actual"
        ]

    def test_type_mismatch_reported_as_value_difference(self):
        golden = {"PORT": {"Ethernet0": {"mtu": "9100"}}}
        actual = {"PORT": {"Ethernet0": {"mtu": 9100}}}

        assert diff_paths(golden, actual) == [
            "PORT|Ethernet0.mtu: golden '9100', actual 9100"
        ]

    def test_multiple_differences_are_sorted_by_path(self):
        golden = {
            "PORT": {"Ethernet0": {"speed": "100000"}},
            "VLAN": {"Vlan100": {"vlanid": "100"}},
        }
        actual = {
            "PORT": {"Ethernet0": {"speed": "100"}},
            "VLAN": {"Vlan100": {"vlanid": "200"}},
        }

        paths = diff_paths(golden, actual)

        assert paths == sorted(paths)
        assert len(paths) == 2

    def test_deeply_nested_values_use_dot_separators(self):
        golden = {"BGP_NEIGHBOR": {"10.0.0.1": {"af": {"ipv4": "on"}}}}
        actual = {"BGP_NEIGHBOR": {"10.0.0.1": {"af": {"ipv4": "off"}}}}

        assert diff_paths(golden, actual) == [
            "BGP_NEIGHBOR|10.0.0.1.af.ipv4: golden 'on', actual 'off'"
        ]


class TestCompareDirs:
    @staticmethod
    def _write(directory, name, config):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(config))

    def test_identical_dirs_are_ok(self, tmp_path):
        config = {"PORT": {"Ethernet0": {"speed": "100000"}}}
        self._write(tmp_path / "golden", "osism_sw1_config_db.json", config)
        self._write(tmp_path / "export", "osism_sw1_config_db.json", config)

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")

        assert result.ok
        assert result.missing == []
        assert result.extra == []
        assert result.mismatched == {}

    def test_missing_export_is_reported(self, tmp_path):
        self._write(tmp_path / "golden", "osism_sw1_config_db.json", {})
        (tmp_path / "export").mkdir()

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")

        assert not result.ok
        assert result.missing == ["osism_sw1_config_db.json"]

    def test_extra_export_is_reported(self, tmp_path):
        (tmp_path / "golden").mkdir()
        self._write(tmp_path / "export", "osism_sw2_config_db.json", {})

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")

        assert not result.ok
        assert result.extra == ["osism_sw2_config_db.json"]

    def test_mismatch_collects_paths_and_unified_diff(self, tmp_path):
        name = "osism_sw1_config_db.json"
        self._write(
            tmp_path / "golden", name, {"PORT": {"Ethernet4": {"speed": "100000"}}}
        )
        self._write(
            tmp_path / "export", name, {"PORT": {"Ethernet4": {"speed": "100"}}}
        )

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")

        assert not result.ok
        mismatch = result.mismatched[name]
        assert mismatch.paths == ["PORT|Ethernet4.speed: golden '100000', actual '100'"]
        assert '-      "speed": "100000"' in mismatch.diff
        assert '+      "speed": "100"' in mismatch.diff

    def test_non_json_files_are_ignored(self, tmp_path):
        config = {"PORT": {}}
        self._write(tmp_path / "golden", "osism_sw1_config_db.json", config)
        self._write(tmp_path / "export", "osism_sw1_config_db.json", config)
        (tmp_path / "export" / "firmware_sw1.bin").write_text("not json")

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")

        assert result.ok

    def test_report_distinguishes_failure_categories(self, tmp_path):
        self._write(tmp_path / "golden", "osism_sw1_config_db.json", {"A": {}})
        self._write(tmp_path / "golden", "osism_sw2_config_db.json", {})
        self._write(tmp_path / "export", "osism_sw1_config_db.json", {"B": {}})
        self._write(tmp_path / "export", "osism_sw3_config_db.json", {})

        result = compare_dirs(tmp_path / "golden", tmp_path / "export")
        report = result.report()

        assert "osism_sw2_config_db.json" in report
        assert "generation or export failed" in report
        assert "osism_sw3_config_db.json" in report
        assert "unexpected extra" in report
        assert "osism_sw1_config_db.json" in report
        assert "A: only in golden" in report


class TestRegenerate:
    def test_copies_exports_to_golden_canonically(self, tmp_path):
        export = tmp_path / "export"
        golden = tmp_path / "golden"
        export.mkdir()
        (export / "osism_sw1_config_db.json").write_text('{"B": {}, "A": {}}')

        regenerate(golden, export)

        content = (golden / "osism_sw1_config_db.json").read_text()
        assert content == '{\n  "A": {},\n  "B": {}\n}\n'

    def test_removes_stale_golden_files(self, tmp_path):
        export = tmp_path / "export"
        golden = tmp_path / "golden"
        export.mkdir()
        golden.mkdir()
        (export / "osism_sw1_config_db.json").write_text("{}")
        (golden / "osism_gone_config_db.json").write_text("{}")

        regenerate(golden, export)

        assert not (golden / "osism_gone_config_db.json").exists()
        assert (golden / "osism_sw1_config_db.json").exists()

    def test_ignores_non_json_exports(self, tmp_path):
        export = tmp_path / "export"
        golden = tmp_path / "golden"
        export.mkdir()
        (export / "firmware_sw1.bin").write_text("binary")
        (export / "osism_sw1_config_db.json").write_text("{}")

        regenerate(golden, export)

        assert not (golden / "firmware_sw1.bin").exists()


class TestMain:
    @staticmethod
    def _dirs(tmp_path, golden_config, export_config):
        golden = tmp_path / "golden"
        export = tmp_path / "export"
        golden.mkdir()
        export.mkdir()
        name = "osism_sw1_config_db.json"
        (golden / name).write_text(json.dumps(golden_config))
        (export / name).write_text(json.dumps(export_config))
        return golden, export

    def test_matching_dirs_exit_zero(self, tmp_path, capsys):
        golden, export = self._dirs(tmp_path, {"A": {}}, {"A": {}})

        rc = main(["--golden", str(golden), "--export", str(export)])

        assert rc == 0
        assert "OK" in capsys.readouterr().out

    def test_mismatch_exits_nonzero_and_prints_report(self, tmp_path, capsys):
        golden, export = self._dirs(tmp_path, {"A": {}}, {"B": {}})

        rc = main(["--golden", str(golden), "--export", str(export)])

        assert rc == 1
        out = capsys.readouterr().out
        assert "A: only in golden" in out

    def test_regenerate_rewrites_goldens_and_exits_zero(self, tmp_path):
        golden, export = self._dirs(tmp_path, {"A": {}}, {"B": {}})

        rc = main(["--golden", str(golden), "--export", str(export), "--regenerate"])

        assert rc == 0
        name = "osism_sw1_config_db.json"
        assert json.loads((golden / name).read_text()) == {"B": {}}
