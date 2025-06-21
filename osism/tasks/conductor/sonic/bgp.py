# SPDX-License-Identifier: Apache-2.0

"""BGP and AS calculation functions for SONiC configuration."""

from loguru import logger

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


# Deprecated: Use connections.find_interconnected_devices instead
# This function is kept for backward compatibility but delegates to the new module
def find_interconnected_spine_groups(devices, target_roles=["spine", "superspine"]):
    """Find groups of interconnected spine/superspine switches.

    Args:
        devices: List of NetBox device objects
        target_roles: List of device roles to consider (default: ["spine", "superspine"])

    Returns:
        List of groups, where each group is a list of interconnected devices of the same role
    """
    # Import here to avoid circular imports
    from .connections import find_interconnected_devices

    return find_interconnected_devices(devices, target_roles)


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
