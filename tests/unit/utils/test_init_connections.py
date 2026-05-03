# SPDX-License-Identifier: Apache-2.0

"""Unit tests for connection / client initialization in ``osism.utils.__init__``.

Covers ``_init_redis``, ``_init_nb``, ``_init_secondary_nb_list``,
``_get_timeout_http_adapter_class``, ``NetBoxSessionManager``,
``cleanup_netbox_sessions``, ``get_netbox_connection``,
``get_openstack_connection`` and the lazy ``__getattr__`` indirection.
"""

import pytest

import osism.utils as utils_pkg

_MODULE_GLOBAL_DEFAULTS = {
    "_redis": None,
    "_nb": None,
    "_nb_initialized": False,
    "_secondary_nb_list": None,
    "_secondary_nb_initialized": False,
    "_cleanup_registered": False,
    "_TimeoutHTTPAdapterClass": None,
}
_SESSION_MANAGER_ATTRS = ("_session", "_lock")
_LAZY_GETATTR_NAMES = ("redis", "nb", "secondary_nb_list")


def _reset_utils_module_state():
    for name, value in _MODULE_GLOBAL_DEFAULTS.items():
        setattr(utils_pkg, name, value)
    for attr in _SESSION_MANAGER_ATTRS:
        setattr(utils_pkg.NetBoxSessionManager, attr, None)
    for name in _LAZY_GETATTR_NAMES:
        utils_pkg.__dict__.pop(name, None)


@pytest.fixture(autouse=True)
def reset_module_globals():
    """Reset every module-level cache touched by the helpers under test.

    Each test starts from a clean slate: cached connections, initialization
    flags, the lazy adapter class, and the lazy ``__getattr__`` cache attrs.
    """
    _reset_utils_module_state()
    yield
    _reset_utils_module_state()


# ---------------------------------------------------------------------------
# _init_redis
# ---------------------------------------------------------------------------


def test_init_redis_first_call_constructs_and_pings(mocker):
    mocker.patch.multiple(
        "osism.utils.settings",
        REDIS_HOST="redis-host",
        REDIS_PORT=6380,
        REDIS_DB=2,
    )
    redis_cls = mocker.patch("redis.Redis")

    result = utils_pkg._init_redis()

    redis_cls.assert_called_once_with(
        host="redis-host", port=6380, db=2, socket_keepalive=True
    )
    redis_cls.return_value.ping.assert_called_once_with()
    assert result is redis_cls.return_value
    assert utils_pkg._redis is redis_cls.return_value


def test_init_redis_caches_instance(mocker):
    mocker.patch.multiple(
        "osism.utils.settings", REDIS_HOST="h", REDIS_PORT=1, REDIS_DB=0
    )
    redis_cls = mocker.patch("redis.Redis")

    first = utils_pkg._init_redis()
    second = utils_pkg._init_redis()

    assert first is second
    assert redis_cls.call_count == 1
    assert redis_cls.return_value.ping.call_count == 1


def test_init_redis_ping_failure_propagates(mocker):
    mocker.patch.multiple(
        "osism.utils.settings", REDIS_HOST="h", REDIS_PORT=1, REDIS_DB=0
    )
    redis_cls = mocker.patch("redis.Redis")
    redis_cls.return_value.ping.side_effect = ConnectionError("boom")

    with pytest.raises(ConnectionError, match="boom"):
        utils_pkg._init_redis()


# ---------------------------------------------------------------------------
# _init_nb
# ---------------------------------------------------------------------------


def test_init_nb_delegates_and_caches(mocker):
    mocker.patch.multiple(
        "osism.utils.settings",
        NETBOX_URL="https://nb",
        NETBOX_TOKEN="token",
        IGNORE_SSL_ERRORS=True,
    )
    sentinel = object()
    get_conn = mocker.patch("osism.utils.get_netbox_connection", return_value=sentinel)

    first = utils_pkg._init_nb()

    get_conn.assert_called_once_with("https://nb", "token", True)
    assert first is sentinel
    assert utils_pkg._nb is sentinel
    assert utils_pkg._nb_initialized is True


