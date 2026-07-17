# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the E2E generation driver.

The driver's assertion logic (expected device set, loguru error capture)
is pure and tested here with an injected sync callable; only the real
``sync_sonic`` import is exercised in the actual E2E run.
"""

from loguru import logger

from tests.e2e.generate import expected_devices, main, run_generation


class TestExpectedDevices:
    def test_strips_prefix_and_suffix(self, tmp_path):
        (tmp_path / "osism_testbed-switch-0_config_db.json").write_text("{}")
        (tmp_path / "osism_testbed-switch-1_config_db.json").write_text("{}")

        assert expected_devices(tmp_path, "osism_", "_config_db.json") == {
            "testbed-switch-0",
            "testbed-switch-1",
        }

    def test_ignores_non_json_and_foreign_names(self, tmp_path):
        (tmp_path / "osism_sw1_config_db.json").write_text("{}")
        (tmp_path / "README.md").write_text("")
        (tmp_path / "other_sw2.json").write_text("{}")

        assert expected_devices(tmp_path, "osism_", "_config_db.json") == {"sw1"}


class TestRunGeneration:
    def test_returns_configs_and_no_errors_for_clean_sync(self):
        configs, errors = run_generation(lambda: {"sw1": {"PORT": {}}})

        assert configs == {"sw1": {"PORT": {}}}
        assert errors == []

    def test_captures_loguru_errors_during_sync(self):
        def failing_sync():
            logger.error("Failed to sync SONiC configuration for device sw1: boom")
            return {}

        configs, errors = run_generation(failing_sync)

        assert configs == {}
        assert len(errors) == 1
        assert "boom" in errors[0]

    def test_does_not_capture_non_error_levels(self):
        def chatty_sync():
            logger.info("processing")
            logger.warning("odd but fine")
            return {"sw1": {}}

        _, errors = run_generation(chatty_sync)

        assert errors == []

    def test_sink_is_removed_after_run(self):
        _, errors = run_generation(lambda: {})
        logger.error("logged after the run")

        assert errors == []


class TestMain:
    def test_success_returns_zero(self, tmp_path, capsys):
        (tmp_path / "osism_sw1_config_db.json").write_text("{}")

        rc = main(["--golden", str(tmp_path)], sync=lambda: {"sw1": {"PORT": {}}})

        assert rc == 0

    def test_captured_errors_fail_the_run(self, tmp_path, capsys):
        (tmp_path / "osism_sw1_config_db.json").write_text("{}")

        def failing_sync():
            logger.error("device sw1 exploded")
            return {"sw1": {}}

        rc = main(["--golden", str(tmp_path)], sync=failing_sync)

        assert rc == 1
        assert "device sw1 exploded" in capsys.readouterr().out

    def test_device_set_mismatch_fails_and_names_devices(self, tmp_path, capsys):
        (tmp_path / "osism_sw1_config_db.json").write_text("{}")
        (tmp_path / "osism_sw2_config_db.json").write_text("{}")

        rc = main(["--golden", str(tmp_path)], sync=lambda: {"sw1": {"PORT": {}}})

        assert rc == 1
        assert "sw2" in capsys.readouterr().out

    def test_empty_config_counts_as_failure(self, tmp_path, capsys):
        (tmp_path / "osism_sw1_config_db.json").write_text("{}")

        rc = main(["--golden", str(tmp_path)], sync=lambda: {"sw1": {}})

        assert rc == 1
        assert "sw1" in capsys.readouterr().out

    def test_no_expect_skips_device_set_check(self, capsys):
        rc = main(["--no-expect"], sync=lambda: {"sw1": {"PORT": {}}})

        assert rc == 0
