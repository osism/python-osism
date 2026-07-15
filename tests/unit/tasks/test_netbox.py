# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ``netbox`` worker tasks (``osism/tasks/netbox.py``).

Covers the device-field update helper (semaphore limiting, error handling),
the NetBox filter matcher, the three structurally identical ``set_*`` tasks
(Redlock guarding, primary/secondary fan-out, filter skipping), the ``get_*``
lookup and pass-through tasks, ``manage`` (environment and argument forwarding
to ``run_command``) and ``ping``.

All tasks are bound Celery tasks and are invoked directly -- Celery binds
``self`` on direct calls, so no broker is needed. ``utils.nb`` and
``utils.secondary_nb_list`` are lazy module attributes resolved via
``osism.utils.__getattr__``; they are always patched with ``create=True`` so
the real NetBox wiring is never triggered.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
import requests.exceptions

from osism.tasks import netbox

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


# The three ``set_*`` tasks share the same lock/filter/update/skip flow; only
# the custom field name and the log wording differ. Parametrize over them
# instead of triplicating every test (same approach as ``QUERY_LIST_VARIANTS``
# in ``tests/unit/tasks/conductor/test_netbox.py``).
SET_TASK_VARIANTS = [
    pytest.param(
        netbox.set_maintenance, "maintenance", "maintenance", True, id="maintenance"
    ),
    pytest.param(
        netbox.set_provision_state,
        "provision_state",
        "provision state",
        "active",
        id="provision-state",
    ),
    pytest.param(
        netbox.set_power_state,
        "power_state",
        "power state",
        "power on",
        id="power-state",
    ),
]

SET_TASK_PARAMS = "set_task,field_name,log_label,state"

# Base URL of the NetBox instance handed to ``_update_netbox_device_field``.
NB_API_URL = "https://netbox.example.com"


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _make_secondary(base_url, netbox_name=None, netbox_site=None):
    """Build a secondary NetBox instance stub.

    ``netbox_name`` / ``netbox_site`` default to ``None`` (attribute present
    but unset) so the filter matcher falls through to the URL check.
    """
    nb = MagicMock()
    nb.base_url = base_url
    nb.netbox_name = netbox_name
    nb.netbox_site = netbox_site
    return nb


@pytest.fixture
def mock_nb(mocker):
    """Replace ``osism.utils.nb`` (lazy attribute) with a fresh MagicMock."""
    nb = MagicMock()
    nb.base_url = "https://netbox-primary.example.com"
    nb.netbox_name = None
    nb.netbox_site = None
    mocker.patch("osism.utils.nb", new=nb, create=True)
    return nb


@pytest.fixture
def patch_lock_check(mocker):
    return mocker.patch("osism.tasks.netbox.utils.check_task_lock_and_exit")


@pytest.fixture
def patch_redlock(mocker):
    lock = MagicMock()
    lock.acquire.return_value = True
    create = mocker.patch("osism.tasks.netbox.utils.create_redlock", return_value=lock)
    return SimpleNamespace(create=create, lock=lock)


@pytest.fixture
def patch_update_field(mocker):
    return mocker.patch(
        "osism.tasks.netbox._update_netbox_device_field", return_value=True
    )


@pytest.fixture
def patch_semaphore(mocker):
    semaphore = MagicMock()
    create = mocker.patch(
        "osism.tasks.netbox.utils.create_netbox_semaphore", return_value=semaphore
    )
    return SimpleNamespace(create=create, semaphore=semaphore)


@pytest.fixture
def nb_api():
    """NetBox API stub passed into ``_update_netbox_device_field``.

    ``base_url`` is set explicitly rather than left to ``MagicMock``
    auto-attribute creation: the helper hands it to
    ``create_netbox_semaphore`` and interpolates it into every error message.
    """
    nb = MagicMock()
    nb.base_url = NB_API_URL
    return nb


# ---------------------------------------------------------------------------
# _update_netbox_device_field
# ---------------------------------------------------------------------------


