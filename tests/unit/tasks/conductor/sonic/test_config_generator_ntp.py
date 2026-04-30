# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_ntp_configuration`` (per-device NTP wiring)."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import _add_ntp_configuration

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


# ---------------------------------------------------------------------------
# _add_ntp_configuration
# ---------------------------------------------------------------------------


def test_add_ntp_configuration_with_metalbox_ip(mocker):
    mocker.patch.object(
        config_generator,
        "_get_metalbox_ip_for_device",
        return_value="10.0.0.1",
    )
    config = {"NTP_SERVER": {}}

    _add_ntp_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["NTP_SERVER"] == {
        "10.0.0.1": {"maxpoll": "10", "minpoll": "6", "prefer": "false"}
    }


def test_add_ntp_configuration_no_metalbox_ip_leaves_config_untouched(mocker):
    mocker.patch.object(
        config_generator, "_get_metalbox_ip_for_device", return_value=None
    )
    config = {"NTP_SERVER": {}}

    _add_ntp_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["NTP_SERVER"] == {}


def test_add_ntp_configuration_helper_exception_swallowed(mocker):
    """A failure inside the helper must never propagate out of the orchestrator —
    NTP being unconfigured is a soft failure."""
    mocker.patch.object(
        config_generator,
        "_get_metalbox_ip_for_device",
        side_effect=RuntimeError("kaboom"),
    )
    config = {"NTP_SERVER": {}}

    _add_ntp_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["NTP_SERVER"] == {}
