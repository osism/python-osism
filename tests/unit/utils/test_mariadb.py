# SPDX-License-Identifier: Apache-2.0

from unittest import mock

import pymysql
import pytest

from osism.utils import mariadb


def _access_denied(user):
    return pymysql.err.OperationalError(1045, f"Access denied for user '{user}'")


def test_connect_prefers_proxysql_shard_user():
    """A ProxySQL cluster: the sharded user connects on the first try."""
    sentinel = object()
    with mock.patch("pymysql.connect", return_value=sentinel) as connect:
        result = mariadb.connect("vip", "root", "pw", port=3306)

    assert result is sentinel
    connect.assert_called_once_with(
        host="vip", user="root_shard_0", password="pw", port=3306
    )


def test_connect_passes_through_extra_kwargs():
    """The call sites' connection kwargs reach pymysql.connect unchanged."""
    sentinel = object()
    cursor_cls = object()
    with mock.patch("pymysql.connect", return_value=sentinel) as connect:
        result = mariadb.connect(
            "vip",
            "octavia",
            "pw",
            port=3306,
            database="octavia",
            cursorclass=cursor_cls,
            connect_timeout=10,
        )

    assert result is sentinel
    connect.assert_called_once_with(
        host="vip",
        user="octavia_shard_0",
        password="pw",
        port=3306,
        database="octavia",
        cursorclass=cursor_cls,
        connect_timeout=10,
    )


def test_connect_falls_back_to_plain_user_on_access_denied():
    """A plain HAProxy cluster: the shard user is denied, the plain user connects."""
    sentinel = object()
    with mock.patch(
        "pymysql.connect", side_effect=[_access_denied("root_shard_0"), sentinel]
    ) as connect:
        result = mariadb.connect("vip", "root", "pw")

    assert result is sentinel
    assert [c.kwargs["user"] for c in connect.call_args_list] == [
        "root_shard_0",
        "root",
    ]


def test_connect_does_not_retry_on_non_auth_errors():
    """A genuine connectivity failure surfaces immediately, without a second attempt."""
    unreachable = pymysql.err.OperationalError(2003, "Can't connect to MySQL server")
    with mock.patch("pymysql.connect", side_effect=unreachable) as connect:
        with pytest.raises(pymysql.err.OperationalError) as excinfo:
            mariadb.connect("vip", "root", "pw")

    assert excinfo.value.args[0] == 2003
    connect.assert_called_once()


def test_connect_raises_last_error_when_both_users_denied():
    """Neither user authenticates: the last access-denied error propagates."""
    errors = [_access_denied("root_shard_0"), _access_denied("root")]
    with mock.patch("pymysql.connect", side_effect=errors):
        with pytest.raises(pymysql.err.OperationalError) as excinfo:
            mariadb.connect("vip", "root", "pw")

    assert "root'" in excinfo.value.args[1]
