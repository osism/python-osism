# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_dns_configuration`` in ``config_generator``."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import _add_dns_configuration

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


def test_add_dns_configuration_with_metalbox_ip(mocker):
    mocker.patch.object(
        config_generator,
        "_get_metalbox_ip_for_device",
        return_value="10.0.0.1",
    )
    config = {"DNS_NAMESERVER": {}}

    _add_dns_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["DNS_NAMESERVER"] == {"10.0.0.1": {}}


def test_add_dns_configuration_no_metalbox_ip(mocker):
    mocker.patch.object(
        config_generator, "_get_metalbox_ip_for_device", return_value=None
    )
    config = {"DNS_NAMESERVER": {}}

    _add_dns_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["DNS_NAMESERVER"] == {}


def test_add_dns_configuration_helper_exception_swallowed(mocker):
    mocker.patch.object(
        config_generator,
        "_get_metalbox_ip_for_device",
        side_effect=RuntimeError("kaboom"),
    )
    config = {"DNS_NAMESERVER": {}}

    _add_dns_configuration(config, SimpleNamespace(name="leaf-1"))

    assert config["DNS_NAMESERVER"] == {}