def test_init_nb_caches_none_result(mocker):
    """When NETBOX_URL is missing, ``get_netbox_connection`` returns ``None``;
    the negative result must still be cached so subsequent calls do not
    re-invoke the connector."""
    mocker.patch.multiple(
        "osism.utils.settings",
        NETBOX_URL="",
        NETBOX_TOKEN="",
        IGNORE_SSL_ERRORS=False,
    )
    get_conn = mocker.patch("osism.utils.get_netbox_connection", return_value=None)

    first = utils_pkg._init_nb()
    second = utils_pkg._init_nb()

    assert first is None
    assert second is None
    assert utils_pkg._nb_initialized is True
    assert get_conn.call_count == 1


def test_init_nb_subsequent_call_uses_cache(mocker):
    mocker.patch.multiple(
        "osism.utils.settings",
        NETBOX_URL="https://nb",
        NETBOX_TOKEN="token",
        IGNORE_SSL_ERRORS=False,
    )
    sentinel = object()
    get_conn = mocker.patch("osism.utils.get_netbox_connection", return_value=sentinel)

    first = utils_pkg._init_nb()
    second = utils_pkg._init_nb()

    assert first is sentinel
    assert second is sentinel
    assert get_conn.call_count == 1


# ---------------------------------------------------------------------------
# _init_secondary_nb_list
# ---------------------------------------------------------------------------


def _patch_secondaries(mocker, yaml_value):
    mocker.patch.multiple("osism.utils.settings", NETBOX_SECONDARIES=yaml_value)


def test_init_secondary_nb_list_two_valid_entries(mocker):
    yaml_value = (
        "- NETBOX_URL: https://nb1\n"
        "  NETBOX_TOKEN: tok1\n"
        "- NETBOX_URL: https://nb2\n"
        "  NETBOX_TOKEN: tok2\n"
    )
    _patch_secondaries(mocker, yaml_value)
    api_a = mocker.MagicMock(name="nb1")
    api_b = mocker.MagicMock(name="nb2")
    get_conn = mocker.patch(
        "osism.utils.get_netbox_connection", side_effect=[api_a, api_b]
    )

    result = utils_pkg._init_secondary_nb_list()

    assert result == [api_a, api_b]
    assert get_conn.call_count == 2
    # IGNORE_SSL_ERRORS defaults to True when omitted
    get_conn.assert_any_call("https://nb1", "tok1", True)
    get_conn.assert_any_call("https://nb2", "tok2", True)
    assert utils_pkg._secondary_nb_initialized is True


@pytest.mark.parametrize(
    "yaml_value,expected_call,expected_name,expected_site",
    [
        pytest.param(
            "- NETBOX_URL: https://nb\n  NETBOX_TOKEN: tok\n",
            ("https://nb", "tok", True),
            None,
            None,
            id="plain",
        ),
        pytest.param(
            "- NETBOX_URL: https://nb\n  NETBOX_TOKEN: '  tok  '\n",
            ("https://nb", "tok", True),
            None,
            None,
            id="token_stripped",
        ),
        pytest.param(
            "- NETBOX_URL: https://nb1\n"
            "  NETBOX_TOKEN: tok1\n"
            "  NETBOX_NAME: primary\n"
            "  NETBOX_SITE: dc-a\n",
            ("https://nb1", "tok1", True),
            "primary",
            "dc-a",
            id="name_and_site",
        ),
    ],
)
def test_init_secondary_nb_list_single_valid_entry(
    mocker, yaml_value, expected_call, expected_name, expected_site
):
    _patch_secondaries(mocker, yaml_value)
    api = mocker.MagicMock()
    get_conn = mocker.patch("osism.utils.get_netbox_connection", return_value=api)

    result = utils_pkg._init_secondary_nb_list()

    assert result == [api]
    # The token is stripped before being passed to get_netbox_connection and
    # IGNORE_SSL_ERRORS defaults to True when omitted.
    get_conn.assert_called_once_with(*expected_call)
    if expected_name is not None:
        assert api.netbox_name == expected_name
    if expected_site is not None:
        assert api.netbox_site == expected_site


