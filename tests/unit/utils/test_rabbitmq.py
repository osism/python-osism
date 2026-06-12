# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.rabbitmq``.

Covers ``get_rabbitmq_node_addresses`` (inventory + host discovery, per-host
interface resolution including Jinja2 template traversal, and result
aggregation) and ``load_rabbitmq_password`` (secrets-file loading and
normalization), plus the ``RABBITMQ_USER`` module constant.

The lazy ``redis`` attribute lives on the ``osism.utils`` package and is read
inside the function via a function-local ``from osism import utils``. Patching
``osism.utils.rabbitmq.utils.redis`` does not work because the ``rabbitmq``
module never gains a ``utils`` global; instead the cached attribute is seeded
on the package namespace with ``mocker.patch.dict`` so the lazy ``__getattr__``
(which would open a real Redis connection) is bypassed.
"""

import json
import subprocess

import pytest

import osism.utils as utils_pkg
from osism.utils import rabbitmq

# A valid group-listing payload for the first ``ansible-inventory`` call. The
# content is irrelevant because ``get_hosts_from_inventory`` is mocked; only the
# bytes need to parse as JSON.
_GROUP_LISTING = json.dumps({"rabbitmq": {"hosts": ["host1"]}}).encode()


def _encode(payload):
    """Encode a payload the way ``ansible-inventory`` / Redis return it."""
    return json.dumps(payload).encode()


def _hostvars(interface):
    """Build a ``--host`` hostvars payload carrying ``internal_interface``."""
    return _encode({"internal_interface": interface})


def _facts(interface_key, address):
    """Build an ansible-facts payload exposing one interface with an IPv4."""
    return _encode({interface_key: {"ipv4": {"address": address}}})


def _setup_addresses(mocker, *, hosts, redis_side_effect, check_output):
    """Wire up every collaborator of ``get_rabbitmq_node_addresses``.

    Returns the fake Redis client so individual tests can assert on the cache
    keys it was queried with.
    """
    fake_redis = mocker.MagicMock()
    fake_redis.get.side_effect = redis_side_effect
    # Seed the lazy attribute on the package so ``utils.redis`` resolves to the
    # mock without triggering ``__getattr__`` -> ``_init_redis()``.
    mocker.patch.dict(utils_pkg.__dict__, {"redis": fake_redis})
    mocker.patch("osism.utils.rabbitmq.get_inventory_path", return_value="/inv")
    mocker.patch(
        "osism.utils.rabbitmq.get_hosts_from_inventory", return_value=list(hosts)
    )
    mocker.patch(
        "osism.utils.rabbitmq.subprocess.check_output", side_effect=check_output
    )
    return fake_redis


def _error_messages(loguru_logs):
    return [record["message"] for record in loguru_logs if record["level"] == "ERROR"]


def _assert_error_logged(loguru_logs, substring):
    """Assert at least one ERROR was logged and one of them mentions ``substring``."""
    errors = _error_messages(loguru_logs)
    assert errors, "expected at least one ERROR log record"
    assert any(substring in message for message in errors), errors


# ---------------------------------------------------------------------------
# get_rabbitmq_node_addresses: inventory & host discovery
# ---------------------------------------------------------------------------


def test_two_hosts_returned_in_alphabetical_order(mocker, loguru_logs):
    fake_redis = _setup_addresses(
        mocker,
        hosts=["host2", "host1"],
        redis_side_effect=[
            _facts("ansible_eth0", "10.0.0.5"),
            _facts("ansible_eth0", "10.0.0.6"),
        ],
        check_output=[_GROUP_LISTING, _hostvars("eth0"), _hostvars("eth0")],
    )

    result = rabbitmq.get_rabbitmq_node_addresses()

    assert result == [("10.0.0.5", "host1"), ("10.0.0.6", "host2")]
    assert _error_messages(loguru_logs) == []
    # Hosts are sorted before processing, so the cache is queried host1 first.
    assert fake_redis.get.call_args_list == [
        mocker.call("ansible_factshost1"),
        mocker.call("ansible_factshost2"),
    ]


def test_no_hosts_in_group_returns_none(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=[],
        redis_side_effect=[],
        check_output=[_GROUP_LISTING],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "No hosts found in rabbitmq group")


def test_group_listing_called_process_error_returns_none(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[],
        check_output=[subprocess.CalledProcessError(1, "ansible-inventory")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "Failed to query ansible inventory")


def test_invalid_group_json_returns_none(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[],
        check_output=[b"{not valid json"],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "Failed to parse inventory data")


def test_outer_generic_exception_returns_none(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[],
        check_output=[_GROUP_LISTING],
    )
    mocker.patch(
        "osism.utils.rabbitmq.get_inventory_path",
        side_effect=RuntimeError("boom"),
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "Failed to get RabbitMQ node addresses")


# ---------------------------------------------------------------------------
# get_rabbitmq_node_addresses: per-host resolution
# ---------------------------------------------------------------------------


def test_missing_facts_in_cache_skips_host_and_continues(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1", "host2"],
        redis_side_effect=[None, _facts("ansible_eth0", "10.0.0.6")],
        check_output=[_GROUP_LISTING, _hostvars("eth0")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.6", "host2")]
    _assert_error_logged(loguru_logs, "No ansible facts found in cache for host1")


def test_no_internal_interface_skips_host(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_facts("ansible_eth0", "10.0.0.5")],
        check_output=[_GROUP_LISTING, _encode({})],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "internal_interface not found in hostvars")


def test_literal_interface_used_directly(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_facts("ansible_eth0", "10.0.0.5")],
        check_output=[_GROUP_LISTING, _hostvars("eth0")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.5", "host1")]
    assert _error_messages(loguru_logs) == []


def test_jinja_template_resolved_from_facts(mocker, loguru_logs):
    facts = {
        "ansible_local": {"testbed_network_devices": {"management": "eth1"}},
        "ansible_eth1": {"ipv4": {"address": "10.0.0.8"}},
    }
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_encode(facts)],
        check_output=[
            _GROUP_LISTING,
            _hostvars("{{ ansible_local.testbed_network_devices.management }}"),
        ],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.8", "host1")]
    assert _error_messages(loguru_logs) == []


@pytest.mark.parametrize(
    "management_value",
    [None, {"nested": "x"}, 42],
    ids=["none", "dict", "int"],
)
def test_template_resolving_to_non_string_skips_host(
    mocker, loguru_logs, management_value
):
    facts = {
        "ansible_local": {"testbed_network_devices": {"management": management_value}}
    }
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_encode(facts)],
        check_output=[
            _GROUP_LISTING,
            _hostvars("{{ ansible_local.testbed_network_devices.management }}"),
        ],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "Could not resolve template")


def test_template_traversal_hits_non_dict_skips_host(mocker, loguru_logs):
    # ``ansible_local`` is a string, so walking ``.testbed_network_devices``
    # leaves the dict path and the template resolves to None.
    facts = {"ansible_local": "not-a-dict"}
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_encode(facts)],
        check_output=[
            _GROUP_LISTING,
            _hostvars("{{ ansible_local.testbed_network_devices.management }}"),
        ],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "Could not resolve template")


@pytest.mark.parametrize(
    "interface,normalized_key",
    [("eth0.100", "ansible_eth0_100"), ("eth-0", "ansible_eth_0")],
)
def test_interface_name_normalized_for_fact_lookup(
    mocker, loguru_logs, interface, normalized_key
):
    # Facts are only stored under the normalized key, so a correct lookup is
    # the only way the address can be found.
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_facts(normalized_key, "10.0.0.7")],
        check_output=[_GROUP_LISTING, _hostvars(interface)],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.7", "host1")]
    assert _error_messages(loguru_logs) == []


def test_normalized_interface_key_missing_skips_host(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_facts("ansible_eth1", "10.0.0.5")],
        check_output=[_GROUP_LISTING, _hostvars("eth0")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "not found in ansible facts")


def test_interface_without_ipv4_skips_host(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_encode({"ansible_eth0": {"mtu": 1500}})],
        check_output=[_GROUP_LISTING, _hostvars("eth0")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "No IPv4 address found")


@pytest.mark.parametrize(
    "ipv4_info",
    [{"address": ""}, {"netmask": "255.255.255.0"}],
    ids=["empty_address", "missing_address"],
)
def test_ipv4_without_address_skips_host(mocker, loguru_logs, ipv4_info):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[_encode({"ansible_eth0": {"ipv4": ipv4_info}})],
        check_output=[_GROUP_LISTING, _hostvars("eth0")],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(loguru_logs, "No IPv4 address found")


# ---------------------------------------------------------------------------
# get_rabbitmq_node_addresses: aggregate results
# ---------------------------------------------------------------------------


def test_all_hosts_skipped_returns_none(mocker, loguru_logs):
    _setup_addresses(
        mocker,
        hosts=["host1"],
        redis_side_effect=[None],
        check_output=[_GROUP_LISTING],
    )

    assert rabbitmq.get_rabbitmq_node_addresses() is None
    _assert_error_logged(
        loguru_logs, "Could not retrieve address for any RabbitMQ node"
    )


# ---------------------------------------------------------------------------
# load_rabbitmq_password
# ---------------------------------------------------------------------------


def _setup_password(mocker, *, exists=True, load_yaml=None, load_raises=None):
    mocker.patch("osism.utils.rabbitmq.os.path.exists", return_value=exists)
    if load_raises is not None:
        mocker.patch(
            "osism.tasks.conductor.utils.load_yaml_file", side_effect=load_raises
        )
    else:
        mocker.patch(
            "osism.tasks.conductor.utils.load_yaml_file", return_value=load_yaml
        )


def test_password_file_missing_returns_none(mocker, loguru_logs):
    _setup_password(mocker, exists=False)

    assert rabbitmq.load_rabbitmq_password() is None
    _assert_error_logged(loguru_logs, "Secrets file not found")


def test_password_empty_secrets_returns_none(mocker, loguru_logs):
    _setup_password(mocker, load_yaml=None)

    assert rabbitmq.load_rabbitmq_password() is None
    _assert_error_logged(loguru_logs, "Empty or invalid secrets file")


def test_password_non_dict_secrets_returns_none(mocker, loguru_logs):
    _setup_password(mocker, load_yaml=["not", "a", "dict"])

    assert rabbitmq.load_rabbitmq_password() is None
    _assert_error_logged(loguru_logs, "Empty or invalid secrets file")


def test_password_missing_key_returns_none(mocker, loguru_logs):
    _setup_password(mocker, load_yaml={"other_password": "x"})

    assert rabbitmq.load_rabbitmq_password() is None
    _assert_error_logged(loguru_logs, "rabbitmq_password not found in secrets file")


def test_password_whitespace_stripped(mocker, loguru_logs):
    _setup_password(mocker, load_yaml={"rabbitmq_password": "  hunter2  "})

    assert rabbitmq.load_rabbitmq_password() == "hunter2"
    assert _error_messages(loguru_logs) == []


def test_password_int_coerced_to_string(mocker, loguru_logs):
    _setup_password(mocker, load_yaml={"rabbitmq_password": 42})

    assert rabbitmq.load_rabbitmq_password() == "42"
    assert _error_messages(loguru_logs) == []


def test_password_load_yaml_raises_returns_none(mocker, loguru_logs):
    _setup_password(mocker, load_raises=RuntimeError("boom"))

    assert rabbitmq.load_rabbitmq_password() is None
    _assert_error_logged(loguru_logs, "Failed to load RabbitMQ password")


# ---------------------------------------------------------------------------
# module constant
# ---------------------------------------------------------------------------


def test_rabbitmq_user_constant():
    assert rabbitmq.RABBITMQ_USER == "openstack"
