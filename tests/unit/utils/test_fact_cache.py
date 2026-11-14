# SPDX-License-Identifier: Apache-2.0

"""Tests for ``osism.utils.fact_cache``.

The entries mirror what the redis cache plugin writes: ansible-core before
2.19 stores plain JSON under ``ansible_facts<host>``; 2.19 and later store
``{"__payload__": "<JSON>"}`` under ``ansible_factss1_<host>``, with data tags
on values set by ``set_fact: cacheable``. Both kinds are recorded in the
``ansible_cache_keys`` sorted set.
"""

import json

import fakeredis
import pytest

from osism.utils import fact_cache


def _legacy(facts):
    return json.dumps(facts).encode()


def _schema1(facts):
    return json.dumps({"__payload__": json.dumps(facts)}).encode()


def _facts(epoch, **extra):
    return {
        "ansible_date_time": {"epoch": str(epoch)},
        "ansible_hostname": "node1",
        **extra,
    }


# A value as ansible-core 2.20 stores a tagged string from `set_fact: cacheable`.
_TAGGED = {
    "value": "bar",
    "tags": [
        {"path": "/p.yml", "line_num": 4, "col_num": 14, "__ansible_type": "Origin"}
    ],
    "__ansible_type": "_AnsibleTaggedStr",
}


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


def _store(redis, key, data, member):
    redis.set(key, data)
    redis.zadd(fact_cache.CACHE_KEYS, {member: 1.0})


# --- keys ---


def test_keys_for_lists_the_schema_prefixed_key_first():
    assert fact_cache.keys_for("node1") == [
        "ansible_factss1_node1",
        "ansible_factsnode1",
    ]


@pytest.mark.parametrize(
    "key, host",
    [
        (b"ansible_factsnode1", "node1"),
        (b"ansible_factss1_node1", "node1"),
        ("ansible_factsnode1", "node1"),
        (b"ansible_cache_keys", None),
    ],
)
def test_host_from_key(key, host):
    assert fact_cache.host_from_key(key) == host


# --- decode ---


def test_decode_legacy_entry():
    assert fact_cache.decode(_legacy(_facts(1))) == _facts(1)


def test_decode_schema1_entry_unwraps_the_payload():
    assert fact_cache.decode(_schema1(_facts(1))) == _facts(1)


def test_decode_strips_data_tags():
    facts = _facts(1, foo=_TAGGED, nested={"items": [_TAGGED, 2]})

    decoded = fact_cache.decode(_schema1(facts))

    assert decoded["foo"] == "bar"
    assert decoded["nested"] == {"items": ["bar", 2]}


def test_decode_drops_the_type_marker_of_a_tagged_mapping_without_value():
    facts = _facts(1, when={"iso": "2026-11-14", "__ansible_type": "datetime"})

    assert fact_cache.decode(_schema1(facts))["when"] == {"iso": "2026-11-14"}


@pytest.mark.parametrize(
    "data",
    [b"{not json", b"[1, 2]", json.dumps({"__payload__": "{not json"}).encode()],
)
def test_decode_rejects_what_is_not_a_fact_mapping(data):
    with pytest.raises(ValueError):
        fact_cache.decode(data)


# --- get_host_facts ---


def test_get_host_facts_none_when_nothing_is_cached(redis):
    assert fact_cache.get_host_facts(redis, "node1") is None


def test_get_host_facts_reads_a_legacy_entry_alone(redis):
    redis.set("ansible_factsnode1", _legacy(_facts(100)))

    assert fact_cache.get_host_facts(redis, "node1") == _facts(100)


def test_get_host_facts_reads_a_schema1_entry_alone(redis):
    redis.set("ansible_factss1_node1", _schema1(_facts(100)))

    assert fact_cache.get_host_facts(redis, "node1") == _facts(100)


def test_get_host_facts_prefers_the_newer_schema1_entry(redis):
    redis.set("ansible_factsnode1", _legacy(_facts(100, packages={})))
    redis.set("ansible_factss1_node1", _schema1(_facts(200)))

    assert fact_cache.get_host_facts(redis, "node1") == _facts(200)


def test_get_host_facts_prefers_the_newer_legacy_entry(redis):
    # ceph-ansible keeps writing the legacy key after osism-ansible moved on.
    redis.set("ansible_factsnode1", _legacy(_facts(300)))
    redis.set("ansible_factss1_node1", _schema1(_facts(200)))

    assert fact_cache.get_host_facts(redis, "node1") == _facts(300)


def test_get_host_facts_falls_back_to_the_entry_with_a_timestamp(redis):
    redis.set("ansible_factsnode1", _legacy({"ansible_hostname": "node1"}))
    redis.set("ansible_factss1_node1", _schema1(_facts(200)))

    assert fact_cache.get_host_facts(redis, "node1") == _facts(200)


def test_get_host_facts_raises_on_a_corrupt_entry(redis):
    redis.set("ansible_factsnode1", b"{not json")

    with pytest.raises(ValueError):
        fact_cache.get_host_facts(redis, "node1")


# --- scan_host_keys ---


def test_scan_host_keys_groups_both_schemas_by_host(redis):
    redis.set("ansible_factsnode1", _legacy(_facts(1)))
    redis.set("ansible_factss1_node1", _schema1(_facts(2)))
    redis.set("ansible_factss1_node2", _schema1(_facts(3)))
    redis.zadd(fact_cache.CACHE_KEYS, {"node1": 1.0})
    redis.set("unrelated", b"x")

    hosts = fact_cache.scan_host_keys(redis)

    assert sorted(hosts) == ["node1", "node2"]
    assert sorted(hosts["node1"]) == [b"ansible_factsnode1", b"ansible_factss1_node1"]
    assert hosts["node2"] == [b"ansible_factss1_node2"]


# --- delete_host_facts ---


def test_delete_host_facts_removes_both_entries_and_set_members(redis):
    _store(redis, "ansible_factsnode1", _legacy(_facts(1)), "node1")
    _store(redis, "ansible_factss1_node1", _schema1(_facts(2)), "s1_node1")
    _store(redis, "ansible_factss1_node2", _schema1(_facts(3)), "s1_node2")
    _store(redis, "ansible_factsnode3", _legacy(_facts(4)), "node3")

    removed = fact_cache.delete_host_facts(redis, ["node1", "node2", "absent"])

    assert removed == 2
    assert redis.keys("ansible_facts*") == [b"ansible_factsnode3"]
    assert redis.zrange(fact_cache.CACHE_KEYS, 0, -1) == [b"node3"]


def test_delete_host_facts_with_no_hosts_touches_nothing(redis):
    _store(redis, "ansible_factsnode1", _legacy(_facts(1)), "node1")

    assert fact_cache.delete_host_facts(redis, []) == 0
    assert redis.exists("ansible_factsnode1")
    assert redis.zrange(fact_cache.CACHE_KEYS, 0, -1) == [b"node1"]