_SECONDARIES_ERROR_PREFIX = "Error parsing settings NETBOX_SECONDARIES"

# Every invalid input is funnelled through the single ``except`` branch which
# emits one ``logger.error`` call. ``detail_substring`` additionally pins the
# specific exception text where it is stable; ``None`` means only the shared
# prefix is asserted (the YAMLError text is library-version dependent).
_INVALID_SECONDARIES_CASES = [
    pytest.param("", "needs to be an array", id="empty_string"),
    pytest.param(
        "NETBOX_URL: https://nb\nNETBOX_TOKEN: tok\n",
        "needs to be an array",
        id="dict_not_list",
    ),
    pytest.param("- just-a-string\n", "need to be mappings", id="element_not_dict"),
    pytest.param(
        "- NETBOX_URL: https://nb\n  NETBOX_TOKEN: tok\n  NETBOX_FOO: bar\n",
        "Unknown key in element",
        id="unknown_key",
    ),
    pytest.param("- NETBOX_TOKEN: tok\n", "valid NetBox URLs", id="missing_url"),
    pytest.param(
        "- NETBOX_URL: ''\n  NETBOX_TOKEN: tok\n", "valid NetBox URLs", id="empty_url"
    ),
    pytest.param(
        "- NETBOX_URL: https://nb\n", "valid NetBox tokens", id="missing_token"
    ),
    pytest.param(
        "- NETBOX_URL: https://nb\n  NETBOX_TOKEN: '   '\n",
        "valid NetBox tokens",
        id="whitespace_token",
    ),
    pytest.param(":\n  - bad: : yaml\n", None, id="invalid_yaml"),
]


def _assert_secondaries_error_logged(loguru_logs, detail_substring):
    """Assert the shared error-logging path fired for an invalid input.

    Checking the common prefix for *every* case (not just some) guarantees a
    future deletion of the ``logger.error(...)`` call is caught regardless of
    which validation raised. Where the exception text is stable the per-case
    ``detail_substring`` additionally pins the specific message.
    """
    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any(_SECONDARIES_ERROR_PREFIX in m for m in error_messages), error_messages
    if detail_substring is not None:
        assert any(
            _SECONDARIES_ERROR_PREFIX in m and detail_substring in m
            for m in error_messages
        ), error_messages


@pytest.mark.parametrize("yaml_value,detail_substring", _INVALID_SECONDARIES_CASES)
def test_init_secondary_nb_list_invalid_input(
    mocker, loguru_logs, yaml_value, detail_substring
):
    _patch_secondaries(mocker, yaml_value)
    get_conn = mocker.patch("osism.utils.get_netbox_connection")

    result = utils_pkg._init_secondary_nb_list()

    assert result == []
    assert utils_pkg._secondary_nb_list == []
    assert utils_pkg._secondary_nb_initialized is True
    assert get_conn.call_count == 0
    _assert_secondaries_error_logged(loguru_logs, detail_substring)


@pytest.mark.parametrize(
    "yaml_extra,expected_flag",
    [
        pytest.param("", True, id="default"),
        pytest.param("  IGNORE_SSL_ERRORS: false\n", False, id="explicit_false"),
        pytest.param("  IGNORE_SSL_ERRORS: true\n", True, id="explicit_true"),
    ],
)
def test_init_secondary_nb_list_ignore_ssl_errors_flag(
    mocker, yaml_extra, expected_flag
):
    yaml_value = "- NETBOX_URL: https://nb\n  NETBOX_TOKEN: tok\n" + yaml_extra
    _patch_secondaries(mocker, yaml_value)
    api = mocker.MagicMock()
    get_conn = mocker.patch("osism.utils.get_netbox_connection", return_value=api)

    utils_pkg._init_secondary_nb_list()

    get_conn.assert_called_once_with("https://nb", "tok", expected_flag)


