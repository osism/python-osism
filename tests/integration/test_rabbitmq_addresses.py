# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``get_rabbitmq_node_addresses()`` interface resolution.

The unit tests in ``tests/unit/utils/test_rabbitmq.py`` cover the same scenarios
against mocks: ``subprocess`` and the Redis client are both replaced, so what
they verify is the shape of the calls the function makes, not whether Ansible
agrees with it. That distinction is not academic here. The value the function
has to resolve, ``internal_interface``, is frequently Jinja-valued, and its
meaning is defined by Ansible's templating and by how Ansible names interface
facts -- neither of which a mock can speak for.

These tests therefore drive the public function with the real collaborators: a
live Redis holding the cached facts, a real inventory on disk, and the real
``ansible-inventory`` / ``ansible`` binaries. Each case is a value shape an
operator actually writes. Because they target the public function rather than
its internals, they stay meaningful across changes to how the resolution is
implemented.

Requires a reachable Redis (see ``conftest.py``) and ``ansible`` on PATH;
``ansible-core`` is not a dependency of this package -- it comes from the
container images -- so the ansible-dependent cases skip without it.
"""

import json
import os
import shutil

import pytest

from osism import utils
from osism.utils import rabbitmq

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _require_ansible():
    """Skip unless ``ansible`` is on PATH.

    Set OSISM_REQUIRE_ANSIBLE to turn the skip into a failure, the way
    OSISM_REQUIRE_REDIS does for Redis, so a job that is meant to have Ansible
    cannot pass by skipping everything.
    """
    if shutil.which("ansible-inventory"):
        return
    if os.environ.get("OSISM_REQUIRE_ANSIBLE"):
        pytest.fail("OSISM_REQUIRE_ANSIBLE is set but 'ansible' is not on PATH")
    pytest.skip("ansible not on PATH")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    """Build a one-host rabbitmq inventory, seed its facts, and point the code at it.

    One host per scenario keeps the assertion unambiguous: the function skips
    hosts it cannot resolve and returns the rest, so a multi-host inventory
    would let a failure hide behind a success.
    """
    seeded = []

    def _build(host, variables, facts):
        inventory = tmp_path / "hosts.yml"
        inventory.write_text(
            "all:\n"
            "  children:\n"
            "    rabbitmq:\n"
            "      hosts:\n"
            # RFC 5737 documentation range: unreachable on purpose, so a
            # resolution path that tried to connect would fail here rather
            # than pass quietly.
            f"        {host}: {{ansible_host: 192.0.2.10}}\n"
        )
        host_vars = tmp_path / "host_vars"
        host_vars.mkdir(exist_ok=True)
        (host_vars / f"{host}.yml").write_text(json.dumps(variables))

        # The inventory path is hardcoded to /ansible/inventory/hosts.yml, which
        # only exists inside the container images.
        monkeypatch.setattr(
            rabbitmq, "get_inventory_path", lambda *args, **kwargs: str(inventory)
        )

        key = f"ansible_facts{host}"
        utils.redis.set(key, json.dumps(facts))
        seeded.append(key)
        return host

    yield _build

    for key in seeded:
        utils.redis.delete(key)


def test_literal_interface(scenario):
    host = scenario(
        "ctl1",
        {"internal_interface": "eth0"},
        {"ansible_eth0": {"ipv4": {"address": "10.0.0.5"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.5", host)]


def test_fact_derived_interface(scenario):
    # internal_interface is a Jinja reference into the facts.
    host = scenario(
        "ctl2",
        {"internal_interface": "{{ ansible_local.network_devices.management }}"},
        {
            "ansible_local": {"network_devices": {"management": "bond_mgmt"}},
            "ansible_bond_mgmt": {"ipv4": {"address": "192.168.16.10"}},
        },
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("192.168.16.10", host)]


def test_dotted_interface_name(scenario):
    # Ansible replaces "-" with "_" in fact names and keeps dots, so a VLAN
    # interface named bond0.1034 is cached as ansible_bond0.1034.
    host = scenario(
        "ctl3",
        {"internal_interface": "bond0.1034"},
        {"ansible_bond0.1034": {"ipv4": {"address": "10.74.34.12"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.74.34.12", host)]


def test_dashed_interface_name(scenario):
    host = scenario(
        "ctl4",
        {"internal_interface": "br-ex"},
        {"ansible_br_ex": {"ipv4": {"address": "10.74.34.13"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.74.34.13", host)]


def test_interface_from_inventory_variable(scenario):
    # The shape reported in osism/issues#1425: internal_interface refers to an
    # inventory variable, which is itself a literal plus a template. Nothing
    # here is a fact, which is why resolving it needs Ansible's templating
    # rather than a walk through the facts. Marked xfail until that landed.
    host = scenario(
        "ctl5",
        {
            "internal_interface": "{{ dataplane_vlan }}",
            "dataplane_id": "1034",
            "dataplane_vlan": "vlan{{ dataplane_id }}",
        },
        {"ansible_vlan1034": {"ipv4": {"address": "10.74.34.11"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.74.34.11", host)]


def test_console_interface_fallback(scenario):
    # osism/defaults resolves this address as
    # internal_interface|default(console_interface), so a host that sets only
    # console_interface resolves in the deployment and has to resolve here.
    host = scenario(
        "ctl9",
        {"console_interface": "eth7"},
        {"ansible_eth7": {"ipv4": {"address": "10.9.9.9"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.9.9.9", host)]


def test_missing_internal_interface_yields_no_addresses(scenario):
    scenario("ctl6", {}, {"ansible_eth0": {"ipv4": {"address": "10.0.0.9"}}})
    assert rabbitmq.get_rabbitmq_node_addresses() is None


def test_interface_without_matching_fact_yields_no_addresses(scenario):
    scenario(
        "ctl7",
        {"internal_interface": "vlan999"},
        {"ansible_eth0": {"ipv4": {"address": "10.0.0.9"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() is None


def test_interface_fact_without_ipv4_yields_no_addresses(scenario):
    # The interface is in the facts but carries no ipv4 block, e.g. an
    # unconfigured NIC. The address cannot be derived, so the host is skipped.
    scenario(
        "ctl10",
        {"internal_interface": "eth0"},
        {"ansible_eth0": {"macaddress": "00:00:5e:00:53:00"}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() is None


def test_ipv4_without_address_yields_no_addresses(scenario):
    scenario(
        "ctl11",
        {"internal_interface": "eth0"},
        {"ansible_eth0": {"ipv4": {"netmask": "255.255.255.0"}}},
    )
    assert rabbitmq.get_rabbitmq_node_addresses() is None


def test_no_facts_in_cache_yields_no_addresses(scenario, tmp_path, monkeypatch):
    # Same inventory, but the cache entry removed: the function must report the
    # missing facts rather than fall back to some other source.
    host = scenario(
        "ctl8",
        {"internal_interface": "eth0"},
        {"ansible_eth0": {"ipv4": {"address": "10.0.0.5"}}},
    )
    utils.redis.delete(f"ansible_facts{host}")
    assert rabbitmq.get_rabbitmq_node_addresses() is None
