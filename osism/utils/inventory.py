# SPDX-License-Identifier: Apache-2.0

import os

from loguru import logger


def get_inventory_path(base_path: str, prefer_minified: bool = True) -> str:
    """Return the minified inventory path if available, otherwise the original.

    The minified inventory (hosts-minified.yml) contains only hosts and their
    group memberships. It is faster to parse than the full inventory and can
    be used for operations that only need to resolve hosts and groups.

    Args:
        base_path: The original inventory path
                   (e.g., "/ansible/inventory/hosts.yml")
        prefer_minified: If True, try to use hosts-minified.yml first

    Returns:
        Path to the inventory file to use
    """
    if prefer_minified:
        directory = os.path.dirname(base_path)
        minified_path = os.path.join(directory, "hosts-minified.yml")
        if os.path.exists(minified_path):
            logger.debug(f"Using minified inventory: {minified_path}")
            return minified_path
    return base_path


def get_hosts_from_inventory(data: dict) -> list:
    """Extract host names from ansible-inventory --list JSON output.

    The minified inventory does not populate _meta.hostvars (since hosts
    have no variables), so we also collect hosts from group listings.
    """
    hosts = set(data.get("_meta", {}).get("hostvars", {}).keys())
    for key, value in data.items():
        if key == "_meta":
            continue
        if isinstance(value, dict) and "hosts" in value:
            hosts.update(value["hosts"])
    return sorted(hosts)