def test_update_field_updates_and_saves(patch_semaphore, nb_api):
    device = nb_api.dcim.devices.get.return_value

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is True
    )

    nb_api.dcim.devices.get.assert_called_once_with(name="node-1")
    device.custom_fields.update.assert_called_once_with({"maintenance": True})
    device.save.assert_called_once_with()


def test_update_field_device_not_found(patch_semaphore, nb_api, loguru_logs):
    nb_api.dcim.devices.get.return_value = None

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is False
    )

    # The helper stays silent on a missing device; the caller logs the error.
    assert not any(r["level"] == "ERROR" for r in loguru_logs)


@pytest.mark.parametrize(
    "exception,message",
    [
        pytest.param(
            requests.exceptions.ConnectTimeout("boom"),
            "Connection timeout while updating",
            id="connect-timeout",
        ),
        # ReadTimeout, not ConnectTimeout: ConnectTimeout inherits from both
        # ConnectionError and Timeout and is caught by the first handler.
        pytest.param(
            requests.exceptions.ReadTimeout("boom"),
            "Request timeout while updating",
            id="read-timeout",
        ),
        pytest.param(
            requests.exceptions.ConnectionError("boom"),
            "Connection error while updating",
            id="connection-error",
        ),
        pytest.param(
            requests.exceptions.HTTPError("boom"),
            "Request error while updating",
            id="request-error",
        ),
    ],
)
def test_update_field_request_errors_from_get(
    patch_semaphore, nb_api, loguru_logs, exception, message
):
    nb_api.dcim.devices.get.side_effect = exception

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is False
    )

    assert _has_log(
        loguru_logs,
        "ERROR",
        f"{message} maintenance for device node-1 on {NB_API_URL}",
    )


def test_update_field_request_error_from_save(patch_semaphore, nb_api, loguru_logs):
    device = nb_api.dcim.devices.get.return_value
    device.save.side_effect = requests.exceptions.ConnectionError("boom")

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is False
    )

    assert _has_log(loguru_logs, "ERROR", "Connection error while updating")


def test_update_field_semaphore_wraps_api_call(patch_semaphore, nb_api):
    manager = MagicMock()
    manager.attach_mock(patch_semaphore.semaphore, "semaphore")
    manager.attach_mock(nb_api.dcim.devices.get, "get")

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is True
    )

    patch_semaphore.create.assert_called_once_with(NB_API_URL)
    calls = manager.mock_calls
    assert calls[0] == call.semaphore.__enter__()
    assert call.get(name="node-1") in calls
    assert calls[-1] == call.semaphore.__exit__(None, None, None)


def test_update_field_semaphore_released_on_handled_error(
    patch_semaphore, nb_api, loguru_logs
):
    nb_api.dcim.devices.get.side_effect = requests.exceptions.ConnectionError("boom")

    assert (
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)
        is False
    )

    # The exception handlers sit inside the ``with`` block, so the semaphore is
    # exited as if nothing had gone wrong.
    patch_semaphore.semaphore.__enter__.assert_called_once_with()
    patch_semaphore.semaphore.__exit__.assert_called_once_with(None, None, None)


def test_update_field_semaphore_released_on_unhandled_error(patch_semaphore, nb_api):
    # Anything that is not a requests exception propagates; the semaphore must
    # still be released on the way out.
    nb_api.dcim.devices.get.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        netbox._update_netbox_device_field(nb_api, "node-1", "maintenance", True)

    patch_semaphore.semaphore.__enter__.assert_called_once_with()
    exc_type, exc, _ = patch_semaphore.semaphore.__exit__.call_args.args
    assert exc_type is RuntimeError
    assert str(exc) == "boom"


# ---------------------------------------------------------------------------
# _matches_netbox_filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("netbox_filter", [None, ""], ids=["none", "empty"])
def test_matches_filter_empty_filter_matches_everything(netbox_filter):
    nb = SimpleNamespace(base_url="https://netbox.example.com")

    assert netbox._matches_netbox_filter(nb, netbox_filter) is True


