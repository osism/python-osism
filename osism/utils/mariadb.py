# SPDX-License-Identifier: Apache-2.0

"""Shared MariaDB connection helper used by the status and loadbalancer commands.

Both need a superuser connection to the cluster's MariaDB, and both have to cope
with the two load-balancer topologies OSISM ships. On a ProxySQL cluster (the
2025.2 default) the proxied superuser is the sharded name ``<user>_shard_0``; on a
plain HAProxy cluster it is ``<user>``.

Which topology is in use is decided by ``enable_proxysql``, a release-gated
``osism/defaults`` group_vars value. It is absent from the operator's
``environments/kolla/configuration.yml`` and is only correct after Ansible templates
it in the host's variable context, so it cannot be read from a raw config file (doing
so silently returned the wrong user -- the ProxySQL DB-user bug). Rather than resolve
it, connect empirically: try the ProxySQL user first and fall back to the plain user
on an authentication failure. The connection itself tells us which topology we are on,
with no dependency on defaults resolution.
"""

from loguru import logger
import pymysql

# MariaDB ER_ACCESS_DENIED_ERROR. ProxySQL also returns this code when the supplied
# user is unknown to it, so it covers "wrong user for this topology" on both paths.
_ACCESS_DENIED = 1045


def connect(host, user, password, **connect_kwargs):
    """Connect to MariaDB, transparently handling the ProxySQL sharded superuser.

    Tries ``<user>_shard_0`` (ProxySQL) first, then ``<user>`` (plain HAProxy),
    falling back only on an access-denied error so genuine connectivity failures
    (host unreachable, timeout, ...) surface immediately without a pointless retry.
    ``connect_kwargs`` are passed through to :func:`pymysql.connect` unchanged (e.g.
    ``port``, ``database``, ``cursorclass``, ``connect_timeout``).

    Raises the last :class:`pymysql.Error` if neither user connects.
    """
    last_exc = None
    for candidate in (f"{user}_shard_0", user):
        try:
            connection = pymysql.connect(
                host=host, user=candidate, password=password, **connect_kwargs
            )
            logger.debug(f"Connected to MariaDB at {host} as {candidate}")
            return connection
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == _ACCESS_DENIED:
                logger.debug(
                    f"MariaDB user {candidate} denied at {host}; trying next candidate"
                )
                last_exc = exc
                continue
            raise
    raise last_exc