def test_init_secondary_nb_list_caches_negative_result(mocker):
    _patch_secondaries(mocker, "")
    get_conn = mocker.patch("osism.utils.get_netbox_connection")

    first = utils_pkg._init_secondary_nb_list()
    second = utils_pkg._init_secondary_nb_list()

    assert first == []
    assert second == []
    assert utils_pkg._secondary_nb_initialized is True
    assert get_conn.call_count == 0


# ---------------------------------------------------------------------------
# _get_timeout_http_adapter_class
# ---------------------------------------------------------------------------


def test_get_timeout_http_adapter_class_returns_subclass():
    from requests.adapters import HTTPAdapter

    cls = utils_pkg._get_timeout_http_adapter_class()

    assert issubclass(cls, HTTPAdapter)
    assert cls.__name__ == "_TimeoutHTTPAdapter"


def test_get_timeout_http_adapter_class_caches_class():
    first = utils_pkg._get_timeout_http_adapter_class()
    second = utils_pkg._get_timeout_http_adapter_class()
    assert first is second


def test_timeout_http_adapter_send_falls_back_to_self_timeout(mocker):
    cls = utils_pkg._get_timeout_http_adapter_class()
    adapter = cls(timeout=42)
    super_send = mocker.patch("requests.adapters.HTTPAdapter.send", return_value="resp")

    result = adapter.send(mocker.sentinel.request)

    assert result == "resp"
    assert super_send.call_count == 1
    _args, kwargs = super_send.call_args
    assert kwargs.get("timeout") == 42


def test_timeout_http_adapter_send_preserves_explicit_timeout(mocker):
    cls = utils_pkg._get_timeout_http_adapter_class()
    adapter = cls(timeout=42)
    super_send = mocker.patch("requests.adapters.HTTPAdapter.send", return_value="resp")

    adapter.send(mocker.sentinel.request, timeout=5)

    _args, kwargs = super_send.call_args
    assert kwargs.get("timeout") == 5


# ---------------------------------------------------------------------------
# NetBoxSessionManager.get_session
# ---------------------------------------------------------------------------


def test_get_session_creates_and_mounts_adapter(mocker):
    session = mocker.MagicMock()
    session.verify = mocker.sentinel.unset
    requests_mod = mocker.patch("requests.Session", return_value=session)
    mocker.patch("urllib3.disable_warnings")

    result = utils_pkg.NetBoxSessionManager.get_session()

    assert result is session
    requests_mod.assert_called_once_with()
    mounted = {call.args[0] for call in session.mount.call_args_list}
    assert mounted == {"http://", "https://"}
    # default ignore_ssl_errors=False -> ``verify`` must not be touched
    assert session.verify is mocker.sentinel.unset


def test_get_session_ignore_ssl_errors_disables_warnings(mocker):
    session = mocker.MagicMock()
    mocker.patch("requests.Session", return_value=session)
    disable_warnings = mocker.patch("urllib3.disable_warnings")

    utils_pkg.NetBoxSessionManager.get_session(ignore_ssl_errors=True)

    disable_warnings.assert_called_once_with()
    assert session.verify is False


def test_get_session_ignore_ssl_errors_false_does_not_disable(mocker):
    session = mocker.MagicMock()
    session.verify = mocker.sentinel.unset
    mocker.patch("requests.Session", return_value=session)
    disable_warnings = mocker.patch("urllib3.disable_warnings")

    utils_pkg.NetBoxSessionManager.get_session(ignore_ssl_errors=False)

    disable_warnings.assert_not_called()
    assert session.verify is mocker.sentinel.unset


def test_get_session_caches_session(mocker):
    session = mocker.MagicMock()
    requests_mod = mocker.patch("requests.Session", return_value=session)
    mocker.patch("urllib3.disable_warnings")

    first = utils_pkg.NetBoxSessionManager.get_session()
    second = utils_pkg.NetBoxSessionManager.get_session()

    assert first is second
    assert requests_mod.call_count == 1