@pytest.mark.parametrize("netbox_filter", ["primary", "PRIMARY"])
def test_matches_filter_primary(netbox_filter):
    nb = SimpleNamespace(base_url="https://netbox.example.com")

    assert netbox._matches_netbox_filter(nb, netbox_filter, is_primary=True) is True


def test_matches_filter_primary_keyword_not_substring_of_filter():
    # A filter that merely contains "primary" (e.g. a site named
    # "primary-region") must not select the primary instance: the keyword is
    # matched as a whole, not treated as a substring of the filter.
    nb = SimpleNamespace(base_url="https://netbox.example.com")

    assert netbox._matches_netbox_filter(nb, "primary-dc", is_primary=True) is False


def test_matches_filter_primary_filter_does_not_match_secondary():
    nb = SimpleNamespace(
        base_url="https://nb2.example.com",
        netbox_name="secondary",
        netbox_site="dc1",
    )

    assert netbox._matches_netbox_filter(nb, "primary", is_primary=False) is False


def test_matches_filter_url_substring_case_insensitive():
    nb = SimpleNamespace(base_url="https://netbox.example.com")

    assert netbox._matches_netbox_filter(nb, "NETBOX.example") is True


def test_matches_filter_missing_name_and_site_attributes():
    # Primary instances carry no netbox_name/netbox_site attributes; the
    # matcher must fall through to False without raising AttributeError.
    nb = SimpleNamespace(base_url="https://netbox.example.com")

    assert netbox._matches_netbox_filter(nb, "does-not-match") is False


def test_matches_filter_netbox_name():
    nb = SimpleNamespace(base_url="https://nb2.example.com", netbox_name="Region-East")

    assert netbox._matches_netbox_filter(nb, "region-east") is True


def test_matches_filter_netbox_site():
    nb = SimpleNamespace(base_url="https://nb2.example.com", netbox_site="DC-West")

    assert netbox._matches_netbox_filter(nb, "dc-west") is True


def test_matches_filter_nothing_matches():
    nb = SimpleNamespace(
        base_url="https://nb2.example.com",
        netbox_name="secondary",
        netbox_site="dc1",
    )

    assert netbox._matches_netbox_filter(nb, "other-instance") is False


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_checks_lock_and_returns_none(patch_lock_check):
    assert netbox.run("action", []) is None

    patch_lock_check.assert_called_once_with()


def test_run_propagates_lock_exit(patch_lock_check):
    patch_lock_check.side_effect = SystemExit(1)

    with pytest.raises(SystemExit):
        netbox.run("action", [])


