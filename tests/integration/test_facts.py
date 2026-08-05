# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``osism.utils.check_ansible_facts()``.

The function scans Redis for ``ansible_facts*`` keys with a cursor-based
``SCAN`` loop and reads ``ansible_date_time.epoch`` from each JSON value to
decide whether the cached facts are stale, reporting the outcome through
loguru. The unit tests cover the same scenarios against a ``MagicMock``
client; running them against a live Redis exercises what the mocks stand in
for: the cursor loop, keys and values arriving as ``bytes``, and JSON that
round-tripped through a Redis server. The suite is skipped automatically when
Redis is not reachable (see ``conftest.py``).
"""

import json
import time
import uuid

import pytest

from osism import utils

pytestmark = pytest.mark.integration

# Passed explicitly to every call: the ``settings.FACTS_MAX_AGE`` default is 12
# hours, which would tie the stale case to the environment.
MAX_AGE = 300


@pytest.fixture
def seed_facts():
    """Seed ``ansible_facts<host>`` keys and remove them after the test."""
    keys = []

    def _seed(host, value):
        key = f"ansible_facts{host}"
        utils.redis.set(key, value)
        keys.append(key)

    yield _seed

    for key in keys:
        utils.redis.delete(key)


def _host():
    """Return a hostname unique to one test.

    The ``itest-`` prefix keeps it clear of ``LOCAL_FACT_HOSTS``, whose facts
    ``check_ansible_facts()`` skips outright.
    """
    return f"itest-{uuid.uuid4()}"


def _facts(epoch):
    """Return a facts blob carrying ``epoch``.

    Ansible stores the epoch as a string, and ``check_ansible_facts()`` casts
    it with ``float()``, so the string form is what the test seeds.
    """
    return json.dumps({"ansible_date_time": {"epoch": str(int(epoch))}})


def _messages(records, level, needle):
    """Return the captured messages at ``level`` that contain ``needle``."""
    return [
        record["message"]
        for record in records
        if record["level"] == level and needle in record["message"]
    ]


def test_no_facts_warns_about_empty_cache(loguru_logs):
    """An empty facts cache is reported as such.

    ``check_ansible_facts()`` scans the whole database, so a Redis holding
    real facts cannot produce this case. Skip there rather than deleting data
    that does not belong to the suite; the CI container starts empty.
    """
    leftover = sorted(
        key.decode() for key in utils.redis.scan_iter(match="ansible_facts*")
    )
    if leftover:
        pytest.skip(f"Redis already holds ansible_facts keys: {leftover}")

    utils.check_ansible_facts(max_age=MAX_AGE)

    assert _messages(loguru_logs, "WARNING", "No Ansible facts found in Redis cache")


def test_fresh_facts_produce_no_warning(seed_facts, loguru_logs):
    """A host whose facts are current is not reported."""
    host = _host()
    seed_facts(host, _facts(time.time()))

    utils.check_ansible_facts(max_age=MAX_AGE)

    assert not _messages(loguru_logs, "WARNING", host)


def test_stale_facts_report_the_stale_host_only(seed_facts, loguru_logs):
    """Facts older than ``max_age`` are reported, fresh ones are not."""
    stale_host = _host()
    fresh_host = _host()
    seed_facts(stale_host, _facts(time.time() - 9999))
    seed_facts(fresh_host, _facts(time.time()))

    utils.check_ansible_facts(max_age=MAX_AGE)

    stale_messages = _messages(
        loguru_logs, "WARNING", f"Host '{stale_host}': facts are"
    )
    assert stale_messages
    assert all("seconds old" in message for message in stale_messages)
    assert _messages(loguru_logs, "WARNING", "Run 'osism sync facts' to update facts.")
    assert not _messages(loguru_logs, "WARNING", fresh_host)


def test_stale_facts_are_reported_across_scan_batches(seed_facts, loguru_logs):
    """Every stale host is reported when ``SCAN`` needs more than one call.

    ``check_ansible_facts()`` collects the keys of every batch before reading
    them. The other tests seed too few keys to leave the first batch, so
    replacing the loop with a single ``SCAN`` call keeps them green; only
    enough hosts to force a second call covers it.
    """
    hosts = [_host() for _ in range(200)]
    for host in hosts:
        seed_facts(host, _facts(time.time() - 9999))

    # COUNT is a hint, not a limit, so the number of keys one call covers is
    # not guaranteed. Fail loudly if a single batch swallows the keyspace
    # instead of passing without having exercised pagination.
    cursor, _ = utils.redis.scan(0, match="ansible_facts*", count=100)
    assert cursor != 0

    utils.check_ansible_facts(max_age=MAX_AGE)

    # One line per host proves the batches accumulated; exactly one line
    # proves they were not counted twice, which matters because SCAN may
    # return a key more than once and the collected keys are not deduplicated.
    for host in hosts:
        assert len(_messages(loguru_logs, "WARNING", f"Host '{host}': facts are")) == 1


def test_facts_without_epoch_are_skipped(seed_facts, loguru_logs):
    """Facts lacking ``ansible_date_time.epoch`` are skipped, not reported."""
    host = _host()
    seed_facts(host, json.dumps({"ansible_hostname": "node-1"}))

    utils.check_ansible_facts(max_age=MAX_AGE)

    assert _messages(
        loguru_logs, "DEBUG", f"Host '{host}': facts missing ansible_date_time.epoch"
    )
    assert not _messages(loguru_logs, "WARNING", host)


def test_malformed_json_is_skipped(seed_facts, loguru_logs):
    """A value that is not JSON is skipped without failing the check."""
    host = _host()
    seed_facts(host, "{ not valid json")

    utils.check_ansible_facts(max_age=MAX_AGE)

    skipped = _messages(loguru_logs, "DEBUG", "Skipping malformed ansible_facts entry")
    assert any(host in message for message in skipped)
    assert not _messages(loguru_logs, "WARNING", host)


def test_empty_value_is_skipped(seed_facts, loguru_logs):
    """An empty value is skipped silently and the scan continues.

    Absence of output says nothing about what happened to the remaining keys,
    so stale hosts are seeded alongside: turning the ``continue`` into a
    ``return`` or ``break`` drops their report and fails the test.
    """
    host = _host()
    seed_facts(host, "")
    stale_hosts = [_host() for _ in range(5)]
    for stale_host in stale_hosts:
        seed_facts(stale_host, _facts(time.time() - 9999))

    utils.check_ansible_facts(max_age=MAX_AGE)

    assert not _messages(loguru_logs, "WARNING", host)
    assert not _messages(loguru_logs, "DEBUG", host)
    for stale_host in stale_hosts:
        assert _messages(loguru_logs, "WARNING", f"Host '{stale_host}': facts are")
