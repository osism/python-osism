# SPDX-License-Identifier: Apache-2.0

"""Connection detection utilities for SONiC configuration."""

from loguru import logger
from typing import Optional, List, Tuple

from osism import utils


def get_connected_device(interface) -> Optional[object]:
    """Get the device connected to an interface using connected_endpoints API.

    Args:
        interface: NetBox interface object

    Returns:
        Connected NetBox device object or None if not found/reachable
    """
    try:
        # Skip management-only interfaces
        if hasattr(interface, "mgmt_only") and interface.mgmt_only:
            return None

        # Check if interface has connected_endpoints (preferred method)
        if hasattr(interface, "connected_endpoints") and interface.connected_endpoints:
            # Ensure connected_endpoints_reachable is True
            if not getattr(interface, "connected_endpoints_reachable", False):
                logger.debug(
                    f"Interface {interface.name} has connected_endpoints but not reachable"
                )
                return None

            # Process each connected endpoint
            for endpoint in interface.connected_endpoints:
                if hasattr(endpoint, "device"):
                    return endpoint.device

    except Exception as e:
        logger.debug(
            f"Error getting connected device for interface {interface.name}: {e}"
        )

    return None


def get_connected_device_and_interface(interface) -> Optional[Tuple[object, object]]:
    """Get both the connected device and interface using connected_endpoints API.

    Args:
        interface: NetBox interface object

    Returns:
        Tuple of (connected_device, connected_interface) or None if not found
    """
    try:
        # Skip management-only interfaces
        if hasattr(interface, "mgmt_only") and interface.mgmt_only:
            return None

        # Check if interface has connected_endpoints
        if hasattr(interface, "connected_endpoints") and interface.connected_endpoints:
            # Ensure connected_endpoints_reachable is True
            if not getattr(interface, "connected_endpoints_reachable", False):
                return None

            # Process each connected endpoint
            for endpoint in interface.connected_endpoints:
                if hasattr(endpoint, "device"):
                    return (endpoint.device, endpoint)

    except Exception as e:
        logger.debug(
            f"Error getting connected device and interface for {interface.name}: {e}"
        )

    return None


def get_device_connections(
    device, skip_mgmt=True
) -> List[Tuple[object, object, object]]:
    """Get all connections for a device.

    Args:
        device: NetBox device object
        skip_mgmt: Skip management-only interfaces (default: True)

    Returns:
        List of tuples: (local_interface, connected_device, connected_interface)
    """
    connections = []

    try:
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)

        for interface in interfaces:
            # Skip management interfaces if requested
            if skip_mgmt and hasattr(interface, "mgmt_only") and interface.mgmt_only:
                continue

            result = get_connected_device_and_interface(interface)
            if result:
                connected_device, connected_interface = result
                connections.append((interface, connected_device, connected_interface))

    except Exception as e:
        logger.warning(f"Error getting connections for device {device.name}: {e}")

    return connections


def get_interconnected_devices(devices, target_roles=None) -> List[List[object]]:
    """Find groups of interconnected devices, optionally filtered by role.

    This is a generalized version of find_interconnected_spine_groups that works
    for any device role.

    Args:
        devices: List of NetBox device objects
        target_roles: List of device role slugs to filter by (optional)

    Returns:
        List of groups, where each group is a list of interconnected devices
    """
    from collections import defaultdict, deque

    # Filter devices by target roles if specified
    filtered_devices = {}
    for device in devices:
        if target_roles:
            if (
                hasattr(device, "role")
                and device.role
                and device.role.slug in target_roles
            ):
                filtered_devices[device.id] = device
        else:
            filtered_devices[device.id] = device

    if not filtered_devices:
        return []

    # Build connection graph
    graph = defaultdict(set)

    for device in filtered_devices.values():
        connections = get_device_connections(device)

        for local_if, connected_device, connected_if in connections:
            # Only add if connected device is in our filtered set
            if connected_device.id in filtered_devices:
                graph[device.id].add(connected_device.id)
                graph[connected_device.id].add(device.id)

    # Find connected components using BFS
    groups = []
    visited = set()

    for device_id in graph:
        if device_id not in visited:
            # BFS to find all connected devices
            group = []
            queue = deque([device_id])
            visited.add(device_id)

            while queue:
                current_id = queue.popleft()
                group.append(filtered_devices[current_id])

                for neighbor_id in graph[current_id]:
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append(neighbor_id)

            if len(group) > 1:  # Only include groups with multiple devices
                groups.append(group)

    return groups


def is_interface_connected(interface) -> bool:
    """Check if an interface is connected to another device.

    Args:
        interface: NetBox interface object

    Returns:
        True if interface is connected, False otherwise
    """
    # Skip management-only interfaces
    if hasattr(interface, "mgmt_only") and interface.mgmt_only:
        return False

    # Check connected_endpoints
    if hasattr(interface, "connected_endpoints") and interface.connected_endpoints:
        # Must be reachable
        return getattr(interface, "connected_endpoints_reachable", False)

    # Alternative: check is_connected property
    if hasattr(interface, "is_connected"):
        return interface.is_connected

    return False
