# SPDX-License-Identifier: Apache-2.0

import os

from loguru import logger


def get_inventory_path(base_path: str, prefer_minified: bool = True) -> str:
    """Return the best available inventory path.

    Resolution order:
    1. If prefer_minified and hosts-minified.yml exists, use it.
    2. If a ``fast/`` directory exists next to hosts.yml, use it.
    3. Fall back to the original base_path.

    The minified inventory (hosts-minified.yml) contains only hosts and their
    group memberships. It is faster to parse than the full inventory and can
    be used for operations that only need to resolve hosts and groups.

    The fast inventory directory is structurally equivalent to hosts.yml but
    optimised for faster parsing by Ansible.

    Args:
        base_path: The original inventory path
                   (e.g., "/ansible/inventory/hosts.yml")
        prefer_minified: If True, try to use hosts-minified.yml first

    Returns:
        Path to the inventory file or directory to use
    """
    directory = os.path.dirname(base_path)

    if prefer_minified:
        minified_path = os.path.join(directory, "hosts-minified.yml")
        if os.path.exists(minified_path):
            logger.debug(f"Using minified inventory: {minified_path}")
            return minified_path

    fast_path = os.path.join(directory, "fast")
    if os.path.isdir(fast_path):
        logger.debug(f"Using fast inventory: {fast_path}")
        return fast_path

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
