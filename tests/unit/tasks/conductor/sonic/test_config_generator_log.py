# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_log_server_configuration`` in ``config_generator``."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.config_generator import _add_log_server_configuration

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


def _device_with_ctx(**ctx):
    return SimpleNamespace(name="leaf-1", config_context=ctx)


def test_add_log_server_configuration_defaults():
    config = {}
    device = _device_with_ctx(_segment_log_server_hosts=["10.1.1.1", "10.1.1.2"])

    _add_log_server_configuration(config, device)

    for host in ("10.1.1.1", "10.1.1.2"):
        assert config["SYSLOG_SERVER"][host] == {
            "message-type": "log",
            "protocol": "udp",
            "remote-port": "514",
            "severity": "info",
            "vrf_name": "mgmt",
        }


@pytest.mark.parametrize(
    "proto_in, proto_out",
    [("tcp", "tcp"), ("TCP", "tcp"), ("Udp", "udp")],
)
def test_add_log_server_configuration_protocol_lowercased(proto_in, proto_out):
    config = {}
    device = _device_with_ctx(
        _segment_log_server_hosts=["10.1.1.1"],
        _segment_log_server_proto=proto_in,
    )

    _add_log_server_configuration(config, device)

    assert config["SYSLOG_SERVER"]["10.1.1.1"]["protocol"] == proto_out


@pytest.mark.parametrize(
    "severity_in, severity_out",
    [
        ("warning", "warn"),
        ("WARNING", "warn"),
        ("informational", "info"),
        ("err", "error"),
        ("critical", "crit"),
        ("warn", "warn"),
        ("info", "info"),
    ],
)
def test_add_log_server_configuration_severity_aliases(severity_in, severity_out):
    config = {}
    device = _device_with_ctx(
        _segment_log_server_hosts=["10.1.1.1"],
        _segment_log_server_severity=severity_in,
    )

    _add_log_server_configuration(config, device)

    assert config["SYSLOG_SERVER"]["10.1.1.1"]["severity"] == severity_out


def test_add_log_server_configuration_custom_severity_and_vrf():
    config = {}
    device = _device_with_ctx(
        _segment_log_server_hosts=["10.1.1.1"],
        _segment_log_server_severity="debug",
        _segment_log_server_vrf="default",
    )

    _add_log_server_configuration(config, device)

    entry = config["SYSLOG_SERVER"]["10.1.1.1"]
    assert entry["severity"] == "debug"
    assert entry["vrf_name"] == "default"


@pytest.mark.parametrize("hosts_value", [[], None])
def test_add_log_server_configuration_no_hosts_skips_section(hosts_value):
    config = {}
    ctx = {} if hosts_value is None else {"_segment_log_server_hosts": hosts_value}
    device = _device_with_ctx(**ctx)

    _add_log_server_configuration(config, device)

    assert "SYSLOG_SERVER" not in config
