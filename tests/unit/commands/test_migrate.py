# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism migrate rabbitmq3to4`` command.

The command talks to the RabbitMQ management API, so all HTTP traffic is
mocked at the module boundary (``osism.commands.migrate.requests``) while the
real ``requests.exceptions`` classes are kept in place so the ``except``
clauses in the command still match. The inventory and password lookups that
``take_action`` imports lazily are patched at their source module,
``osism.utils.rabbitmq``.
"""

from unittest.mock import MagicMock, call, mock_open, patch

import pytest
import requests

from osism.commands import migrate

from ._helpers import make_command, parse_args


NODES = [("10.0.0.1", "node1"), ("10.0.0.2", "node2")]
BASE_URL = "http://10.0.0.1:15672/api"
AUTH = ("openstack", "secret")

VALID_KOLLA_CONFIG = (
    "om_enable_rabbitmq_quorum_queues: true\n"
    'om_rpc_vhost: "openstack"\n'
    'om_notify_vhost: "openstack"\n'
)


def _response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


def _http_error(status_code):
    return requests.exceptions.HTTPError(response=MagicMock(status_code=status_code))


def _error_response(status_code):
    response = _response(status_code)
    response.raise_for_status.side_effect = _http_error(status_code)
    return response


def _messages(records, level):
    return [r["message"] for r in records if r["level"] == level]


@pytest.fixture
def mock_requests():
    """Patch the requests module used by migrate, keeping real exceptions."""
    with patch("osism.commands.migrate.requests") as mocked:
        mocked.exceptions = requests.exceptions
        yield mocked


def _take_action(cmd, parsed_args, node_addresses=NODES, password="secret"):
    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=node_addresses,
    ), patch("osism.utils.rabbitmq.load_rabbitmq_password", return_value=password):
        return cmd.take_action(parsed_args)


# --- _check_kolla_configuration ---


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(VALID_KOLLA_CONFIG, True, id="valid-double-quoted"),
        pytest.param(
            "om_rpc_vhost: 'openstack'\nom_notify_vhost: 'openstack'\n",
            True,
            id="valid-single-quoted-flag-absent",
        ),
        pytest.param(
            "om_rpc_vhost: openstack\nom_notify_vhost: openstack\n",
            True,
            id="valid-unquoted",
        ),
        pytest.param(
            "  om_rpc_vhost: openstack\n  om_notify_vhost: openstack\n",
            True,
            id="indented-lines-are-stripped",
        ),
        pytest.param(
            "# om_enable_rabbitmq_quorum_queues: false\n"
            "om_rpc_vhost: openstack\n"
            "om_notify_vhost: openstack\n",
            True,
            id="commented-quorum-false-is-ignored",
        ),
        pytest.param(
            "om_enable_rabbitmq_quorum_queues: false\n"
            'om_rpc_vhost: "openstack"\n'
            'om_notify_vhost: "openstack"\n',
            False,
            id="quorum-queues-false",
        ),
        pytest.param(
            'om_enable_rabbitmq_quorum_queues: "no"\n'
            'om_rpc_vhost: "openstack"\n'
            'om_notify_vhost: "openstack"\n',
            False,
            id="quorum-queues-no",
        ),
        pytest.param(
            'om_notify_vhost: "openstack"\n',
            False,
            id="rpc-vhost-missing",
        ),
        pytest.param(
            'om_rpc_vhost: "openstack"\n',
            False,
            id="notify-vhost-missing",
        ),
    ],
)
def test_check_kolla_configuration(content, expected):
    cmd = make_command(migrate.Rabbitmq3to4)
    with patch("builtins.open", mock_open(read_data=content)):
        assert cmd._check_kolla_configuration() is expected


def test_check_kolla_configuration_missing_file(loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert cmd._check_kolla_configuration() is False
    assert any(
        "Configuration file not found" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_check_kolla_configuration_read_error(loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    with patch("builtins.open", side_effect=OSError("disk error")):
        assert cmd._check_kolla_configuration() is False
    assert any(
        "Failed to read configuration file" in m
        for m in _messages(loguru_logs, "ERROR")
    )


def test_check_kolla_configuration_logs_success(loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    with patch("builtins.open", mock_open(read_data=VALID_KOLLA_CONFIG)):
        assert cmd._check_kolla_configuration() is True
    assert any(
        "Kolla configuration check passed" in m for m in _messages(loguru_logs, "INFO")
    )


# --- _prepare_vhost ---


def test_prepare_vhost_aborts_when_kolla_check_fails(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=False)

    assert cmd._prepare_vhost(BASE_URL, AUTH) is False
    mock_requests.put.assert_not_called()


def test_prepare_vhost_dry_run_makes_no_requests(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=True)

    assert cmd._prepare_vhost(BASE_URL, AUTH, dry_run=True) is True
    mock_requests.put.assert_not_called()
    infos = _messages(loguru_logs, "INFO")
    assert any("[DRY-RUN] Would create vhost 'openstack'" in m for m in infos)
    assert any("[DRY-RUN] Would set permissions" in m for m in infos)


def test_prepare_vhost_creates_vhost_and_permissions(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=True)

    assert cmd._prepare_vhost(BASE_URL, AUTH) is True
    assert mock_requests.put.call_args_list == [
        call(
            f"{BASE_URL}/vhosts/openstack",
            auth=AUTH,
            json={"default_queue_type": "quorum"},
            timeout=30,
        ),
        call(
            f"{BASE_URL}/permissions/openstack/openstack",
            auth=AUTH,
            json={"configure": ".*", "write": ".*", "read": ".*"},
            timeout=30,
        ),
    ]


def test_prepare_vhost_conflict_is_treated_as_success(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=True)
    mock_requests.put.return_value = _error_response(409)

    assert cmd._prepare_vhost(BASE_URL, AUTH) is True
    assert any(
        "Vhost 'openstack' already exists" in m
        for m in _messages(loguru_logs, "WARNING")
    )


def test_prepare_vhost_http_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=True)
    mock_requests.put.return_value = _error_response(500)

    assert cmd._prepare_vhost(BASE_URL, AUTH) is False
    assert any("Failed to prepare vhost" in m for m in _messages(loguru_logs, "ERROR"))


def test_prepare_vhost_connection_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._check_kolla_configuration = MagicMock(return_value=True)
    mock_requests.put.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._prepare_vhost(BASE_URL, AUTH) is False
    assert any("Failed to prepare vhost" in m for m in _messages(loguru_logs, "ERROR"))


# --- queue classification ---


def test_get_classic_queues_defaults_missing_type_to_classic():
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [
        {"name": "a"},
        {"name": "b", "type": "classic"},
        {"name": "c", "type": "quorum"},
    ]

    assert cmd._get_classic_queues(queues) == [
        {"name": "a"},
        {"name": "b", "type": "classic"},
    ]


def test_get_quorum_queues_returns_only_quorum():
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [
        {"name": "a"},
        {"name": "b", "type": "classic"},
        {"name": "c", "type": "quorum"},
    ]

    assert cmd._get_quorum_queues(queues) == [{"name": "c", "type": "quorum"}]


@pytest.mark.parametrize(
    ("service", "queue_name", "matches"),
    [
        pytest.param("nova", "compute", True, id="nova-exact"),
        pytest.param("nova", "compute.host1", True, id="nova-host-suffix"),
        pytest.param("nova", "compute_fanout_x", True, id="nova-fanout"),
        pytest.param("nova", "computex", False, id="nova-no-partial-match"),
        pytest.param("designate", "reply_abc123", True, id="designate-reply-hex"),
        pytest.param("designate", "reply_XYZ", False, id="designate-reply-non-hex"),
    ],
)
def test_match_queues_for_service_patterns(service, queue_name, matches):
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [{"name": queue_name}]

    matched = cmd._match_queues_for_service(queues, service)
    assert matched == (queues if matches else [])


def test_match_queues_for_service_unknown_service_returns_empty():
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [{"name": "compute"}]

    assert cmd._match_queues_for_service(queues, "unknown-service") == []


def test_match_queues_for_service_deduplicates_multi_pattern_matches():
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [{"name": "dup.queue"}]

    with patch.dict(
        migrate.SERVICE_QUEUE_PATTERNS,
        {"testsvc": [r"^dup.*$", r"^dup\..*$"]},
    ):
        matched = cmd._match_queues_for_service(queues, "testsvc")

    assert matched == queues


# --- _get_all_queues ---


def test_get_all_queues_returns_parsed_json(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    queues = [{"name": "compute", "vhost": "/"}]
    mock_requests.get.return_value = _response(200, json_data=queues)

    assert cmd._get_all_queues(BASE_URL, AUTH) == queues
    mock_requests.get.assert_called_once_with(
        f"{BASE_URL}/queues", auth=AUTH, timeout=30
    )


def test_get_all_queues_returns_none_on_error(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._get_all_queues(BASE_URL, AUTH) is None
    assert any("Failed to get queues" in m for m in _messages(loguru_logs, "ERROR"))


# --- _get_all_exchanges ---


def test_get_all_exchanges_without_vhost(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    exchanges = [{"name": "nova"}]
    mock_requests.get.return_value = _response(200, json_data=exchanges)

    assert cmd._get_all_exchanges(BASE_URL, AUTH) == exchanges
    mock_requests.get.assert_called_once_with(
        f"{BASE_URL}/exchanges", auth=AUTH, timeout=30
    )


def test_get_all_exchanges_encodes_vhost(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(200, json_data=[])

    assert cmd._get_all_exchanges(BASE_URL, AUTH, vhost="/") == []
    mock_requests.get.assert_called_once_with(
        f"{BASE_URL}/exchanges/%2F", auth=AUTH, timeout=30
    )


def test_get_all_exchanges_filters_default_exchanges(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    exchanges = [
        {"name": ""},
        {"name": "amq.topic"},
        {},
        {"name": "nova"},
    ]
    mock_requests.get.return_value = _response(200, json_data=exchanges)

    assert cmd._get_all_exchanges(BASE_URL, AUTH) == [{"name": "nova"}]


def test_get_all_exchanges_returns_none_on_error(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._get_all_exchanges(BASE_URL, AUTH) is None
    assert any("Failed to get exchanges" in m for m in _messages(loguru_logs, "ERROR"))


# --- _close_queue_connections ---


def _consumer(connection_name):
    return {"channel_details": {"connection_name": connection_name}}


def test_close_queue_connections_queue_not_found(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(404)

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 0
    mock_requests.delete.assert_not_called()


def test_close_queue_connections_without_consumers(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(200, json_data={})

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 0
    mock_requests.get.assert_called_once_with(
        f"{BASE_URL}/queues/%2F/compute", auth=AUTH, timeout=30
    )
    mock_requests.delete.assert_not_called()


def test_close_queue_connections_without_connection_names(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200, json_data={"consumer_details": [{"channel_details": {}}]}
    )

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 0
    mock_requests.delete.assert_not_called()


def test_close_queue_connections_dry_run_counts_unique_connections(
    mock_requests, loguru_logs
):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200,
        json_data={
            "consumer_details": [
                _consumer("conn1"),
                _consumer("conn1"),
                _consumer("conn2"),
            ]
        },
    )

    closed = cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute", dry_run=True)

    assert closed == 2
    mock_requests.delete.assert_not_called()
    dry_run_logs = [
        m
        for m in _messages(loguru_logs, "INFO")
        if "[DRY-RUN] Would close connection" in m
    ]
    assert len(dry_run_logs) == 2


def test_close_queue_connections_counts_successful_deletes(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200,
        json_data={"consumer_details": [_consumer("conn1"), _consumer("conn2")]},
    )
    mock_requests.delete.side_effect = [_response(200), _response(204)]

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 2
    assert mock_requests.delete.call_count == 2


def test_close_queue_connections_encodes_connection_name(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200,
        json_data={"consumer_details": [_consumer("1.2.3.4:5672 -> 5.6.7.8:5673")]},
    )
    mock_requests.delete.return_value = _response(200)

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 1
    mock_requests.delete.assert_called_once_with(
        f"{BASE_URL}/connections/1.2.3.4%3A5672%20-%3E%205.6.7.8%3A5673",
        auth=AUTH,
        timeout=30,
    )


def test_close_queue_connections_skips_already_closed_connection(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200, json_data={"consumer_details": [_consumer("conn1")]}
    )
    mock_requests.delete.return_value = _response(404)

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 0


def test_close_queue_connections_continues_after_failed_delete(
    mock_requests, loguru_logs
):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.return_value = _response(
        200,
        json_data={"consumer_details": [_consumer("conn1"), _consumer("conn2")]},
    )
    mock_requests.delete.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        _response(200),
    ]

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 1
    assert mock_requests.delete.call_count == 2
    assert any(
        "Failed to close connection" in m for m in _messages(loguru_logs, "WARNING")
    )


def test_close_queue_connections_queue_lookup_failure_returns_zero(
    mock_requests, loguru_logs
):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.get.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._close_queue_connections(BASE_URL, AUTH, "/", "compute") == 0
    assert any(
        "Failed to get queue consumers for 'compute'" in m
        for m in _messages(loguru_logs, "WARNING")
    )


# --- _delete_queue ---


def test_delete_queue_closes_connections_first(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._close_queue_connections = MagicMock(return_value=2)
    mock_requests.delete.return_value = _response(200)

    result = cmd._delete_queue(BASE_URL, AUTH, "/", "compute", close_connections=True)

    assert result is True
    cmd._close_queue_connections.assert_called_once_with(
        BASE_URL, AUTH, "/", "compute", False
    )
    assert any(
        "Closed 2 connection(s) for queue: compute" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_delete_queue_does_not_close_connections_by_default(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    cmd._close_queue_connections = MagicMock()
    mock_requests.delete.return_value = _response(200)

    assert cmd._delete_queue(BASE_URL, AUTH, "/", "compute") is True
    cmd._close_queue_connections.assert_not_called()


def test_delete_queue_dry_run_makes_no_requests(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)

    assert cmd._delete_queue(BASE_URL, AUTH, "/", "compute", dry_run=True) is True
    mock_requests.delete.assert_not_called()
    assert any(
        "[DRY-RUN] Would delete queue: compute" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_delete_queue_encodes_vhost_and_queue_name(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _response(200)

    assert cmd._delete_queue(BASE_URL, AUTH, "/openstack", "a/b") is True
    mock_requests.delete.assert_called_once_with(
        f"{BASE_URL}/queues/%2Fopenstack/a%2Fb", auth=AUTH, timeout=30
    )


def test_delete_queue_not_found_is_treated_as_success(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _error_response(404)

    assert cmd._delete_queue(BASE_URL, AUTH, "/", "compute") is True
    assert any(
        "Queue 'compute' not found" in m for m in _messages(loguru_logs, "WARNING")
    )


def test_delete_queue_http_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _error_response(500)

    assert cmd._delete_queue(BASE_URL, AUTH, "/", "compute") is False
    assert any(
        "Failed to delete queue 'compute'" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_delete_queue_connection_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._delete_queue(BASE_URL, AUTH, "/", "compute") is False
    assert any(
        "Failed to delete queue 'compute'" in m for m in _messages(loguru_logs, "ERROR")
    )


# --- _delete_exchange ---


def test_delete_exchange_dry_run_makes_no_requests(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)

    assert cmd._delete_exchange(BASE_URL, AUTH, "/", "nova", dry_run=True) is True
    mock_requests.delete.assert_not_called()
    assert any(
        "[DRY-RUN] Would delete exchange: nova" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_delete_exchange_encodes_vhost_and_exchange_name(mock_requests):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _response(200)

    assert cmd._delete_exchange(BASE_URL, AUTH, "/", "nova") is True
    mock_requests.delete.assert_called_once_with(
        f"{BASE_URL}/exchanges/%2F/nova", auth=AUTH, timeout=30
    )


def test_delete_exchange_not_found_is_treated_as_success(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _error_response(404)

    assert cmd._delete_exchange(BASE_URL, AUTH, "/", "nova") is True
    assert any(
        "Exchange 'nova' not found" in m for m in _messages(loguru_logs, "WARNING")
    )


def test_delete_exchange_http_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.return_value = _error_response(500)

    assert cmd._delete_exchange(BASE_URL, AUTH, "/", "nova") is False
    assert any(
        "Failed to delete exchange 'nova'" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_delete_exchange_connection_error_fails(mock_requests, loguru_logs):
    cmd = make_command(migrate.Rabbitmq3to4)
    mock_requests.delete.side_effect = requests.exceptions.ConnectionError("boom")

    assert cmd._delete_exchange(BASE_URL, AUTH, "/", "nova") is False
    assert any(
        "Failed to delete exchange 'nova'" in m for m in _messages(loguru_logs, "ERROR")
    )


# --- take_action: argument validation and node selection ---


def test_take_action_requires_command(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, [])

    with patch("osism.utils.rabbitmq.get_rabbitmq_node_addresses") as mock_nodes:
        rc = cmd.take_action(parsed_args)

    assert rc == 1
    mock_nodes.assert_not_called()
    assert any("must be specified" in m for m in _messages(loguru_logs, "ERROR"))


def test_take_action_fails_without_node_addresses(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["check"])

    assert _take_action(cmd, parsed_args, node_addresses=None) == 1
    assert any(
        "Failed to get RabbitMQ node addresses" in m
        for m in _messages(loguru_logs, "ERROR")
    )


def test_take_action_fails_without_password(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["check"])

    assert _take_action(cmd, parsed_args, password=None) == 1
    assert any(
        "Failed to load RabbitMQ password" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_take_action_rejects_unknown_server(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["check", "--server", "node3"])

    assert _take_action(cmd, parsed_args) == 1
    errors = _messages(loguru_logs, "ERROR")
    assert any("Server 'node3' not found" in m for m in errors)
    assert any("Available: node1, node2" in m for m in errors)


def test_take_action_selects_requested_server():
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4, ["prepare", "--server", "node2", "--dry-run"]
    )
    cmd._prepare_vhost = MagicMock(return_value=True)

    assert _take_action(cmd, parsed_args) == 0
    cmd._prepare_vhost.assert_called_once_with("http://10.0.0.2:15672/api", AUTH, True)


@pytest.mark.parametrize(
    ("prepare_result", "expected_rc"),
    [
        pytest.param(True, 0, id="prepare-success"),
        pytest.param(False, 1, id="prepare-failure"),
    ],
)
def test_take_action_prepare_uses_first_node_by_default(prepare_result, expected_rc):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["prepare"])
    cmd._prepare_vhost = MagicMock(return_value=prepare_result)

    assert _take_action(cmd, parsed_args) == expected_rc
    cmd._prepare_vhost.assert_called_once_with(BASE_URL, AUTH, False)


# --- take_action: check command ---


CLASSIC_ROOT = {"name": "compute", "vhost": "/", "type": "classic"}
CLASSIC_OTHER = {"name": "compute", "vhost": "/other", "type": "classic"}
QUORUM_ROOT = {"name": "conductor", "vhost": "/", "type": "quorum"}
QUORUM_OPENSTACK = {"name": "conductor", "vhost": "/openstack", "type": "quorum"}


@pytest.mark.parametrize(
    ("queues", "expected_message"),
    [
        pytest.param(
            [CLASSIC_ROOT],
            "Migration is REQUIRED",
            id="only-classic",
        ),
        pytest.param(
            [QUORUM_OPENSTACK],
            "Migration is NOT required: Only quorum queues found",
            id="only-quorum",
        ),
        pytest.param(
            [CLASSIC_ROOT, QUORUM_OPENSTACK],
            "Migration is IN PROGRESS: Classic queues in / and quorum queues",
            id="classic-in-root-quorum-in-openstack",
        ),
        pytest.param(
            [CLASSIC_ROOT, QUORUM_ROOT],
            "Migration is IN PROGRESS: Classic queues in / and quorum queues",
            id="legacy-quorum-in-root",
        ),
        pytest.param(
            [CLASSIC_OTHER, QUORUM_OPENSTACK],
            "Migration is IN PROGRESS: Both classic and quorum queues found",
            id="mixed-outside-root",
        ),
        pytest.param(
            [],
            "Migration is NOT required: No queues found",
            id="no-queues",
        ),
    ],
)
def test_take_action_check_verdicts(queues, expected_message, loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["check"])
    cmd._get_all_queues = MagicMock(return_value=queues)

    assert _take_action(cmd, parsed_args) == 0
    assert any(expected_message in m for m in _messages(loguru_logs, "INFO"))


def test_take_action_fails_when_queues_unavailable():
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list"])
    cmd._get_all_queues = MagicMock(return_value=None)

    assert _take_action(cmd, parsed_args) == 1


def test_take_action_check_fails_when_second_queue_fetch_fails():
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["check"])
    cmd._get_all_queues = MagicMock(side_effect=[[], None])

    assert _take_action(cmd, parsed_args) == 1


# --- take_action: list command ---


LIST_QUEUES = [
    {"name": "compute", "vhost": "/", "type": "classic", "messages": 3},
    {"name": "q-plugin", "vhost": "/", "type": "classic"},
    {"name": "conductor", "vhost": "/", "type": "quorum", "messages": 1},
    {"name": "central", "vhost": "/openstack", "type": "classic"},
]


def test_take_action_list_shows_classic_queues_in_default_vhost(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)

    assert _take_action(cmd, parsed_args) == 0
    infos = _messages(loguru_logs, "INFO")
    assert any("Found 2 classic queue(s) in vhost '/':" in m for m in infos)
    assert any("- compute (vhost: /, messages: 3)" in m for m in infos)
    assert any("- q-plugin (vhost: /, messages: 0)" in m for m in infos)
    assert not any("conductor" in m for m in infos)
    assert not any("central" in m for m in infos)


def test_take_action_list_quorum_queues(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list", "--quorum"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)

    assert _take_action(cmd, parsed_args) == 0
    infos = _messages(loguru_logs, "INFO")
    assert any("Found 1 quorum queue(s) in vhost '/':" in m for m in infos)
    assert any("- conductor (vhost: /, messages: 1)" in m for m in infos)


def test_take_action_list_filters_by_service(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list", "nova"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)

    assert _take_action(cmd, parsed_args) == 0
    infos = _messages(loguru_logs, "INFO")
    assert any(
        "Found 1 classic queue(s) for service 'nova' in vhost '/':" in m for m in infos
    )
    assert not any("q-plugin" in m for m in infos)


def test_take_action_list_filters_by_vhost(loguru_logs):
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4, ["list", "--vhost", "/openstack"]
    )
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)

    assert _take_action(cmd, parsed_args) == 0
    infos = _messages(loguru_logs, "INFO")
    assert any("Found 1 classic queue(s) in vhost '/openstack':" in m for m in infos)
    assert any("- central (vhost: /openstack, messages: 0)" in m for m in infos)
    assert not any("compute" in m for m in infos)


def test_take_action_list_reports_no_queues(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list", "designate"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)

    assert _take_action(cmd, parsed_args) == 0
    assert any(
        "No classic queues found for service 'designate' in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )


# --- take_action: delete command ---


def test_take_action_delete_deletes_all_classic_queues(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)
    cmd._delete_queue = MagicMock(return_value=True)

    assert _take_action(cmd, parsed_args) == 0
    cmd._delete_queue.assert_has_calls(
        [
            call(BASE_URL, AUTH, "/", "compute", False, True),
            call(BASE_URL, AUTH, "/", "q-plugin", False, True),
        ]
    )
    assert cmd._delete_queue.call_count == 2
    assert any(
        "Successfully deleted 2 queue(s) in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_take_action_delete_reports_failures(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)
    cmd._delete_queue = MagicMock(side_effect=[True, False])

    assert _take_action(cmd, parsed_args) == 1
    assert any(
        "Failed to delete 1 queue(s)" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_take_action_delete_dry_run_with_service_filter(loguru_logs):
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4,
        ["delete", "nova", "--dry-run", "--no-close-connections"],
    )
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)
    cmd._delete_queue = MagicMock(return_value=True)

    assert _take_action(cmd, parsed_args) == 0
    cmd._delete_queue.assert_called_once_with(
        BASE_URL, AUTH, "/", "compute", True, False
    )
    assert any(
        "[DRY-RUN] Would delete 1 queue(s) for service 'nova' in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_take_action_delete_reports_no_queues(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete", "designate"])
    cmd._get_all_queues = MagicMock(return_value=LIST_QUEUES)
    cmd._delete_queue = MagicMock()

    assert _take_action(cmd, parsed_args) == 0
    cmd._delete_queue.assert_not_called()
    assert any(
        "No classic queues found for service 'designate' in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )


# --- take_action: list-exchanges command ---


def test_take_action_list_exchanges_fails_on_error():
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list-exchanges"])
    cmd._get_all_exchanges = MagicMock(return_value=None)

    assert _take_action(cmd, parsed_args) == 1


def test_take_action_list_exchanges_reports_empty_vhost(loguru_logs):
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4, ["list-exchanges", "--vhost", "/openstack"]
    )
    cmd._get_all_exchanges = MagicMock(return_value=[])

    assert _take_action(cmd, parsed_args) == 0
    cmd._get_all_exchanges.assert_called_once_with(BASE_URL, AUTH, "/openstack")
    assert any(
        "No exchanges found in vhost '/openstack'" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_take_action_list_exchanges_lists_exchanges(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["list-exchanges"])
    cmd._get_all_exchanges = MagicMock(
        return_value=[
            {"name": "nova", "type": "topic", "durable": True},
            {"name": "cinder", "type": "fanout", "durable": False},
        ]
    )

    assert _take_action(cmd, parsed_args) == 0
    infos = _messages(loguru_logs, "INFO")
    assert any("Found 2 exchange(s) in vhost '/':" in m for m in infos)
    assert any("- nova (type: topic, durable)" in m for m in infos)
    assert any("- cinder (type: fanout, transient)" in m for m in infos)


# --- take_action: delete-exchanges command ---


def test_take_action_delete_exchanges_fails_on_error():
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete-exchanges"])
    cmd._get_all_exchanges = MagicMock(return_value=None)

    assert _take_action(cmd, parsed_args) == 1


def test_take_action_delete_exchanges_reports_empty_vhost(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete-exchanges"])
    cmd._get_all_exchanges = MagicMock(return_value=[])

    assert _take_action(cmd, parsed_args) == 0
    assert any(
        "No exchanges found in vhost '/'" in m for m in _messages(loguru_logs, "INFO")
    )


def test_take_action_delete_exchanges_only_targets_root_vhost(loguru_logs):
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4, ["delete-exchanges", "--vhost", "/openstack"]
    )
    cmd._get_all_exchanges = MagicMock(
        return_value=[{"name": "nova"}, {"name": "cinder"}]
    )
    cmd._delete_exchange = MagicMock(return_value=True)

    assert _take_action(cmd, parsed_args) == 0
    cmd._get_all_exchanges.assert_called_once_with(BASE_URL, AUTH, "/")
    cmd._delete_exchange.assert_has_calls(
        [
            call(BASE_URL, AUTH, "/", "cinder", False),
            call(BASE_URL, AUTH, "/", "nova", False),
        ]
    )
    assert any(
        "Successfully deleted 2 exchange(s) in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )


def test_take_action_delete_exchanges_reports_failures(loguru_logs):
    cmd, parsed_args = parse_args(migrate.Rabbitmq3to4, ["delete-exchanges"])
    cmd._get_all_exchanges = MagicMock(
        return_value=[{"name": "nova"}, {"name": "cinder"}]
    )
    cmd._delete_exchange = MagicMock(side_effect=[True, False])

    assert _take_action(cmd, parsed_args) == 1
    assert any(
        "Failed to delete 1 exchange(s)" in m for m in _messages(loguru_logs, "ERROR")
    )


def test_take_action_delete_exchanges_dry_run(loguru_logs):
    cmd, parsed_args = parse_args(
        migrate.Rabbitmq3to4, ["delete-exchanges", "--dry-run"]
    )
    cmd._get_all_exchanges = MagicMock(return_value=[{"name": "nova"}])
    cmd._delete_exchange = MagicMock(return_value=True)

    assert _take_action(cmd, parsed_args) == 0
    cmd._delete_exchange.assert_called_once_with(BASE_URL, AUTH, "/", "nova", True)
    assert any(
        "[DRY-RUN] Would delete 1 exchange(s) in vhost '/'" in m
        for m in _messages(loguru_logs, "INFO")
    )