def test_get_session_propagates_custom_timeout(mocker):
    session = mocker.MagicMock()
    mocker.patch("requests.Session", return_value=session)
    mocker.patch("urllib3.disable_warnings")
    adapter = mocker.MagicMock()
    adapter_cls = mocker.MagicMock(return_value=adapter)
    mocker.patch(
        "osism.utils._get_timeout_http_adapter_class", return_value=adapter_cls
    )

    utils_pkg.NetBoxSessionManager.get_session(timeout=30)

    adapter_cls.assert_called_once_with(
        timeout=30, pool_connections=10, pool_maxsize=10
    )


# ---------------------------------------------------------------------------
# NetBoxSessionManager.close_session
# ---------------------------------------------------------------------------


def test_close_session_closes_and_clears(mocker):
    session = mocker.MagicMock()
    utils_pkg.NetBoxSessionManager._session = session

    utils_pkg.NetBoxSessionManager.close_session()

    session.close.assert_called_once_with()
    assert utils_pkg.NetBoxSessionManager._session is None


def test_close_session_noop_when_unset():
    # Idempotent: a second call (or a call without prior init) must not raise.
    utils_pkg.NetBoxSessionManager.close_session()
    utils_pkg.NetBoxSessionManager.close_session()
    assert utils_pkg.NetBoxSessionManager._session is None


# ---------------------------------------------------------------------------
# cleanup_netbox_sessions
# ---------------------------------------------------------------------------


def test_cleanup_netbox_sessions_delegates(mocker):
    close = mocker.patch.object(utils_pkg.NetBoxSessionManager, "close_session")

    utils_pkg.cleanup_netbox_sessions()

    close.assert_called_once_with()


# ---------------------------------------------------------------------------
# get_netbox_connection
# ---------------------------------------------------------------------------


def test_get_netbox_connection_happy_path(mocker):
    nb = mocker.MagicMock(name="nb")
    pynetbox = mocker.patch("pynetbox.api", return_value=nb)
    session = mocker.MagicMock(name="session")
    get_session = mocker.patch.object(
        utils_pkg.NetBoxSessionManager, "get_session", return_value=session
    )
    register = mocker.patch("atexit.register")

    result = utils_pkg.get_netbox_connection("https://nb", "tok")

    assert result is nb
    pynetbox.assert_called_once_with("https://nb", token="tok")
    assert nb.http_session is session
    register.assert_called_once_with(utils_pkg.cleanup_netbox_sessions)
    get_session.assert_called_once_with(ignore_ssl_errors=False, timeout=20)
    assert utils_pkg._cleanup_registered is True


def test_get_netbox_connection_missing_url(mocker):
    pynetbox = mocker.patch("pynetbox.api")
    register = mocker.patch("atexit.register")

    result = utils_pkg.get_netbox_connection("", "tok")

    assert result is None
    pynetbox.assert_not_called()
    register.assert_not_called()


def test_get_netbox_connection_missing_token(mocker):
    pynetbox = mocker.patch("pynetbox.api")
    register = mocker.patch("atexit.register")

    result = utils_pkg.get_netbox_connection("https://nb", "")

    assert result is None
    pynetbox.assert_not_called()
    register.assert_not_called()


def test_get_netbox_connection_falsy_pynetbox_result(mocker):
    """If ``pynetbox.api`` returns a falsy value, ``atexit.register`` is not
    invoked but the caller still receives that falsy value back."""
    pynetbox = mocker.patch("pynetbox.api", return_value=None)
    register = mocker.patch("atexit.register")
    get_session = mocker.patch.object(utils_pkg.NetBoxSessionManager, "get_session")

    result = utils_pkg.get_netbox_connection("https://nb", "tok")

    assert result is None
    pynetbox.assert_called_once_with("https://nb", token="tok")
    register.assert_not_called()
    get_session.assert_not_called()
    assert utils_pkg._cleanup_registered is False


