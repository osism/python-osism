# SPDX-License-Identifier: Apache-2.0

"""Ansible's fact cache in Redis, in both of its key schemas.

The Ansible runtimes OSISM ships straddle ansible-core 2.19, which changed how
cache plugins store entries. Before 2.19 the redis cache plugin stores a host's
facts as plain JSON under ``ansible_facts<host>``. From 2.19 on, ansible-core
puts a schema prefix inside the plugin's key prefix and wraps the value, so the
same host's facts land under ``ansible_factss1_<host>`` as
``{"__payload__": "<JSON>"}``. Values set with ``set_fact: cacheable`` keep
their data tags in that payload, as
``{"value": ..., "tags": [...], "__ansible_type": "..."}``.

Which key is current depends on which runtime gathered last, and both coexist
on a running cluster. Readers here look at both and take the newer entry, by
``ansible_date_time.epoch``. Tags are stripped rather than decoded with
ansible-core's private decoder, so the result is plain JSON data and does not
depend on ansible-core internals.

The redis cache plugin also records every key it has written as a member of
the sorted set ``ansible_cache_keys`` (``<host>`` and ``s1_<host>``), so
deleting a host's facts removes those members too.
"""

import json

KEY_PREFIX = "ansible_facts"
SCHEMA_PREFIX = "s1_"
CACHE_KEYS = "ansible_cache_keys"

_PAYLOAD = "__payload__"
_TYPE = "__ansible_type"


def keys_for(host):
    """Return both cache keys for *host*, the schema-prefixed one first."""
    return [f"{KEY_PREFIX}{SCHEMA_PREFIX}{host}", f"{KEY_PREFIX}{host}"]


def host_from_key(key):
    """Return the host a cache key belongs to, or None for a foreign key."""
    if isinstance(key, bytes):
        key = key.decode()
    if not key.startswith(KEY_PREFIX):
        return None
    name = key[len(KEY_PREFIX) :]
    if name.startswith(SCHEMA_PREFIX):
        name = name[len(SCHEMA_PREFIX) :]
    return name


def _untag(value):
    if isinstance(value, dict):
        if _TYPE in value:
            if "value" in value:
                return _untag(value["value"])
            return {k: _untag(v) for k, v in value.items() if k != _TYPE}
        return {k: _untag(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_untag(v) for v in value]
    return value


def decode(data):
    """Parse one cache entry, in either schema, into a plain dict.

    Raises ValueError (json.JSONDecodeError included) for an entry that is not
    JSON or not a mapping of facts.
    """
    value = json.loads(data)
    if isinstance(value, dict) and _PAYLOAD in value:
        value = _untag(json.loads(value[_PAYLOAD]))
    if not isinstance(value, dict):
        raise ValueError("fact cache entry is not a mapping")
    return value


def _epoch(facts):
    try:
        return float(facts.get("ansible_date_time", {}).get("epoch"))
    except (AttributeError, TypeError, ValueError):
        return float("-inf")


def newest(entries):
    """Return the entry with the newest ``ansible_date_time.epoch``.

    On a tie, or when no entry carries a timestamp, the first one wins.
    """
    return max(entries, key=_epoch)


def get_host_facts(redis, host):
    """Return the newest cached facts for *host*, or None if there are none.

    Raises ValueError if a cached entry cannot be parsed.
    """
    entries = []
    for key in keys_for(host):
        data = redis.get(key)
        if data:
            entries.append(decode(data))
    if not entries:
        return None
    return newest(entries)


def scan_host_keys(redis):
    """Return ``{host: [key, ...]}`` for every fact-cache key in Redis."""
    hosts = {}
    cursor = 0
    while True:
        cursor, batch = redis.scan(cursor, match=f"{KEY_PREFIX}*", count=100)
        for key in batch:
            host = host_from_key(key)
            if host is not None:
                hosts.setdefault(host, []).append(key)
        if cursor == 0:
            break
    return hosts


def delete_host_facts(redis, hosts):
    """Delete both cache entries of each host in *hosts*.

    Also removes the hosts' members from the ``ansible_cache_keys`` set.
    Returns the number of hosts that had at least one entry.
    """
    removed = sum(1 for host in hosts if redis.exists(*keys_for(host)))
    keys = [key for host in hosts for key in keys_for(host)]
    members = [m for host in hosts for m in (f"{SCHEMA_PREFIX}{host}", host)]
    if keys:
        redis.delete(*keys)
        redis.zrem(CACHE_KEYS, *members)
    return removed