# ---------------------------------------------------------------------------
# set_maintenance / set_provision_state / set_power_state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_happy_path_primary_only(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    set_task,
    field_name,
    log_label,
    state,
):
    result = set_task("node-1", state, secondary_nb_list=[])

    assert result is True
    patch_lock_check.assert_called_once_with()
    patch_redlock.create.assert_called_once_with(
        key="lock_osism_tasks_netbox_node-1", auto_release_time=300
    )
    patch_redlock.lock.acquire.assert_called_once_with(timeout=120)
    patch_update_field.assert_called_once_with(mock_nb, "node-1", field_name, state)
    patch_redlock.lock.release.assert_called_once_with()


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_lock_not_acquired(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    loguru_logs,
    set_task,
    field_name,
    log_label,
    state,
):
    patch_redlock.lock.acquire.return_value = False

    result = set_task("node-1", state, secondary_nb_list=[])

    assert result is False
    assert _has_log(loguru_logs, "ERROR", "Could not acquire lock for node node-1")
    patch_update_field.assert_not_called()
    patch_redlock.lock.release.assert_not_called()


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_update_failure_logs_error_and_returns_false(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    loguru_logs,
    set_task,
    field_name,
    log_label,
    state,
):
    patch_update_field.return_value = False

    result = set_task("node-1", state, secondary_nb_list=[])

    assert result is False
    assert _has_log(
        loguru_logs,
        "ERROR",
        f"Could not set {log_label} for node-1 on {mock_nb.base_url}",
    )
    patch_redlock.lock.release.assert_called_once_with()


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_filter_skips_primary(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    set_task,
    field_name,
    log_label,
    state,
):
    result = set_task(
        "node-1", state, netbox_filter="no-such-instance", secondary_nb_list=[]
    )

    assert result is True
    patch_update_field.assert_not_called()
    patch_redlock.lock.release.assert_called_once_with()


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_filter_selects_matching_secondary(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    set_task,
    field_name,
    log_label,
    state,
):
    matching = _make_secondary("https://nb2.example.com")
    other = _make_secondary("https://nb3.example.com")

    result = set_task(
        "node-1", state, netbox_filter="nb2", secondary_nb_list=[matching, other]
    )

    assert result is True
    # The primary URL does not contain "nb2" either, so only the matching
    # secondary is updated.
    patch_update_field.assert_called_once_with(matching, "node-1", field_name, state)


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_defaults_to_utils_secondary_nb_list(
    mocker,
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    set_task,
    field_name,
    log_label,
    state,
):
    secondary = _make_secondary("https://nb2.example.com")
    mocker.patch("osism.utils.secondary_nb_list", new=[secondary], create=True)

    result = set_task("node-1", state)

    assert result is True
    assert patch_update_field.call_args_list == [
        call(mock_nb, "node-1", field_name, state),
        call(secondary, "node-1", field_name, state),
    ]


@pytest.mark.parametrize(SET_TASK_PARAMS, SET_TASK_VARIANTS)
def test_set_task_releases_lock_when_update_raises(
    patch_lock_check,
    patch_redlock,
    patch_update_field,
    mock_nb,
    set_task,
    field_name,
    log_label,
    state,
):
    patch_update_field.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        set_task("node-1", state, secondary_nb_list=[])

    patch_redlock.lock.release.assert_called_once_with()


def test_set_power_state_converts_none_to_na(
    patch_lock_check, patch_redlock, patch_update_field, mock_nb
):
    result = netbox.set_power_state("node-1", None, secondary_nb_list=[])

    assert result is True
    patch_update_field.assert_called_once_with(mock_nb, "node-1", "power_state", "n/a")


def test_set_task_locked_aborts_before_redlock(patch_lock_check, patch_redlock):
    patch_lock_check.side_effect = SystemExit(1)

    with pytest.raises(SystemExit):
        netbox.set_maintenance("node-1", True)

    patch_redlock.create.assert_not_called()


# ---------------------------------------------------------------------------
# get_location_id / get_rack_id
# ---------------------------------------------------------------------------


LOOKUP_TASK_VARIANTS = [
    pytest.param(netbox.get_location_id, "locations", id="location"),
    pytest.param(netbox.get_rack_id, "racks", id="rack"),
]


@pytest.mark.parametrize("lookup_task,endpoint", LOOKUP_TASK_VARIANTS)
def test_get_id_found(mock_nb, lookup_task, endpoint):
    api = getattr(mock_nb.dcim, endpoint)
    api.get.return_value = SimpleNamespace(id=42)

    assert lookup_task("name-1") == 42

    api.get.assert_called_once_with(name="name-1")


@pytest.mark.parametrize("lookup_task,endpoint", LOOKUP_TASK_VARIANTS)
def test_get_id_not_found(mock_nb, lookup_task, endpoint):
    getattr(mock_nb.dcim, endpoint).get.return_value = None

    assert lookup_task("name-1") is None