def test_get_netbox_connection_propagates_ssl_and_timeout(mocker):
    nb = mocker.MagicMock()
    mocker.patch("pynetbox.api", return_value=nb)
    get_session = mocker.patch.object(
        utils_pkg.NetBoxSessionManager,
        "get_session",
        return_value=mocker.MagicMock(),
    )
    mocker.patch("atexit.register")

    utils_pkg.get_netbox_connection(
        "https://nb", "tok", ignore_ssl_errors=True, timeout=99
    )

    get_session.assert_called_once_with(ignore_ssl_errors=True, timeout=99)


def test_get_netbox_connection_atexit_registered_only_once(mocker):
    nb = mocker.MagicMock()
    mocker.patch("pynetbox.api", return_value=nb)
    mocker.patch.object(
        utils_pkg.NetBoxSessionManager,
        "get_session",
        return_value=mocker.MagicMock(),
    )
    register = mocker.patch("atexit.register")

    utils_pkg.get_netbox_connection("https://nb", "tok")
    utils_pkg.get_netbox_connection("https://nb", "tok")
    utils_pkg.get_netbox_connection("https://nb", "tok")

    assert register.call_count == 1


# ---------------------------------------------------------------------------
# get_openstack_connection
# ---------------------------------------------------------------------------


def test_get_openstack_connection_success(mocker):
    conn = mocker.MagicMock()
    connect = mocker.patch("openstack.connect", return_value=conn)

    result = utils_pkg.get_openstack_connection()

    assert result is conn
    connect.assert_called_once_with()


def test_get_openstack_connection_missing_required_options(mocker):
    from keystoneauth1.exceptions.auth_plugins import MissingRequiredOptions

    mocker.patch(
        "openstack.connect",
        side_effect=MissingRequiredOptions(options=[]),
    )

    with pytest.raises(RuntimeError, match="missing required authentication options"):
        utils_pkg.get_openstack_connection()


def test_get_openstack_connection_other_exception_propagates(mocker):
    mocker.patch("openstack.connect", side_effect=ValueError("nope"))

    with pytest.raises(ValueError, match="nope"):
        utils_pkg.get_openstack_connection()


# ---------------------------------------------------------------------------
# __getattr__
# ---------------------------------------------------------------------------


def test_getattr_redis_initializes_and_caches(mocker):
    sentinel = mocker.MagicMock(name="redis-instance")
    init_redis = mocker.patch("osism.utils._init_redis", return_value=sentinel)

    first = utils_pkg.redis
    second = utils_pkg.redis

    assert first is sentinel
    assert second is sentinel
    # ``globals()["redis"]`` is set on first access; second access reads the
    # cached attribute without invoking ``__getattr__`` again.
    assert init_redis.call_count == 1
    assert utils_pkg.__dict__.get("redis") is sentinel


def test_getattr_nb_initializes_and_caches(mocker):
    sentinel = mocker.MagicMock(name="nb-instance")
    init_nb = mocker.patch("osism.utils._init_nb", return_value=sentinel)

    first = utils_pkg.nb
    second = utils_pkg.nb

    assert first is sentinel
    assert second is sentinel
    assert init_nb.call_count == 1
    assert utils_pkg.__dict__.get("nb") is sentinel


def test_getattr_secondary_nb_list_initializes_and_caches(mocker):
    sentinel = [mocker.MagicMock()]
    init_list = mocker.patch(
        "osism.utils._init_secondary_nb_list", return_value=sentinel
    )

    first = utils_pkg.secondary_nb_list
    second = utils_pkg.secondary_nb_list

    assert first is sentinel
    assert second is sentinel
    assert init_list.call_count == 1
    assert utils_pkg.__dict__.get("secondary_nb_list") is sentinel


def test_getattr_unknown_name_raises_attribute_error():
    with pytest.raises(AttributeError, match="has no attribute 'foo'"):
        utils_pkg.__getattr__("foo")
