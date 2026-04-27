# SPDX-License-Identifier: Apache-2.0

import threading
from unittest.mock import MagicMock

import pytest

from osism.tasks.conductor.sonic.cache import (
    InterfaceCache,
    clear_interface_cache,
    get_cached_device_interfaces,
    get_interface_cache,
    get_interface_cache_stats,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_nb(mocker):
    """Replace ``osism.utils.nb`` with a MagicMock for the duration of a test.

    ``utils.nb`` is normally lazy-initialised through ``__getattr__`` and would
    try to reach a real NetBox instance. ``create=True`` is needed because the
    attribute may not yet exist on the module when the test starts.
    """
    nb = MagicMock()
    mocker.patch("osism.utils.nb", new=nb, create=True)
    return nb


@pytest.fixture(autouse=True)
def _reset_thread_local():
    """Reset the module-level thread-local cache between tests.

    Tests that call ``get_cached_device_interfaces`` etc. populate the
    thread-local storage; without an explicit reset, later tests would
    inherit that state and become order-dependent. We use the public
    ``clear_interface_cache`` helper so we don't bind to the module's
    internal storage layout.
    """
    yield
    clear_interface_cache()


# ---------------------------------------------------------------------------
# InterfaceCache.__init__
# ---------------------------------------------------------------------------


def test_init_starts_with_empty_cache():
    cache = InterfaceCache()

    assert cache.get_cache_stats() == {"cached_devices": 0, "total_interfaces": 0}


# ---------------------------------------------------------------------------
# InterfaceCache.get_device_interfaces
# ---------------------------------------------------------------------------


def test_get_device_interfaces_cache_miss_queries_netbox(mock_nb):
    iface_a, iface_b = MagicMock(), MagicMock()
    mock_nb.dcim.interfaces.filter.return_value = iter([iface_a, iface_b])

    cache = InterfaceCache()
    result = cache.get_device_interfaces(42)

    assert result == [iface_a, iface_b]
    assert mock_nb.dcim.interfaces.filter.call_count == 1


def test_get_device_interfaces_uses_keyword_argument(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = []

    cache = InterfaceCache()
    cache.get_device_interfaces(7)

    mock_nb.dcim.interfaces.filter.assert_called_once_with(device_id=7)
    # Belt-and-suspenders: no positional arguments at all.
    args, _ = mock_nb.dcim.interfaces.filter.call_args
    assert args == ()


def test_get_device_interfaces_consumes_generator_into_list(mock_nb):
    """The implementation wraps the filter() result in ``list(...)``.

    Returning a one-shot iterator simulates pynetbox's lazy result objects and
    pins the behaviour that the cache stores a concrete list, not the
    iterator itself (which would be exhausted after the first iteration).
    """
    mock_nb.dcim.interfaces.filter.return_value = iter([MagicMock(), MagicMock()])

    cache = InterfaceCache()
    first = cache.get_device_interfaces(1)

    assert isinstance(first, list)
    # Re-iterating the cached list must still yield the items.
    assert len(list(first)) == 2


def test_get_device_interfaces_cache_hit_does_not_query_netbox(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = [MagicMock()]

    cache = InterfaceCache()
    first = cache.get_device_interfaces(1)
    second = cache.get_device_interfaces(1)

    assert mock_nb.dcim.interfaces.filter.call_count == 1
    # Same list object — identity, not just equality.
    assert first is second


def test_get_device_interfaces_different_device_ids_coexist(mock_nb):
    iface_1, iface_2a, iface_2b = MagicMock(), MagicMock(), MagicMock()
    mock_nb.dcim.interfaces.filter.side_effect = [
        iter([iface_1]),
        iter([iface_2a, iface_2b]),
    ]

    cache = InterfaceCache()
    result_1 = cache.get_device_interfaces(1)
    result_2 = cache.get_device_interfaces(2)

    assert result_1 == [iface_1]
    assert result_2 == [iface_2a, iface_2b]
    assert mock_nb.dcim.interfaces.filter.call_count == 2
    assert cache.get_cache_stats() == {"cached_devices": 2, "total_interfaces": 3}


def test_get_device_interfaces_returns_empty_list_on_exception(mock_nb):
    mock_nb.dcim.interfaces.filter.side_effect = RuntimeError("netbox down")

    cache = InterfaceCache()
    result = cache.get_device_interfaces(99)

    assert result == []
    # The failure produced a cached entry with no interfaces.
    assert cache.get_cache_stats() == {"cached_devices": 1, "total_interfaces": 0}


def test_get_device_interfaces_caches_empty_list_after_exception(mock_nb):
    mock_nb.dcim.interfaces.filter.side_effect = RuntimeError("netbox down")

    cache = InterfaceCache()
    cache.get_device_interfaces(99)
    cache.get_device_interfaces(99)

    # The empty list is cached, so no retry happens.
    assert mock_nb.dcim.interfaces.filter.call_count == 1


def test_get_device_interfaces_recovers_for_other_devices_after_exception(mock_nb):
    """An exception for one device must not poison the cache for others."""
    iface = MagicMock()
    mock_nb.dcim.interfaces.filter.side_effect = [
        RuntimeError("transient"),
        iter([iface]),
    ]

    cache = InterfaceCache()
    failed = cache.get_device_interfaces(1)
    ok = cache.get_device_interfaces(2)

    assert failed == []
    assert ok == [iface]


def test_get_device_interfaces_handles_empty_filter_result(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = []

    cache = InterfaceCache()
    result = cache.get_device_interfaces(1)

    assert result == []
    # Subsequent call must hit cache, not re-query.
    cache.get_device_interfaces(1)
    assert mock_nb.dcim.interfaces.filter.call_count == 1


# ---------------------------------------------------------------------------
# InterfaceCache.clear
# ---------------------------------------------------------------------------


def test_clear_empties_cache(mock_nb):
    mock_nb.dcim.interfaces.filter.side_effect = [
        iter([MagicMock()]),
        iter([MagicMock(), MagicMock()]),
    ]

    cache = InterfaceCache()
    cache.get_device_interfaces(1)
    cache.get_device_interfaces(2)
    assert cache.get_cache_stats() == {"cached_devices": 2, "total_interfaces": 3}

    cache.clear()

    assert cache.get_cache_stats() == {"cached_devices": 0, "total_interfaces": 0}


def test_clear_forces_subsequent_call_to_requery_netbox(mock_nb):
    mock_nb.dcim.interfaces.filter.side_effect = [
        iter([MagicMock()]),
        iter([MagicMock()]),
    ]

    cache = InterfaceCache()
    cache.get_device_interfaces(1)
    cache.clear()
    cache.get_device_interfaces(1)

    assert mock_nb.dcim.interfaces.filter.call_count == 2


def test_clear_on_empty_cache_is_noop():
    cache = InterfaceCache()

    cache.clear()  # Must not raise.

    assert cache.get_cache_stats() == {"cached_devices": 0, "total_interfaces": 0}


# ---------------------------------------------------------------------------
# InterfaceCache.get_cache_stats
# ---------------------------------------------------------------------------


def test_get_cache_stats_empty_cache():
    cache = InterfaceCache()

    assert cache.get_cache_stats() == {"cached_devices": 0, "total_interfaces": 0}


def test_get_cache_stats_sums_interfaces_across_devices(mock_nb):
    mock_nb.dcim.interfaces.filter.side_effect = [
        iter([MagicMock(), MagicMock(), MagicMock()]),
        iter([MagicMock()] * 5),
    ]

    cache = InterfaceCache()
    cache.get_device_interfaces(1)
    cache.get_device_interfaces(2)

    assert cache.get_cache_stats() == {"cached_devices": 2, "total_interfaces": 8}


def test_get_cache_stats_counts_empty_entries(mock_nb):
    """Devices that returned no interfaces still count toward ``cached_devices``."""
    mock_nb.dcim.interfaces.filter.return_value = []

    cache = InterfaceCache()
    cache.get_device_interfaces(1)
    cache.get_device_interfaces(2)

    assert cache.get_cache_stats() == {"cached_devices": 2, "total_interfaces": 0}


# ---------------------------------------------------------------------------
# Lock semantics
# ---------------------------------------------------------------------------


def test_concurrent_get_device_interfaces_is_safe(mock_nb):
    """Smoke test: two threads asking for the same device must not raise.

    This is not a concurrency proof — it just exercises the lock path and
    asserts both threads observe the same cached list.
    """
    iface = MagicMock()
    mock_nb.dcim.interfaces.filter.return_value = [iface]

    cache = InterfaceCache()
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(cache.get_device_interfaces(1))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2
    assert results[0] == [iface]
    assert results[1] == [iface]
    # The list is cached, so even under contention only one filter call should
    # have happened.
    assert mock_nb.dcim.interfaces.filter.call_count == 1


# ---------------------------------------------------------------------------
# get_interface_cache (module-level, thread-local)
# ---------------------------------------------------------------------------


def test_get_interface_cache_returns_same_instance_within_thread():
    first = get_interface_cache()
    second = get_interface_cache()

    assert first is second
    assert isinstance(first, InterfaceCache)


def test_get_interface_cache_returns_different_instance_per_thread():
    main_cache = get_interface_cache()
    other_cache_holder: list[InterfaceCache] = []

    def worker():
        other_cache_holder.append(get_interface_cache())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert len(other_cache_holder) == 1
    assert other_cache_holder[0] is not main_cache
    assert isinstance(other_cache_holder[0], InterfaceCache)


# ---------------------------------------------------------------------------
# get_cached_device_interfaces
# ---------------------------------------------------------------------------


def test_get_cached_device_interfaces_delegates_to_thread_local_cache(mocker):
    fake_cache = MagicMock(spec=InterfaceCache)
    fake_cache.get_device_interfaces.return_value = ["iface"]
    mocker.patch(
        "osism.tasks.conductor.sonic.cache.get_interface_cache",
        return_value=fake_cache,
    )

    result = get_cached_device_interfaces(123)

    fake_cache.get_device_interfaces.assert_called_once_with(123)
    assert result == ["iface"]


def test_get_cached_device_interfaces_populates_thread_local_cache(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = [MagicMock()]

    get_cached_device_interfaces(1)

    assert get_interface_cache_stats() == {
        "cached_devices": 1,
        "total_interfaces": 1,
    }


# ---------------------------------------------------------------------------
# clear_interface_cache
# ---------------------------------------------------------------------------


def test_clear_interface_cache_is_noop_when_no_cache_exists():
    """Calling clear before any cache has been created must not raise.

    A fresh thread is used to guarantee the thread-local has no
    ``interface_cache`` attribute set.
    """
    errors: list[BaseException] = []

    def worker():
        try:
            clear_interface_cache()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert errors == []


def test_clear_interface_cache_empties_populated_cache(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = [MagicMock(), MagicMock()]

    get_cached_device_interfaces(1)
    assert get_interface_cache_stats() == {
        "cached_devices": 1,
        "total_interfaces": 2,
    }

    clear_interface_cache()

    assert get_interface_cache_stats() == {
        "cached_devices": 0,
        "total_interfaces": 0,
    }


# ---------------------------------------------------------------------------
# get_interface_cache_stats
# ---------------------------------------------------------------------------


def test_get_interface_cache_stats_returns_none_without_cache():
    """A fresh thread has no thread-local cache; stats must be ``None``."""
    captured: list = []

    def worker():
        captured.append(get_interface_cache_stats())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert captured == [None]


def test_get_interface_cache_stats_returns_dict_after_use(mock_nb):
    mock_nb.dcim.interfaces.filter.return_value = [MagicMock()]

    get_cached_device_interfaces(42)

    assert get_interface_cache_stats() == {
        "cached_devices": 1,
        "total_interfaces": 1,
    }
