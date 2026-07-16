# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the cloud credential/environment helpers of
``osism/tasks/openstack.py``.

Covers ``get_cloud_password``, ``get_cloud_helpers``,
``setup_cloud_environment``, ``cleanup_cloud_environment``, the module-level
two-argument ``get_openstack_connection`` and ``run_openstack_command_with_cloud``.

Every external effect is mocked: the environment helpers never touch the real
filesystem or working directory because the module-level ``os``/``shutil``/
``yaml`` name bindings (plus ``builtins.open``) are patched (see the shared
``mock_os`` fixture in ``conftest.py``). The module-level
``get_openstack_connection(cloud, password)`` is exercised against a patched
``openstack.connect``; ``openstacksdk`` and ``keystoneauth1`` are pinned runtime
dependencies, so their real exception classes are raised instead of stand-ins.
"""

from types import SimpleNamespace
from unittest.mock import call

import keystoneauth1.exceptions
import openstack.exceptions
import pytest

from osism.tasks import openstack as openstack_tasks

SECRETS_PATH = "/opt/configuration/environments/openstack/secrets.yml"

Unauthorized = keystoneauth1.exceptions.http.Unauthorized
SDKException = openstack.exceptions.SDKException


def _missing_options(*dests):
    """Build a real ``MissingRequiredOptions`` whose message names ``dests``."""
    return keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions(
        [SimpleNamespace(dest=dest) for dest in dests]
    )


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _exists_only(fake_os, *paths):
    """Make the patched ``os.path.exists`` report exactly ``paths`` as present."""
    existing = set(paths)
    fake_os.path.exists.side_effect = lambda path: path in existing


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def secrets(mocker, mock_os):
    """An existing secrets file whose parsed content the test controls."""
    mock_os.path.exists.return_value = True
    return mocker.patch("osism.tasks.openstack.load_yaml_file")


@pytest.fixture
def cloud_env(mocker, mock_os):
    """Mock every external effect of ``setup_cloud_environment``.

    By default no path exists, ``get_cloud_password`` yields ``"hunter2"``
    (password branch) and ``open``/``yaml``/``shutil`` are inert mocks.
    """
    get_cloud_password = mocker.patch(
        "osism.tasks.openstack.get_cloud_password", return_value="hunter2"
    )
    fake_shutil = mocker.patch("osism.tasks.openstack.shutil")
    fake_yaml = mocker.patch("osism.tasks.openstack.yaml")
    open_ = mocker.patch("builtins.open", mocker.mock_open())
    return SimpleNamespace(
        os=mock_os,
        get_cloud_password=get_cloud_password,
        shutil=fake_shutil,
        yaml=fake_yaml,
        open=open_,
    )


@pytest.fixture
def mock_connect(mocker, mock_os):
    """Patch ``openstack.connect`` at source; no secure.yml exists by default."""
    return mocker.patch("openstack.connect")


@pytest.fixture
def command_env(mocker):
    """Mock the collaborators of ``run_openstack_command_with_cloud``."""
    setup = mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=("pw", ["/tmp/clouds.yaml"], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command", return_value=0)
    return SimpleNamespace(setup=setup, cleanup=cleanup, run=run)


# ---------------------------------------------------------------------------
# get_cloud_password
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cloud", [None, ""], ids=["none", "empty"])
def test_get_cloud_password_requires_cloud(mocker, loguru_logs, cloud):
    """A falsy cloud short-circuits with a warning before any file access."""
    load = mocker.patch("osism.tasks.openstack.load_yaml_file")

    assert openstack_tasks.get_cloud_password(cloud) is None

    load.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "No cloud parameter provided")


def test_get_cloud_password_missing_secrets_file(mocker, mock_os, loguru_logs):
    """A missing secrets file yields ``None`` without parsing anything."""
    load = mocker.patch("osism.tasks.openstack.load_yaml_file")

    assert openstack_tasks.get_cloud_password("admin") is None

    mock_os.path.exists.assert_called_once_with(SECRETS_PATH)
    load.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "Secrets file not found")


@pytest.mark.parametrize("content", [None, ["not", "a", "dict"]], ids=["none", "list"])
def test_get_cloud_password_invalid_secrets_content(secrets, loguru_logs, content):
    """``None`` or non-dict content from the YAML loader is rejected."""
    secrets.return_value = content

    assert openstack_tasks.get_cloud_password("admin") is None

    assert _has_log(loguru_logs, "WARNING", "Empty or invalid secrets file")


def test_get_cloud_password_normalizes_hyphens(secrets):
    """Hyphens in the cloud name map to underscores in the password key."""
    secrets.return_value = {"os_password_admin_system": "pw"}

    assert openstack_tasks.get_cloud_password("admin-system") == "pw"

    secrets.assert_called_once_with(SECRETS_PATH)


def test_get_cloud_password_rejects_non_identifier_key(secrets, loguru_logs):
    """A cloud name producing a non-identifier key is refused with an error."""
    secrets.return_value = {"os_password_admin": "pw"}

    assert openstack_tasks.get_cloud_password("admin system") is None

    assert _has_log(loguru_logs, "ERROR", "Invalid password key format")


def test_get_cloud_password_key_not_found(secrets, loguru_logs):
    """A missing password key is only a debug event, not a warning."""
    secrets.return_value = {"os_password_other": "pw"}

    assert openstack_tasks.get_cloud_password("admin") is None

    assert _has_log(loguru_logs, "DEBUG", "not found")
    assert not any(r["level"] in ("WARNING", "ERROR") for r in loguru_logs)


def test_get_cloud_password_strips_whitespace(secrets):
    secrets.return_value = {"os_password_admin": "  hunter2  "}

    assert openstack_tasks.get_cloud_password("admin") == "hunter2"


def test_get_cloud_password_coerces_to_string(secrets):
    """Non-string values (e.g. YAML integers) are coerced via ``str``."""
    secrets.return_value = {"os_password_admin": 42}

    assert openstack_tasks.get_cloud_password("admin") == "42"


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace"])
def test_get_cloud_password_empty_value(secrets, loguru_logs, value):
    """Values that are empty after stripping yield ``None`` with a warning."""
    secrets.return_value = {"os_password_admin": value}

    assert openstack_tasks.get_cloud_password("admin") is None

    assert _has_log(loguru_logs, "WARNING", "empty after conversion")


def test_get_cloud_password_load_error(secrets, loguru_logs):
    """Loader exceptions are swallowed and logged as errors."""
    secrets.side_effect = Exception("vault broken")

    assert openstack_tasks.get_cloud_password("admin") is None

    assert _has_log(loguru_logs, "ERROR", "Failed to load/decrypt password")


# ---------------------------------------------------------------------------
# get_cloud_helpers
# ---------------------------------------------------------------------------


def test_get_cloud_helpers_returns_helper_triple():
    assert openstack_tasks.get_cloud_helpers() == (
        openstack_tasks.setup_cloud_environment,
        openstack_tasks.get_openstack_connection,
        openstack_tasks.cleanup_cloud_environment,
    )


# ---------------------------------------------------------------------------
# setup_cloud_environment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cloud", [None, ""], ids=["none", "empty"])
def test_setup_cloud_environment_requires_cloud(cloud_env, loguru_logs, cloud):
    """A falsy cloud fails the setup before any password lookup."""
    result = openstack_tasks.setup_cloud_environment(cloud)

    assert result == (None, [], "/orig", False)
    cloud_env.get_cloud_password.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "No cloud parameter provided")


def test_setup_cloud_environment_injects_password(cloud_env):
    """Password branch: the password is injected into the cloud profile, the
    combined config plus an empty secure.yml land in /tmp and the working
    directory changes there."""
    _exists_only(cloud_env.os, "/etc/openstack/clouds.yaml")
    clouds_config = {"clouds": {"admin": {"auth": {"username": "u"}}}}
    cloud_env.yaml.safe_load.return_value = clouds_config

    result = openstack_tasks.setup_cloud_environment("admin")

    handle = cloud_env.open.return_value
    cloud_env.open.assert_any_call("/etc/openstack/clouds.yaml", "r")
    cloud_env.open.assert_any_call("/tmp/clouds.yaml", "w")
    cloud_env.open.assert_any_call("/tmp/secure.yml", "w")
    cloud_env.yaml.safe_load.assert_called_once_with(handle)
    assert clouds_config["clouds"]["admin"]["auth"]["password"] == "hunter2"
    assert cloud_env.yaml.dump.call_args_list == [
        call(clouds_config, handle),
        call({}, handle),
    ]
    cloud_env.os.chdir.assert_called_once_with("/tmp")
    assert result == ("hunter2", ["/tmp/clouds.yaml", "/tmp/secure.yml"], "/orig", True)


def test_setup_cloud_environment_clouds_yml_variant(cloud_env):
    """Only ``clouds.yml`` present: the /tmp copy keeps the ``.yml`` suffix."""
    _exists_only(cloud_env.os, "/etc/openstack/clouds.yml")
    cloud_env.yaml.safe_load.return_value = {"clouds": {"admin": {"auth": {}}}}

    result = openstack_tasks.setup_cloud_environment("admin")

    cloud_env.open.assert_any_call("/etc/openstack/clouds.yml", "r")
    cloud_env.open.assert_any_call("/tmp/clouds.yml", "w")
    assert result == ("hunter2", ["/tmp/clouds.yml", "/tmp/secure.yml"], "/orig", True)


def test_setup_cloud_environment_creates_auth_section(cloud_env):
    """A cloud profile without an ``auth`` key gets one before injection."""
    _exists_only(cloud_env.os, "/etc/openstack/clouds.yaml")
    clouds_config = {"clouds": {"admin": {}}}
    cloud_env.yaml.safe_load.return_value = clouds_config

    result = openstack_tasks.setup_cloud_environment("admin")

    assert clouds_config["clouds"]["admin"]["auth"] == {"password": "hunter2"}
    assert result[3] is True


def test_setup_cloud_environment_cloud_missing_from_config(cloud_env, loguru_logs):
    """A cloud profile absent from the clouds config fails the setup."""
    _exists_only(cloud_env.os, "/etc/openstack/clouds.yaml")
    cloud_env.yaml.safe_load.return_value = {"clouds": {"other": {}}}

    result = openstack_tasks.setup_cloud_environment("admin")

    assert result == (None, [], "/orig", False)
    cloud_env.os.chdir.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "not found in clouds config")


def test_setup_cloud_environment_without_clouds_file(cloud_env):
    """No clouds.yaml at all: the password is still returned for direct SDK
    usage, without any temp files or directory change."""
    result = openstack_tasks.setup_cloud_environment("admin")

    assert result == ("hunter2", [], "/orig", True)
    cloud_env.os.chdir.assert_not_called()
    cloud_env.open.assert_not_called()


def test_setup_cloud_environment_write_error(cloud_env, loguru_logs):
    """Errors while reading/writing the config fail the setup."""
    _exists_only(cloud_env.os, "/etc/openstack/clouds.yaml")
    cloud_env.yaml.safe_load.side_effect = Exception("bad yaml")

    result = openstack_tasks.setup_cloud_environment("admin")

    assert result == (None, [], "/orig", False)
    assert _has_log(loguru_logs, "ERROR", "Failed to set up cloud environment")


def test_setup_cloud_environment_secure_yml_fallback(cloud_env):
    """Fallback branch: without a password, clouds.yaml and secure.yml are
    copied to /tmp and the working directory changes there."""
    cloud_env.get_cloud_password.return_value = None
    _exists_only(
        cloud_env.os, "/etc/openstack/secure.yml", "/etc/openstack/clouds.yaml"
    )

    result = openstack_tasks.setup_cloud_environment("admin")

    assert cloud_env.shutil.copy2.call_args_list == [
        call("/etc/openstack/clouds.yaml", "/tmp/clouds.yaml"),
        call("/etc/openstack/secure.yml", "/tmp/secure.yml"),
    ]
    cloud_env.os.chdir.assert_called_once_with("/tmp")
    assert result == (None, ["/tmp/clouds.yaml", "/tmp/secure.yml"], "/orig", True)


def test_setup_cloud_environment_secure_yaml_variant(cloud_env):
    """Only ``secure.yaml`` present: the /tmp copy keeps the ``.yaml`` suffix."""
    cloud_env.get_cloud_password.return_value = None
    _exists_only(cloud_env.os, "/etc/openstack/secure.yaml")

    result = openstack_tasks.setup_cloud_environment("admin")

    cloud_env.shutil.copy2.assert_called_once_with(
        "/etc/openstack/secure.yaml", "/tmp/secure.yaml"
    )
    assert result == (None, ["/tmp/secure.yaml"], "/orig", True)


def test_setup_cloud_environment_no_credentials(cloud_env, loguru_logs):
    """Neither a password nor a secure file: the error names the expected
    ``os_password_<cloud>`` key with hyphens normalized."""
    cloud_env.get_cloud_password.return_value = None

    result = openstack_tasks.setup_cloud_environment("admin-system")

    assert result == (None, [], "/orig", False)
    assert _has_log(loguru_logs, "ERROR", "os_password_admin_system")


def test_setup_cloud_environment_copy_error(cloud_env, loguru_logs):
    """A failing copy in the fallback branch fails the setup."""
    cloud_env.get_cloud_password.return_value = None
    _exists_only(cloud_env.os, "/etc/openstack/secure.yml")
    cloud_env.shutil.copy2.side_effect = OSError("disk full")

    result = openstack_tasks.setup_cloud_environment("admin")

    assert result == (None, [], "/orig", False)
    assert _has_log(loguru_logs, "ERROR", "Failed to copy config files")


# ---------------------------------------------------------------------------
# cleanup_cloud_environment
# ---------------------------------------------------------------------------


def test_cleanup_restores_cwd_and_removes_files(mock_os):
    mock_os.path.exists.return_value = True

    openstack_tasks.cleanup_cloud_environment(["/tmp/a", "/tmp/b"], "/orig")

    mock_os.chdir.assert_called_once_with("/orig")
    assert mock_os.remove.call_args_list == [call("/tmp/a"), call("/tmp/b")]


def test_cleanup_survives_chdir_failure(mock_os, loguru_logs):
    """A failing ``chdir`` is only a warning; files are still removed."""
    mock_os.path.exists.return_value = True
    mock_os.chdir.side_effect = OSError("gone")

    openstack_tasks.cleanup_cloud_environment(["/tmp/a"], "/orig")

    mock_os.remove.assert_called_once_with("/tmp/a")
    assert _has_log(
        loguru_logs, "WARNING", "Could not restore original working directory"
    )


def test_cleanup_skips_missing_files(mock_os):
    mock_os.path.exists.return_value = False

    openstack_tasks.cleanup_cloud_environment(["/tmp/a"], "/orig")

    mock_os.remove.assert_not_called()


def test_cleanup_continues_after_remove_failure(mock_os, loguru_logs):
    """A failing removal is only a warning; remaining files are processed."""
    mock_os.path.exists.return_value = True
    mock_os.remove.side_effect = [OSError("busy"), None]

    openstack_tasks.cleanup_cloud_environment(["/tmp/a", "/tmp/b"], "/orig")

    assert mock_os.remove.call_args_list == [call("/tmp/a"), call("/tmp/b")]
    assert _has_log(loguru_logs, "WARNING", "Could not remove temporary file /tmp/a")


# ---------------------------------------------------------------------------
# get_openstack_connection (module-level two-argument helper)
# ---------------------------------------------------------------------------


def test_connection_with_password(mocker, mock_connect):
    """With a password, ``connect`` gets the auth override and the connection
    is verified by touching ``current_project``."""
    conn = mocker.MagicMock()
    project = mocker.PropertyMock(return_value="proj")
    type(conn).current_project = project
    mock_connect.return_value = conn

    result = openstack_tasks.get_openstack_connection("admin", password="pw")

    mock_connect.assert_called_once_with(cloud="admin", auth={"password": "pw"})
    project.assert_called_once_with()
    assert result is conn


def test_connection_password_fallback_to_secure_yml(mocker, mock_connect, mock_os):
    """``Unauthorized`` with an existing secure.yml retries without the
    password override."""
    mock_os.path.exists.side_effect = lambda p: p == "/etc/openstack/secure.yml"
    fallback_conn = mocker.MagicMock()
    mock_connect.side_effect = [Unauthorized(), fallback_conn]

    result = openstack_tasks.get_openstack_connection("admin", password="wrong")

    assert result is fallback_conn
    assert mock_connect.call_args_list == [
        call(cloud="admin", auth={"password": "wrong"}),
        call(cloud="admin"),
    ]


def test_connection_password_unauthorized_without_secure_yml(mock_connect, loguru_logs):
    """``Unauthorized`` without a secure.yml exits; the error names the
    normalized password key."""
    mock_connect.side_effect = Unauthorized()

    with pytest.raises(SystemExit) as excinfo:
        openstack_tasks.get_openstack_connection("admin-system", password="wrong")

    assert excinfo.value.code == 1
    assert _has_log(loguru_logs, "ERROR", "os_password_admin_system")


def test_connection_password_missing_options(mock_connect, loguru_logs):
    mock_connect.side_effect = _missing_options("auth_url")

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin", password="pw")

    assert _has_log(loguru_logs, "ERROR", "Missing configuration for cloud 'admin'")


def test_connection_password_sdk_error(mock_connect, loguru_logs):
    mock_connect.side_effect = SDKException("boom")

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin", password="pw")

    assert _has_log(loguru_logs, "ERROR", "OpenStack SDK error")


def test_connection_without_password(mocker, mock_connect):
    conn = mocker.MagicMock()
    mock_connect.return_value = conn

    result = openstack_tasks.get_openstack_connection("admin")

    mock_connect.assert_called_once_with(cloud="admin")
    assert result is conn


def test_connection_without_password_missing_password_option(mock_connect, loguru_logs):
    """A ``MissingRequiredOptions`` naming the password produces the specific
    "No password configured" error."""
    mock_connect.side_effect = _missing_options("password")

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin-system")

    assert _has_log(
        loguru_logs, "ERROR", "No password configured for cloud 'admin-system'"
    )
    assert _has_log(loguru_logs, "ERROR", "os_password_admin_system")


def test_connection_without_password_missing_other_option(mock_connect, loguru_logs):
    """Other missing options produce the generic configuration error."""
    mock_connect.side_effect = _missing_options("auth_url")

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin")

    assert _has_log(loguru_logs, "ERROR", "Missing configuration for cloud 'admin'")


def test_connection_without_password_unauthorized(mock_connect, loguru_logs):
    mock_connect.side_effect = Unauthorized()

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin")

    assert _has_log(loguru_logs, "ERROR", "Authentication failed for cloud 'admin'")


def test_connection_without_password_sdk_error(mock_connect, loguru_logs):
    mock_connect.side_effect = SDKException("boom")

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin")

    assert _has_log(loguru_logs, "ERROR", "OpenStack SDK error")


def test_connection_test_failure_after_connect(mocker, mock_connect):
    """``connect`` succeeds but the ``current_project`` probe fails."""
    conn = mocker.MagicMock()
    type(conn).current_project = mocker.PropertyMock(
        side_effect=SDKException("no project")
    )
    mock_connect.return_value = conn

    with pytest.raises(SystemExit):
        openstack_tasks.get_openstack_connection("admin", password="pw")


# ---------------------------------------------------------------------------
# run_openstack_command_with_cloud
# ---------------------------------------------------------------------------


def test_run_openstack_command_with_cloud_delegates(command_env):
    result = openstack_tasks.run_openstack_command_with_cloud(
        "req-1",
        "/usr/local/bin/x",
        "admin",
        ["--a", "--b"],
        publish=False,
        locking=True,
        auto_release_time=60,
    )

    command_env.setup.assert_called_once_with("admin")
    command_env.run.assert_called_once_with(
        "req-1",
        "/usr/local/bin/x",
        {},
        "--a",
        "--b",
        publish=False,
        locking=True,
        auto_release_time=60,
        ignore_env=True,
    )
    command_env.cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")
    assert result == 0


def test_run_openstack_command_with_cloud_cleans_up_on_error(command_env):
    """The temp files from setup are cleaned up even when the command fails."""
    command_env.run.side_effect = RuntimeError("worker died")

    with pytest.raises(RuntimeError):
        openstack_tasks.run_openstack_command_with_cloud("req-1", "/bin/x", "admin", [])

    command_env.cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")


def test_run_openstack_command_with_cloud_aborts_on_setup_failure(
    command_env, loguru_logs
):
    """A failed setup short-circuits: the command is never run without
    credentials; cleanup still runs."""
    command_env.setup.return_value = (None, [], "/orig", False)

    result = openstack_tasks.run_openstack_command_with_cloud(
        "req-1", "/bin/x", "admin", []
    )

    assert result == 1
    command_env.run.assert_not_called()
    command_env.cleanup.assert_called_once_with([], "/orig")
    assert _has_log(loguru_logs, "ERROR", "cloud environment setup failed")