@pytest.mark.parametrize("lookup_task,endpoint", LOOKUP_TASK_VARIANTS)
def test_get_id_ambiguous_match(mock_nb, lookup_task, endpoint):
    # pynetbox raises ValueError when a get() matches multiple objects.
    getattr(mock_nb.dcim, endpoint).get.side_effect = ValueError("multiple results")

    assert lookup_task("name-1") is None


# ---------------------------------------------------------------------------
# get_devices / get_device_by_name / get_interfaces_by_device /
# get_addresses_by_device_and_interface
# ---------------------------------------------------------------------------


def test_get_devices_delegates_to_filter(mock_nb):
    result = netbox.get_devices(role="server", site="x")

    mock_nb.dcim.devices.filter.assert_called_once_with(role="server", site="x")
    assert result is mock_nb.dcim.devices.filter.return_value


def test_get_device_by_name_delegates_to_get(mock_nb):
    result = netbox.get_device_by_name("n1")

    mock_nb.dcim.devices.get.assert_called_once_with(name="n1")
    assert result is mock_nb.dcim.devices.get.return_value


def test_get_interfaces_by_device_delegates_to_filter(mock_nb):
    result = netbox.get_interfaces_by_device("n1")

    mock_nb.dcim.interfaces.filter.assert_called_once_with(device="n1")
    assert result is mock_nb.dcim.interfaces.filter.return_value


def test_get_addresses_by_device_and_interface_delegates_to_filter(mock_nb):
    result = netbox.get_addresses_by_device_and_interface("n1", "eth0")

    mock_nb.ipam.ip_addresses.filter.assert_called_once_with(
        device="n1", interface="eth0"
    )
    assert result is mock_nb.ipam.ip_addresses.filter.return_value


# ---------------------------------------------------------------------------
# manage
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_run_command(mocker):
    return mocker.patch("osism.tasks.netbox.run_command")


@pytest.fixture
def patch_manager_settings(mocker):
    mocker.patch(
        "osism.tasks.netbox.settings.NETBOX_URL", new="https://netbox.example.com"
    )
    mocker.patch("osism.tasks.netbox.settings.NETBOX_TOKEN", new="token-123")
    mocker.patch("osism.tasks.netbox.settings.IGNORE_SSL_ERRORS", new=True)


def test_manage_runs_netbox_manager(
    patch_lock_check, patch_run_command, patch_manager_settings
):
    result = netbox.manage("import", "--dry-run")

    assert result is patch_run_command.return_value
    # First positional argument is self.request.id, which is None on a
    # direct call; all settings values are str()-coerced.
    patch_run_command.assert_called_once_with(
        None,
        "/usr/local/bin/netbox-manager",
        {
            "NETBOX_MANAGER_URL": "https://netbox.example.com",
            "NETBOX_MANAGER_TOKEN": "token-123",
            "NETBOX_MANAGER_IGNORE_SSL_ERRORS": "True",
            "NETBOX_MANAGER_VERBOSE": "true",
        },
        "import",
        "--dry-run",
        publish=True,
        locking=False,
        auto_release_time=3600,
    )


def test_manage_forwards_explicit_keyword_arguments(
    patch_lock_check, patch_run_command, patch_manager_settings
):
    netbox.manage("sync", publish=False, locking=True, auto_release_time=60)

    args, kwargs = patch_run_command.call_args
    assert args[3:] == ("sync",)
    assert kwargs == {"publish": False, "locking": True, "auto_release_time": 60}


def test_manage_locked_does_not_run_command(patch_lock_check, patch_run_command):
    patch_lock_check.side_effect = SystemExit(1)

    with pytest.raises(SystemExit):
        netbox.manage("import")

    patch_run_command.assert_not_called()


# ---------------------------------------------------------------------------
# ping / setup_periodic_tasks
# ---------------------------------------------------------------------------


def test_ping_returns_status(mock_nb):
    assert netbox.ping() is mock_nb.status.return_value

    mock_nb.status.assert_called_once_with()


def test_setup_periodic_tasks_is_noop():
    assert netbox.setup_periodic_tasks(sender=None) is None
