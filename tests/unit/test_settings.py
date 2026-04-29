# SPDX-License-Identifier: Apache-2.0

import builtins
import importlib
from unittest.mock import mock_open

import pytest

from osism import settings as settings_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _install_open_patch(monkeypatch, secrets):
    """Patch builtins.open to intercept reads under ``/run/secrets/``.

    Names listed in ``secrets`` are served from the in-memory mapping; any
    other name under ``/run/secrets/`` raises ``FileNotFoundError`` so the
    test environment is independent of files that may exist on the host.
    """
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        path_str = path if isinstance(path, str) else str(path)
        if path_str.startswith("/run/secrets/"):
            name = path_str.removeprefix("/run/secrets/")
            if name in secrets:
                return mock_open(read_data=secrets[name])()
            raise FileNotFoundError(2, "No such file or directory", path_str)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


@pytest.fixture
def reload_settings(monkeypatch):
    """Return a callable that reloads ``osism.settings`` with mocked secrets.

    The fixture installs an ``open()`` patch that prevents the settings
    module from reading real ``/run/secrets/*`` files. Pass a mapping like
    ``{"NETBOX_TOKEN": "abc\\n"}`` to make specific secrets available.
    """
    secrets: dict[str, str] = {}
    _install_open_patch(monkeypatch, secrets)

    def _reload(secrets_override=None):
        secrets.clear()
        if secrets_override:
            secrets.update(secrets_override)
        return importlib.reload(settings_module)

    return _reload


@pytest.fixture(autouse=True, scope="module")
def _restore_settings_module_state():
    """Reload ``osism.settings`` after this test module finishes.

    Each test that mutates env vars uses ``monkeypatch`` (which restores
    them at teardown). Reloading once at module teardown picks up the
    restored env so other test modules see the original state.
    """
    yield
    importlib.reload(settings_module)


# ---------------------------------------------------------------------------
# read_secret
# ---------------------------------------------------------------------------


def test_read_secret_returns_stripped_content(monkeypatch):
    monkeypatch.setattr(builtins, "open", mock_open(read_data="abc\n"))

    assert settings_module.read_secret("X") == "abc"


def test_read_secret_missing_file_returns_empty_string(monkeypatch):
    def raising_open(*args, **kwargs):
        raise FileNotFoundError(2, "No such file", "/run/secrets/X")

    monkeypatch.setattr(builtins, "open", raising_open)

    assert settings_module.read_secret("X") == ""


def test_read_secret_permission_error_returns_empty_string(monkeypatch):
    def raising_open(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "/run/secrets/X")

    monkeypatch.setattr(builtins, "open", raising_open)

    assert settings_module.read_secret("X") == ""


