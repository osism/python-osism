# SPDX-License-Identifier: Apache-2.0

"""BGP and AS calculation functions for SONiC configuration."""

from collections import defaultdict, deque
from loguru import logger

from osism import utils
from .constants import DEFAULT_LOCAL_AS_PREFIX


def calculate_local_asn_from_ipv4(
    ipv4_address: str, prefix: int = DEFAULT_LOCAL_AS_PREFIX
) -> int:
    """Calculate AS number from IPv4 address.

    Args:
        ipv4_address: IPv4 address in format "192.168.45.123/32" or "192.168.45.123"
        prefix: Four-digit prefix for AS number (default: 4200)

    Returns:
        AS number calculated as prefix + 3rd octet (padded) + 4th octet (padded)
        Example: 192.168.45.123 with prefix 4200 -> 4200045123

    Raises:
        ValueError: If IP address format is invalid
    """
    try:
        # Remove CIDR notation if present
        ip_only = ipv4_address.split("/")[0]
        octets = ip_only.split(".")

        if len(octets) != 4:
            raise ValueError(f"Invalid IPv4 address format: {ipv4_address}")

        # AS = prefix + third octet (3 digits) + fourth octet (3 digits)
        # Example: 192.168.45.123 -> 4200 + 045 + 123 = 4200045123
        third_octet = int(octets[2])
        fourth_octet = int(octets[3])

        if not (0 <= third_octet <= 255 and 0 <= fourth_octet <= 255):
            raise ValueError(f"Invalid octet values in: {ipv4_address}")

        return int(f"{prefix}{third_octet:03d}{fourth_octet:03d}")
    except (IndexError, ValueError) as e:
        raise ValueError(f"Failed to calculate AS from {ipv4_address}: {str(e)}")


def find_interconnected_spine_groups(devices, target_roles=["spine", "superspine"]):
    """Find groups of interconnected spine/superspine switches.

    Args:
        devices: List of NetBox device objects
        target_roles: List of device roles to consider (default: ["spine", "superspine"])

    Returns:
        List of groups, where each group is a list of interconnected devices of the same role
    """
    # Filter devices by target roles
    spine_devices = {}
    for device in devices:
        if hasattr(device, "role") and device.role and device.role.slug in target_roles:
            spine_devices[device.id] = device

    if not spine_devices:
        return []

    # Build connection graph for each role separately
    role_graphs = defaultdict(lambda: defaultdict(set))

    for device in spine_devices.values():
        device_role = device.role.slug

        try:
            # Get all interfaces for this device
            interfaces = list(utils.nb.dcim.interfaces.filter(device_id=device.id))

            for interface in interfaces:
                # Check if interface has connected_endpoints
                if (
                    hasattr(interface, "connected_endpoints")
                    and interface.connected_endpoints
                ):
                    # Ensure connected_endpoints_reachable is True
                    if not getattr(interface, "connected_endpoints_reachable", False):
                        continue

                    try:
                        # Process each connected endpoint
                        for endpoint in interface.connected_endpoints:
                            # Get the connected device from the endpoint
                            if hasattr(endpoint, "device"):
                                connected_device = endpoint.device

                                # Check if connected device is also a spine/superspine device
                                if (
                                    connected_device.id in spine_devices
                                    and connected_device.id != device.id
                                    and connected_device.role.slug == device_role
                                ):
                                    # Add connection to the graph
                                    role_graphs[device_role][device.id].add(
                                        connected_device.id
                                    )
                                    role_graphs[device_role][connected_device.id].add(
                                        device.id
                                    )

                    except Exception as e:
                        logger.debug(
                            f"Error processing connected_endpoints for interface {interface.name} on {device.name}: {e}"
                        )

        except Exception as e:
            logger.warning(
                f"Error processing device {device.name} for spine grouping: {e}"
            )

    # Find connected components for each role using BFS
    all_groups = []

    for role, graph in role_graphs.items():
        visited = set()

        for device_id in graph:
            if device_id not in visited:
                # BFS to find all connected devices
                group = []
                queue = deque([device_id])
                visited.add(device_id)

                while queue:
                    current_id = queue.popleft()
                    group.append(spine_devices[current_id])

                    for neighbor_id in graph[current_id]:
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            queue.append(neighbor_id)

                if len(group) > 1:  # Only include groups with multiple devices
                    all_groups.append(group)

    return all_groups


def calculate_minimum_as_for_group(device_group, prefix=DEFAULT_LOCAL_AS_PREFIX):
    """Calculate the minimum AS number for a group of interconnected devices.

    Args:
        device_group: List of interconnected devices
        prefix: AS prefix (default: DEFAULT_LOCAL_AS_PREFIX)

    Returns:
        int: Minimum AS number for the group, or None if no valid AS can be calculated
    """
    as_numbers = []

    for device in device_group:
        if device.primary_ip4:
            try:
                as_number = calculate_local_asn_from_ipv4(
                    str(device.primary_ip4), prefix
                )
                as_numbers.append(as_number)
            except ValueError as e:
                logger.debug(f"Could not calculate AS for device {device.name}: {e}")

    return min(as_numbers) if as_numbers else None
