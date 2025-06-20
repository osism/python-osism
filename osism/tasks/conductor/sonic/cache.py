# SPDX-License-Identifier: Apache-2.0

"""Interface caching for SONiC configuration generation."""

import threading
from typing import Dict, List, Optional
from loguru import logger

from osism import utils


class InterfaceCache:
    """Thread-local cache for device interfaces during sync_sonic task."""

    def __init__(self):
        self._cache: Dict[int, List] = {}
        self._lock = threading.Lock()

    def get_device_interfaces(self, device_id: int) -> List:
        """Get interfaces for a device, using cache if available.

        Args:
            device_id: NetBox device ID

        Returns:
            List of interface objects
        """
        with self._lock:
            if device_id not in self._cache:
                logger.debug(f"Fetching interfaces for device {device_id}")
                try:
                    interfaces = list(
                        utils.nb.dcim.interfaces.filter(device_id=device_id)
                    )
                    self._cache[device_id] = interfaces
                    logger.debug(
                        f"Cached {len(interfaces)} interfaces for device {device_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch interfaces for device {device_id}: {e}"
                    )
                    self._cache[device_id] = []
            else:
                logger.debug(f"Using cached interfaces for device {device_id}")

            return self._cache[device_id]

    def clear(self):
        """Clear the cache."""
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared interface cache ({cache_size} devices)")

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_interfaces = sum(
                len(interfaces) for interfaces in self._cache.values()
            )
            return {
                "cached_devices": len(self._cache),
                "total_interfaces": total_interfaces,
            }


# Thread-local storage for the interface cache
_thread_local = threading.local()


def get_interface_cache() -> InterfaceCache:
    """Get the current thread's interface cache.

    Returns:
        InterfaceCache instance for current thread
    """
    if not hasattr(_thread_local, "interface_cache"):
        _thread_local.interface_cache = InterfaceCache()
    return _thread_local.interface_cache


def get_cached_device_interfaces(device_id: int) -> List:
    """Get interfaces for a device using the thread-local cache.

    Args:
        device_id: NetBox device ID

    Returns:
        List of interface objects
    """
    cache = get_interface_cache()
    return cache.get_device_interfaces(device_id)


def clear_interface_cache():
    """Clear the current thread's interface cache."""
    if hasattr(_thread_local, "interface_cache"):
        _thread_local.interface_cache.clear()


def get_interface_cache_stats() -> Optional[Dict[str, int]]:
    """Get cache statistics for the current thread.

    Returns:
        Dictionary with cache statistics or None if no cache exists
    """
    if hasattr(_thread_local, "interface_cache"):
        return _thread_local.interface_cache.get_cache_stats()
    return None