def test_read_secret_is_a_directory_returns_empty_string(monkeypatch):
    def raising_open(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory", "/run/secrets/X")

    monkeypatch.setattr(builtins, "open", raising_open)

    assert settings_module.read_secret("X") == ""


def test_read_secret_generic_oserror_returns_empty_string(monkeypatch):
    # The implementation catches ``EnvironmentError`` (== ``OSError``), so
    # any ``OSError`` subclass — not only the three explicit cases above —
    # is swallowed and yields an empty string.
    def raising_open(*args, **kwargs):
        raise OSError(5, "Input/output error", "/run/secrets/X")

    monkeypatch.setattr(builtins, "open", raising_open)

    assert settings_module.read_secret("X") == ""


def test_read_secret_non_oserror_propagates(monkeypatch):
    # Exceptions that are not ``OSError`` subclasses must bubble up.
    def raising_open(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(builtins, "open", raising_open)

    with pytest.raises(RuntimeError, match="boom"):
        settings_module.read_secret("X")


def test_read_secret_empty_file_returns_empty_string(monkeypatch):
    monkeypatch.setattr(builtins, "open", mock_open(read_data=""))

    assert settings_module.read_secret("X") == ""


def test_read_secret_strips_leading_and_trailing_whitespace(monkeypatch):
    monkeypatch.setattr(builtins, "open", mock_open(read_data="   abc \t \n"))

    # The implementation calls ``.strip()`` which removes both leading and
    # trailing whitespace; pin the actual behaviour as a regression guard.
    assert settings_module.read_secret("X") == "abc"


def test_read_secret_preserves_internal_whitespace(monkeypatch):
    monkeypatch.setattr(builtins, "open", mock_open(read_data="ab cd\n"))

    assert settings_module.read_secret("X") == "ab cd"


def test_read_secret_returns_only_first_line(monkeypatch):
    monkeypatch.setattr(builtins, "open", mock_open(read_data="line1\nline2\n"))

    assert settings_module.read_secret("X") == "line1"


def test_read_secret_uses_secret_name_in_path(monkeypatch):
    captured = {}

    def fake_open(path, *args, **kwargs):
        captured["path"] = path
        return mock_open(read_data="value\n")()

    monkeypatch.setattr(builtins, "open", fake_open)

    settings_module.read_secret("MY_SECRET")

    assert captured["path"] == "/run/secrets/MY_SECRET"


# ---------------------------------------------------------------------------
# OPENSEARCH_*
# ---------------------------------------------------------------------------


def test_opensearch_address_default_is_none(reload_settings, monkeypatch):
    monkeypatch.delenv("OPENSEARCH_ADDRESS", raising=False)
    reload_settings()

    assert settings_module.OPENSEARCH_ADDRESS is None


def test_opensearch_protocol_default_is_https(reload_settings, monkeypatch):
    monkeypatch.delenv("OPENSEARCH_PROTOCOL", raising=False)
    reload_settings()

    assert settings_module.OPENSEARCH_PROTOCOL == "https"


def test_opensearch_protocol_override(reload_settings, monkeypatch):
    monkeypatch.setenv("OPENSEARCH_PROTOCOL", "http")
    reload_settings()

    assert settings_module.OPENSEARCH_PROTOCOL == "http"


def test_opensearch_port_default_is_none(reload_settings, monkeypatch):
    monkeypatch.delenv("OPENSEARCH_PORT", raising=False)
    reload_settings()

    assert settings_module.OPENSEARCH_PORT is None


# ---------------------------------------------------------------------------
# REDIS_*
# ---------------------------------------------------------------------------


def test_redis_host_default(reload_settings, monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    reload_settings()

    assert settings_module.REDIS_HOST == "redis"


def test_redis_host_override(reload_settings, monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "mycache")
    reload_settings()

    assert settings_module.REDIS_HOST == "mycache"


def test_redis_port_default_is_int(reload_settings, monkeypatch):
    monkeypatch.delenv("REDIS_PORT", raising=False)
    reload_settings()

    assert settings_module.REDIS_PORT == 6379
    assert isinstance(settings_module.REDIS_PORT, int)


def test_redis_port_override_is_int(reload_settings, monkeypatch):
    monkeypatch.setenv("REDIS_PORT", "1234")
    reload_settings()

    assert settings_module.REDIS_PORT == 1234
    assert isinstance(settings_module.REDIS_PORT, int)


def test_redis_port_invalid_raises_at_import(reload_settings, monkeypatch):
    monkeypatch.setenv("REDIS_PORT", "not-an-int")

    with pytest.raises(ValueError):
        reload_settings()


def test_redis_db_default_is_int(reload_settings, monkeypatch):
    monkeypatch.delenv("REDIS_DB", raising=False)
    reload_settings()

    assert settings_module.REDIS_DB == 0
    assert isinstance(settings_module.REDIS_DB, int)


def test_redis_db_override(reload_settings, monkeypatch):
    monkeypatch.setenv("REDIS_DB", "5")
    reload_settings()

    assert settings_module.REDIS_DB == 5


# ---------------------------------------------------------------------------
# NETBOX_URL
# ---------------------------------------------------------------------------


def test_netbox_url_default_is_none(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_API", raising=False)
    monkeypatch.delenv("NETBOX_URL", raising=False)
    reload_settings()

    assert settings_module.NETBOX_URL is None


def test_netbox_url_uses_netbox_url_when_only_it_is_set(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_API", raising=False)
    monkeypatch.setenv("NETBOX_URL", "https://netbox.example.com")
    reload_settings()

    assert settings_module.NETBOX_URL == "https://netbox.example.com"


def test_netbox_url_uses_netbox_api_when_only_it_is_set(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_API", "https://api.example.com")
    monkeypatch.delenv("NETBOX_URL", raising=False)
    reload_settings()

    assert settings_module.NETBOX_URL == "https://api.example.com"


def test_netbox_url_netbox_api_wins_over_netbox_url(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_API", "https://api.example.com")
    monkeypatch.setenv("NETBOX_URL", "https://netbox.example.com")
    reload_settings()

    assert settings_module.NETBOX_URL == "https://api.example.com"


# ---------------------------------------------------------------------------
# NETBOX_TOKEN
# ---------------------------------------------------------------------------


def test_netbox_token_default_is_empty_string(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    reload_settings()

    assert settings_module.NETBOX_TOKEN == ""


def test_netbox_token_env_var_wins(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_TOKEN", "env-token")
    reload_settings({"NETBOX_TOKEN": "secret-token\n"})

    assert settings_module.NETBOX_TOKEN == "env-token"


def test_netbox_token_falls_back_to_secret_when_env_unset(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    reload_settings({"NETBOX_TOKEN": "secret-token\n"})

    assert settings_module.NETBOX_TOKEN == "secret-token"


def test_netbox_token_falls_back_to_secret_when_env_is_empty(
    reload_settings, monkeypatch
):
    monkeypatch.setenv("NETBOX_TOKEN", "")
    reload_settings({"NETBOX_TOKEN": "secret-token\n"})

    assert settings_module.NETBOX_TOKEN == "secret-token"


def test_netbox_token_strips_whitespace_from_env(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_TOKEN", "  spaced-token  ")
    reload_settings()

    assert settings_module.NETBOX_TOKEN == "spaced-token"


# ---------------------------------------------------------------------------
# IGNORE_SSL_ERRORS
# ---------------------------------------------------------------------------


def test_ignore_ssl_errors_default_is_true(reload_settings, monkeypatch):
    monkeypatch.delenv("IGNORE_SSL_ERRORS", raising=False)
    reload_settings()

    assert settings_module.IGNORE_SSL_ERRORS is True


def test_ignore_ssl_errors_explicit_true(reload_settings, monkeypatch):
    monkeypatch.setenv("IGNORE_SSL_ERRORS", "True")
    reload_settings()

    assert settings_module.IGNORE_SSL_ERRORS is True


def test_ignore_ssl_errors_explicit_false(reload_settings, monkeypatch):
    monkeypatch.setenv("IGNORE_SSL_ERRORS", "False")
    reload_settings()

    assert settings_module.IGNORE_SSL_ERRORS is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "", "anything"])
def test_ignore_ssl_errors_only_capital_true_is_true(
    reload_settings, monkeypatch, value
):
    monkeypatch.setenv("IGNORE_SSL_ERRORS", value)
    reload_settings()

    assert settings_module.IGNORE_SSL_ERRORS is False


# ---------------------------------------------------------------------------
# GATHER_FACTS_SCHEDULE / FACTS_MAX_AGE / INVENTORY_RECONCILER_SCHEDULE
# ---------------------------------------------------------------------------


def test_gather_facts_schedule_default(reload_settings, monkeypatch):
    monkeypatch.delenv("GATHER_FACTS_SCHEDULE", raising=False)
    reload_settings()

    assert settings_module.GATHER_FACTS_SCHEDULE == 43200.0
    assert isinstance(settings_module.GATHER_FACTS_SCHEDULE, float)


def test_gather_facts_schedule_override_int_string_becomes_float(
    reload_settings, monkeypatch
):
    monkeypatch.setenv("GATHER_FACTS_SCHEDULE", "60")
    reload_settings()

    assert settings_module.GATHER_FACTS_SCHEDULE == 60.0
    assert isinstance(settings_module.GATHER_FACTS_SCHEDULE, float)


def test_facts_max_age_default_matches_int_of_gather_facts_schedule(
    reload_settings, monkeypatch
):
    monkeypatch.delenv("GATHER_FACTS_SCHEDULE", raising=False)
    monkeypatch.delenv("FACTS_MAX_AGE", raising=False)
    reload_settings()

    assert settings_module.FACTS_MAX_AGE == 43200
    assert isinstance(settings_module.FACTS_MAX_AGE, int)


def test_facts_max_age_tracks_gather_facts_schedule_when_unset(
    reload_settings, monkeypatch
):
    monkeypatch.setenv("GATHER_FACTS_SCHEDULE", "120.5")
    monkeypatch.delenv("FACTS_MAX_AGE", raising=False)
    reload_settings()

    # int(120.5) == 120 — the default for FACTS_MAX_AGE truncates the float.
    assert settings_module.FACTS_MAX_AGE == 120


def test_facts_max_age_explicit_override_wins(reload_settings, monkeypatch):
    monkeypatch.setenv("GATHER_FACTS_SCHEDULE", "60")
    monkeypatch.setenv("FACTS_MAX_AGE", "999")
    reload_settings()

    assert settings_module.FACTS_MAX_AGE == 999


def test_inventory_reconciler_schedule_default(reload_settings, monkeypatch):
    monkeypatch.delenv("INVENTORY_RECONCILER_SCHEDULE", raising=False)
    reload_settings()

    assert settings_module.INVENTORY_RECONCILER_SCHEDULE == 600.0
    assert isinstance(settings_module.INVENTORY_RECONCILER_SCHEDULE, float)


def test_inventory_reconciler_schedule_override(reload_settings, monkeypatch):
    monkeypatch.setenv("INVENTORY_RECONCILER_SCHEDULE", "300")
    reload_settings()

    assert settings_module.INVENTORY_RECONCILER_SCHEDULE == 300.0


# ---------------------------------------------------------------------------
# OSISM_API_URL / OPERATOR_USER / FRR_DUMMY_INTERFACE
# ---------------------------------------------------------------------------


def test_osism_api_url_default_is_none(reload_settings, monkeypatch):
    monkeypatch.delenv("OSISM_API_URL", raising=False)
    reload_settings()

    assert settings_module.OSISM_API_URL is None


def test_osism_api_url_override(reload_settings, monkeypatch):
    monkeypatch.setenv("OSISM_API_URL", "https://osism.example.com")
    reload_settings()

    assert settings_module.OSISM_API_URL == "https://osism.example.com"


def test_operator_user_default(reload_settings, monkeypatch):
    monkeypatch.delenv("OSISM_OPERATOR_USER", raising=False)
    reload_settings()

    assert settings_module.OPERATOR_USER == "dragon"


def test_operator_user_override(reload_settings, monkeypatch):
    monkeypatch.setenv("OSISM_OPERATOR_USER", "admin")
    reload_settings()

    assert settings_module.OPERATOR_USER == "admin"


def test_frr_dummy_interface_default(reload_settings, monkeypatch):
    monkeypatch.delenv("OSISM_FRR_DUMMY_INTERFACE", raising=False)
    reload_settings()

    assert settings_module.FRR_DUMMY_INTERFACE == "loopback0"


def test_frr_dummy_interface_override(reload_settings, monkeypatch):
    monkeypatch.setenv("OSISM_FRR_DUMMY_INTERFACE", "lo1")
    reload_settings()

    assert settings_module.FRR_DUMMY_INTERFACE == "lo1"


# ---------------------------------------------------------------------------
# NETBOX_FILTER_CONDUCTOR_*
# ---------------------------------------------------------------------------


def test_netbox_filter_conductor_ironic_default(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_FILTER_CONDUCTOR_IRONIC", raising=False)
    reload_settings()

    assert (
        settings_module.NETBOX_FILTER_CONDUCTOR_IRONIC
        == settings_module.DEFAULT_NETBOX_FILTER_CONDUCTOR_IRONIC
    )


def test_netbox_filter_conductor_ironic_override(reload_settings, monkeypatch):
    override = "[{'status': 'active', 'tag': ['custom']}]"
    monkeypatch.setenv("NETBOX_FILTER_CONDUCTOR_IRONIC", override)
    reload_settings()

    assert settings_module.NETBOX_FILTER_CONDUCTOR_IRONIC == override


def test_netbox_filter_conductor_sonic_default(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_FILTER_CONDUCTOR_SONIC", raising=False)
    reload_settings()

    assert (
        settings_module.NETBOX_FILTER_CONDUCTOR_SONIC
        == settings_module.DEFAULT_NETBOX_FILTER_CONDUCTOR_SONIC
    )


def test_netbox_filter_conductor_sonic_override(reload_settings, monkeypatch):
    override = "[{'status': 'active', 'tag': ['custom-metalbox']}]"
    monkeypatch.setenv("NETBOX_FILTER_CONDUCTOR_SONIC", override)
    reload_settings()

    assert settings_module.NETBOX_FILTER_CONDUCTOR_SONIC == override


# ---------------------------------------------------------------------------
# SONIC_EXPORT_*
# ---------------------------------------------------------------------------


def test_sonic_export_dir_default(reload_settings, monkeypatch):
    monkeypatch.delenv("SONIC_EXPORT_DIR", raising=False)
    reload_settings()

    assert settings_module.SONIC_EXPORT_DIR == "/etc/sonic/export"


def test_sonic_export_dir_override(reload_settings, monkeypatch):
    monkeypatch.setenv("SONIC_EXPORT_DIR", "/var/sonic")
    reload_settings()

    assert settings_module.SONIC_EXPORT_DIR == "/var/sonic"


def test_sonic_export_prefix_default(reload_settings, monkeypatch):
    monkeypatch.delenv("SONIC_EXPORT_PREFIX", raising=False)
    reload_settings()

    assert settings_module.SONIC_EXPORT_PREFIX == "osism_"


def test_sonic_export_suffix_default(reload_settings, monkeypatch):
    monkeypatch.delenv("SONIC_EXPORT_SUFFIX", raising=False)
    reload_settings()

    assert settings_module.SONIC_EXPORT_SUFFIX == "_config_db.json"


def test_sonic_export_identifier_default(reload_settings, monkeypatch):
    monkeypatch.delenv("SONIC_EXPORT_IDENTIFIER", raising=False)
    reload_settings()

    assert settings_module.SONIC_EXPORT_IDENTIFIER == "serial-number"


def test_sonic_export_identifier_override(reload_settings, monkeypatch):
    monkeypatch.setenv("SONIC_EXPORT_IDENTIFIER", "asset-tag")
    reload_settings()

    assert settings_module.SONIC_EXPORT_IDENTIFIER == "asset-tag"


# ---------------------------------------------------------------------------
# NETBOX_SECONDARIES
# ---------------------------------------------------------------------------


def test_netbox_secondaries_default_is_empty_list_literal(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_SECONDARIES", raising=False)
    reload_settings()

    assert settings_module.NETBOX_SECONDARIES == "[]"


def test_netbox_secondaries_env_var_wins(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_SECONDARIES", "[1, 2, 3]")
    reload_settings({"NETBOX_SECONDARIES": "['from-secret']"})

    assert settings_module.NETBOX_SECONDARIES == "[1, 2, 3]"


def test_netbox_secondaries_falls_back_to_secret_when_env_unset(
    reload_settings, monkeypatch
):
    monkeypatch.delenv("NETBOX_SECONDARIES", raising=False)
    reload_settings({"NETBOX_SECONDARIES": "['from-secret']"})

    assert settings_module.NETBOX_SECONDARIES == "['from-secret']"


def test_netbox_secondaries_empty_env_falls_back_to_default(
    reload_settings, monkeypatch
):
    # ``os.getenv`` returns "" when the variable is set to empty; the
    # subsequent ``or "[]"`` then yields the literal default.
    monkeypatch.setenv("NETBOX_SECONDARIES", "")
    reload_settings()

    assert settings_module.NETBOX_SECONDARIES == "[]"


# ---------------------------------------------------------------------------
# REDFISH_TIMEOUT / NETBOX_MAX_CONNECTIONS
# ---------------------------------------------------------------------------


def test_redfish_timeout_default_is_int(reload_settings, monkeypatch):
    monkeypatch.delenv("REDFISH_TIMEOUT", raising=False)
    reload_settings()

    assert settings_module.REDFISH_TIMEOUT == 20
    assert isinstance(settings_module.REDFISH_TIMEOUT, int)


def test_redfish_timeout_override(reload_settings, monkeypatch):
    monkeypatch.setenv("REDFISH_TIMEOUT", "45")
    reload_settings()

    assert settings_module.REDFISH_TIMEOUT == 45


def test_netbox_max_connections_default_is_int(reload_settings, monkeypatch):
    monkeypatch.delenv("NETBOX_MAX_CONNECTIONS", raising=False)
    reload_settings()

    assert settings_module.NETBOX_MAX_CONNECTIONS == 5
    assert isinstance(settings_module.NETBOX_MAX_CONNECTIONS, int)


def test_netbox_max_connections_override(reload_settings, monkeypatch):
    monkeypatch.setenv("NETBOX_MAX_CONNECTIONS", "25")
    reload_settings()

    assert settings_module.NETBOX_MAX_CONNECTIONS == 25
