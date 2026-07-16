# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.rabbitmq``.

Tests are grouped into one class per function: ``TestGetRabbitmqNodeAddresses``
(inventory + host discovery, per-host interface resolution including Jinja2
template traversal, and result aggregation) and ``TestLoadRabbitmqPassword``
(secrets-file loading and normalization), plus the ``RABBITMQ_USER`` module
constant. The collaborators of each function are wired up by the
``setup_addresses`` / ``setup_password`` factory fixtures.

The lazy ``redis`` attribute lives on the ``osism.utils`` package and is read
inside the function via a function-local ``from osism import utils``. Patching
``osism.utils.rabbitmq.utils.redis`` does not work because the ``rabbitmq``
module never gains a ``utils`` global; instead the cached attribute is seeded
on the package namespace with ``mocker.patch.dict`` so the lazy ``__getattr__``
(which would open a real Redis connection) is bypassed.
"""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import call

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


def _error_messages(loguru_logs):
    return [record["message"] for record in loguru_logs if record["level"] == "ERROR"]


def _assert_error_logged(loguru_logs, substring):
    """Assert at least one ERROR was logged and one of them mentions ``substring``."""
    errors = _error_messages(loguru_logs)
    assert errors, "expected at least one ERROR log record"
    assert any(substring in message for message in errors), errors


@pytest.fixture
def setup_addresses(mocker):
    """Factory wiring up every collaborator of ``get_rabbitmq_node_addresses``.

    Returns the collaborator mocks so individual tests can assert on the cache
    keys and command lines they were invoked with.
    """

    def _setup(*, hosts, redis_side_effect, check_output):
        fake_redis = mocker.MagicMock()
        fake_redis.get.side_effect = redis_side_effect
        # Seed the lazy attribute on the package so ``utils.redis`` resolves to
        # the mock without triggering ``__getattr__`` -> ``_init_redis()``.
        mocker.patch.dict(utils_pkg.__dict__, {"redis": fake_redis})
        get_inventory_path = mocker.patch(
            "osism.utils.rabbitmq.get_inventory_path", return_value="/inv"
        )
        mocker.patch(
            "osism.utils.rabbitmq.get_hosts_from_inventory", return_value=list(hosts)
        )
        check_output_mock = mocker.patch(
            "osism.utils.rabbitmq.subprocess.check_output", side_effect=check_output
        )
        return SimpleNamespace(
            redis=fake_redis,
            get_inventory_path=get_inventory_path,
            check_output=check_output_mock,
        )

    return _setup


@pytest.fixture
def setup_password(mocker):
    """Factory patching the secrets-file existence check and the YAML loader."""

    def _setup(*, exists=True, load_yaml=None, load_raises=None):
        mocker.patch("osism.utils.rabbitmq.os.path.exists", return_value=exists)
        if load_raises is not None:
            mocker.patch(
                "osism.tasks.conductor.utils.load_yaml_file", side_effect=load_raises
            )
        else:
            mocker.patch(
                "osism.tasks.conductor.utils.load_yaml_file", return_value=load_yaml
            )

    return _setup


class TestGetRabbitmqNodeAddresses:
    # -- inventory & host discovery -----------------------------------------

    def test_two_hosts_returned_in_alphabetical_order(
        self, setup_addresses, loguru_logs
    ):
        mocks = setup_addresses(
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
        # Hosts are sorted before processing, so the cache is queried host1
        # first.
        assert mocks.redis.get.call_args_list == [
            call("ansible_factshost1"),
            call("ansible_factshost2"),
        ]

    def test_inventory_queries_use_expected_arguments(
        self, setup_addresses, loguru_logs
    ):
        mocks = setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_facts("ansible_eth0", "10.0.0.5")],
            check_output=[_GROUP_LISTING, _hostvars("eth0")],
        )

        rabbitmq.get_rabbitmq_node_addresses()

        # ``--limit rabbitmq`` is the only thing scoping the listing to the
        # rabbitmq group; ``get_hosts_from_inventory`` does no group filtering.
        assert "--limit rabbitmq" in mocks.check_output.call_args_list[0].args[0]
        assert "--host host1" in mocks.check_output.call_args_list[1].args[0]
        # The hostvars lookup must not use the minified inventory, which omits
        # hostvars such as ``internal_interface``.
        assert mocks.get_inventory_path.call_args_list == [
            call("/ansible/inventory/hosts.yml"),
            call("/ansible/inventory/hosts.yml", prefer_minified=False),
        ]

    def test_no_hosts_in_group_returns_none(self, setup_addresses, loguru_logs):
        setup_addresses(
            hosts=[],
            redis_side_effect=[],
            check_output=[_GROUP_LISTING],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "No hosts found in rabbitmq group")

    def test_group_listing_called_process_error_returns_none(
        self, setup_addresses, loguru_logs
    ):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[],
            check_output=[subprocess.CalledProcessError(1, "ansible-inventory")],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "Failed to query ansible inventory")

    def test_invalid_group_json_returns_none(self, setup_addresses, loguru_logs):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[],
            check_output=[b"{not valid json"],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "Failed to parse inventory data")

    def test_outer_generic_exception_returns_none(self, setup_addresses, loguru_logs):
        mocks = setup_addresses(
            hosts=["host1"],
            redis_side_effect=[],
            check_output=[_GROUP_LISTING],
        )
        mocks.get_inventory_path.side_effect = RuntimeError("boom")

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "Failed to get RabbitMQ node addresses")

    # -- per-host resolution -------------------------------------------------

    def test_missing_facts_in_cache_skips_host_and_continues(
        self, setup_addresses, loguru_logs
    ):
        setup_addresses(
            hosts=["host1", "host2"],
            redis_side_effect=[None, _facts("ansible_eth0", "10.0.0.6")],
            check_output=[_GROUP_LISTING, _hostvars("eth0")],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.6", "host2")]
        _assert_error_logged(loguru_logs, "No ansible facts found in cache for host1")

    @pytest.mark.parametrize(
        "redis_side_effect,check_output",
        [
            pytest.param(
                [_facts("ansible_eth0", "10.0.0.5"), b"{corrupt facts"],
                [_GROUP_LISTING, _hostvars("eth0")],
                id="corrupt_cached_facts",
            ),
            pytest.param(
                [
                    _facts("ansible_eth0", "10.0.0.5"),
                    _facts("ansible_eth0", "10.0.0.6"),
                ],
                [
                    _GROUP_LISTING,
                    _hostvars("eth0"),
                    subprocess.CalledProcessError(1, "ansible-inventory"),
                ],
                id="hostvars_query_fails",
            ),
            pytest.param(
                [
                    _facts("ansible_eth0", "10.0.0.5"),
                    _facts("ansible_eth0", "10.0.0.6"),
                ],
                [_GROUP_LISTING, _hostvars("eth0"), b"{not valid json"],
                id="corrupt_hostvars_json",
            ),
            pytest.param(
                [
                    _facts("ansible_eth0", "10.0.0.5"),
                    _facts("ansible_eth0", "10.0.0.6"),
                ],
                [_GROUP_LISTING, _hostvars("eth0"), _hostvars(["eth0"])],
                id="non_string_internal_interface",
            ),
        ],
    )
    def test_per_host_failure_keeps_addresses_of_other_hosts(
        self, setup_addresses, loguru_logs, redis_side_effect, check_output
    ):
        # host1 resolves before host2 fails; the failure must only drop host2.
        setup_addresses(
            hosts=["host1", "host2"],
            redis_side_effect=redis_side_effect,
            check_output=check_output,
        )

        assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.5", "host1")]
        _assert_error_logged(loguru_logs, "Failed to resolve address for host2")

    def test_no_internal_interface_skips_host(self, setup_addresses, loguru_logs):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_facts("ansible_eth0", "10.0.0.5")],
            check_output=[_GROUP_LISTING, _encode({})],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "internal_interface not found in hostvars")

    def test_literal_interface_used_directly(self, setup_addresses, loguru_logs):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_facts("ansible_eth0", "10.0.0.5")],
            check_output=[_GROUP_LISTING, _hostvars("eth0")],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.5", "host1")]
        assert _error_messages(loguru_logs) == []

    def test_jinja_template_resolved_from_facts(self, setup_addresses, loguru_logs):
        facts = {
            "ansible_local": {"testbed_network_devices": {"management": "eth1"}},
            "ansible_eth1": {"ipv4": {"address": "10.0.0.8"}},
        }
        setup_addresses(
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
        self, setup_addresses, loguru_logs, management_value
    ):
        facts = {
            "ansible_local": {
                "testbed_network_devices": {"management": management_value}
            }
        }
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_encode(facts)],
            check_output=[
                _GROUP_LISTING,
                _hostvars("{{ ansible_local.testbed_network_devices.management }}"),
            ],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "Could not resolve template")

    def test_template_traversal_hits_non_dict_skips_host(
        self, setup_addresses, loguru_logs
    ):
        # ``ansible_local`` is a string, so walking ``.testbed_network_devices``
        # leaves the dict path and the template resolves to None.
        facts = {"ansible_local": "not-a-dict"}
        setup_addresses(
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
        self, setup_addresses, loguru_logs, interface, normalized_key
    ):
        # Facts are only stored under the normalized key, so a correct lookup
        # is the only way the address can be found.
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_facts(normalized_key, "10.0.0.7")],
            check_output=[_GROUP_LISTING, _hostvars(interface)],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() == [("10.0.0.7", "host1")]
        assert _error_messages(loguru_logs) == []

    def test_normalized_interface_key_missing_skips_host(
        self, setup_addresses, loguru_logs
    ):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_facts("ansible_eth1", "10.0.0.5")],
            check_output=[_GROUP_LISTING, _hostvars("eth0")],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "not found in ansible facts")

    def test_interface_without_ipv4_skips_host(self, setup_addresses, loguru_logs):
        setup_addresses(
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
    def test_ipv4_without_address_skips_host(
        self, setup_addresses, loguru_logs, ipv4_info
    ):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[_encode({"ansible_eth0": {"ipv4": ipv4_info}})],
            check_output=[_GROUP_LISTING, _hostvars("eth0")],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(loguru_logs, "No IPv4 address found")

    # -- aggregate results ----------------------------------------------------

    def test_all_hosts_skipped_returns_none(self, setup_addresses, loguru_logs):
        setup_addresses(
            hosts=["host1"],
            redis_side_effect=[None],
            check_output=[_GROUP_LISTING],
        )

        assert rabbitmq.get_rabbitmq_node_addresses() is None
        _assert_error_logged(
            loguru_logs, "Could not retrieve address for any RabbitMQ node"
        )


class TestLoadRabbitmqPassword:
    def test_password_file_missing_returns_none(self, setup_password, loguru_logs):
        setup_password(exists=False)

        assert rabbitmq.load_rabbitmq_password() is None
        _assert_error_logged(loguru_logs, "Secrets file not found")

    def test_password_empty_secrets_returns_none(self, setup_password, loguru_logs):
        setup_password(load_yaml=None)

        assert rabbitmq.load_rabbitmq_password() is None
        _assert_error_logged(loguru_logs, "Empty or invalid secrets file")

    def test_password_non_dict_secrets_returns_none(self, setup_password, loguru_logs):
        setup_password(load_yaml=["not", "a", "dict"])

        assert rabbitmq.load_rabbitmq_password() is None
        _assert_error_logged(loguru_logs, "Empty or invalid secrets file")

    def test_password_missing_key_returns_none(self, setup_password, loguru_logs):
        setup_password(load_yaml={"other_password": "x"})

        assert rabbitmq.load_rabbitmq_password() is None
        _assert_error_logged(loguru_logs, "rabbitmq_password not found in secrets file")

    def test_password_whitespace_stripped(self, setup_password, loguru_logs):
        setup_password(load_yaml={"rabbitmq_password": "  hunter2  "})

        assert rabbitmq.load_rabbitmq_password() == "hunter2"
        assert _error_messages(loguru_logs) == []

    def test_password_int_coerced_to_string(self, setup_password, loguru_logs):
        setup_password(load_yaml={"rabbitmq_password": 42})

        assert rabbitmq.load_rabbitmq_password() == "42"
        assert _error_messages(loguru_logs) == []

    def test_password_load_yaml_raises_returns_none(self, setup_password, loguru_logs):
        setup_password(load_raises=RuntimeError("boom"))

        assert rabbitmq.load_rabbitmq_password() is None
        _assert_error_logged(loguru_logs, "Failed to load RabbitMQ password")


def test_rabbitmq_user_constant():
    assert rabbitmq.RABBITMQ_USER == "openstack"
