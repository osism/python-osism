# SPDX-License-Identifier: Apache-2.0

"""Centralized connection detection functions for SONiC configuration.

This module provides unified helper functions for detecting connected devices
using the NetBox connected_endpoints API, replacing legacy cable-based detection.
"""

from loguru import logger
from typing import Optional, Set, Tuple, List, Any, DefaultDict
from collections import defaultdict

from osism import utils
from .interface import (
    convert_netbox_interface_to_sonic,
)
from .cache import get_cached_device_interfaces

# Global cache for VIP addresses to avoid repeated queries
_vip_addresses_cache = None


def get_connected_device_via_interface(
    interface: Any, source_device_id: int
) -> Optional[Any]:
    """Get the connected device for a given interface using connected_endpoints API.

    Args:
        interface: NetBox interface object
        source_device_id: ID of the source device to exclude from results

    Returns:
        Connected NetBox device object or None if not found/reachable
    """
    # Skip management-only interfaces
    if hasattr(interface, "mgmt_only") and interface.mgmt_only:
        return None

    # Check if interface has connected_endpoints
    if not (
        hasattr(interface, "connected_endpoints") and interface.connected_endpoints
    ):
        return None

    # Ensure connected_endpoints_reachable is True
    if not getattr(interface, "connected_endpoints_reachable", False):
        return None

    try:
        # Process each connected endpoint
        for endpoint in interface.connected_endpoints:
            # Get the connected device from the endpoint
            if hasattr(endpoint, "device") and endpoint.device.id != source_device_id:
                return endpoint.device
    except Exception as e:
        logger.debug(
            f"Error processing connected_endpoints for interface {interface.name}: {e}"
        )

    return None


def get_connected_interfaces(
    device: Any, portchannel_info: Optional[dict] = None
) -> Tuple[Set[str], Set[str]]:
    """Get list of interface names that are connected to other devices.

    Uses the modern connected_endpoints API as the primary method for detecting
    connections, with reachability checks.

    Args:
        device: NetBox device object
        portchannel_info: Optional port channel info dict from detect_port_channels

    Returns:
        tuple: (set of connected interfaces, set of connected port channels)
    """
    connected_interfaces = set()
    connected_portchannels = set()

    try:
        # Get all interfaces for the device (using cache)
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Skip management-only interfaces
            if hasattr(interface, "mgmt_only") and interface.mgmt_only:
                continue

            # Check if interface is connected using connected_endpoints API
            connected_device = get_connected_device_via_interface(interface, device.id)

            if connected_device:
                # Convert NetBox interface name to SONiC format
                sonic_interface_name = convert_netbox_interface_to_sonic(
                    interface, device
                )
                connected_interfaces.add(sonic_interface_name)

                # If this interface is part of a port channel, mark the port channel as connected
                if (
                    portchannel_info
                    and sonic_interface_name in portchannel_info["member_mapping"]
                ):
                    pc_name = portchannel_info["member_mapping"][sonic_interface_name]
                    connected_portchannels.add(pc_name)

    except Exception as e:
        logger.warning(
            f"Could not get interface connections for device {device.name}: {e}"
        )

    return connected_interfaces, connected_portchannels


def get_connected_device_for_sonic_interface(
    device: Any, sonic_interface_name: str
) -> Optional[Any]:
    """Get the connected device for a given SONiC interface name.

    For Port Channels, uses the member ports to detect connected devices.

    Args:
        device: NetBox device object
        sonic_interface_name: SONiC interface name (e.g., "Ethernet0" or "PortChannel1")

    Returns:
        NetBox device object or None if not found
    """
    try:
        # Check if this is a Port Channel
        if sonic_interface_name.startswith("PortChannel"):
            return get_connected_device_for_port_channel(device, sonic_interface_name)

        # Handle regular interfaces
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Convert NetBox interface name to SONiC format
            sonic_name = convert_netbox_interface_to_sonic(interface, device)

            if sonic_name == sonic_interface_name:
                return get_connected_device_via_interface(interface, device.id)

    except Exception as e:
        logger.debug(
            f"Could not find connected device for interface {sonic_interface_name}: {e}"
        )

    return None


def get_connected_device_for_port_channel(
    device: Any, portchannel_name: str
) -> Optional[Any]:
    """Get the connected device for a Port Channel by checking its member ports.

    Args:
        device: NetBox device object
        portchannel_name: Port Channel name (e.g., "PortChannel1")

    Returns:
        NetBox device object or None if not found
    """
    try:
        # Import here to avoid circular imports
        from .interface import detect_port_channels

        # Get port channel information to find member ports
        portchannel_info = detect_port_channels(device)

        if portchannel_name not in portchannel_info["portchannels"]:
            logger.debug(
                f"Port Channel {portchannel_name} not found on device {device.name}"
            )
            return None

        member_ports = portchannel_info["portchannels"][portchannel_name]["members"]

        if not member_ports:
            logger.debug(f"No member ports found for Port Channel {portchannel_name}")
            return None

        # Check each member port to find a connected device
        # All member ports in a Port Channel should connect to the same remote device
        interfaces = get_cached_device_interfaces(device.id)

        for member_port in member_ports:
            # Find the NetBox interface corresponding to this member port
            for interface in interfaces:
                sonic_name = convert_netbox_interface_to_sonic(interface, device)
                if sonic_name == member_port:
                    connected_device = get_connected_device_via_interface(
                        interface, device.id
                    )
                    if connected_device:
                        logger.debug(
                            f"Found connected device {connected_device.name} for Port Channel {portchannel_name} "
                            f"via member port {member_port}"
                        )
                        return connected_device
                    break

        logger.debug(
            f"No connected device found for any member ports of {portchannel_name}"
        )
        return None

    except Exception as e:
        logger.debug(
            f"Could not find connected device for Port Channel {portchannel_name}: {e}"
        )
        return None


def find_interconnected_devices(
    devices: List[Any], target_roles: List[str] = ["spine", "superspine"]
) -> List[List[Any]]:
    """Find groups of interconnected devices with specific roles.

    Uses connected_endpoints API to build a graph of device connections.

    Args:
        devices: List of NetBox device objects
        target_roles: List of device roles to consider

    Returns:
        List of groups, where each group is a list of interconnected devices of the same role
    """
    from collections import deque

    # Filter devices by target roles
    target_devices = {}
    for device in devices:
        if hasattr(device, "role") and device.role and device.role.slug in target_roles:
            target_devices[device.id] = device

    if not target_devices:
        return []

    # Build connection graph for each role separately
    role_graphs: DefaultDict[str, DefaultDict[int, Set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for device in target_devices.values():
        device_role = device.role.slug

        try:
            # Get all interfaces for this device
            interfaces = get_cached_device_interfaces(device.id)

            for interface in interfaces:
                # Get connected device using our helper
                connected_device = get_connected_device_via_interface(
                    interface, device.id
                )

                if (
                    connected_device
                    and connected_device.id in target_devices
                    and connected_device.role.slug == device_role
                ):
                    # Add bidirectional connection to the graph
                    role_graphs[device_role][device.id].add(connected_device.id)
                    role_graphs[device_role][connected_device.id].add(device.id)

        except Exception as e:
            logger.warning(f"Error processing device {device.name} for grouping: {e}")

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
                    group.append(target_devices[current_id])

                    for neighbor_id in graph[current_id]:
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            queue.append(neighbor_id)

                if len(group) > 1:  # Only include groups with multiple devices
                    all_groups.append(group)

    return all_groups


def load_vip_addresses_cache():
    """Load all VIP addresses into cache at start of sync.

    This avoids repeated queries for VIP addresses during connected interface
    IP address lookups.
    """
    global _vip_addresses_cache

    logger.debug("Loading VIP addresses cache...")

    try:
        _vip_addresses_cache = list(utils.nb.ipam.ip_addresses.filter(role="vip"))
        logger.info(f"Loaded {len(_vip_addresses_cache)} VIP addresses into cache")
    except Exception as e:
        logger.warning(f"Could not load VIP addresses cache: {e}")
        _vip_addresses_cache = []


def clear_vip_addresses_cache():
    """Clear the VIP addresses cache."""
    global _vip_addresses_cache
    _vip_addresses_cache = None
    logger.debug("Cleared VIP addresses cache")


def get_device_bgp_neighbors_via_loopback(
    device: Any,
    portchannel_info: dict,
    connected_interfaces: Set[str],
    port_config: dict,
) -> List[dict]:
    """Get BGP neighbors for a device based on Loopback0 addresses of connected devices.

    Args:
        device: NetBox device object
        portchannel_info: Port channel information
        connected_interfaces: Set of connected interface names
        port_config: Port configuration dict

    Returns:
        List of BGP neighbor dictionaries with IP and device info
    """
    bgp_neighbors = []

    try:
        # Get all interfaces for the device
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Skip management-only interfaces
            if hasattr(interface, "mgmt_only") and interface.mgmt_only:
                continue

            # Get connected device
            connected_device = get_connected_device_via_interface(interface, device.id)
            if not connected_device:
                continue

            # Convert to SONiC interface name to check if it's in our PORT config
            sonic_interface_name = convert_netbox_interface_to_sonic(interface, device)

            # Only process if this interface is in PORT configuration and connected
            if (
                sonic_interface_name in port_config
                and sonic_interface_name in connected_interfaces
                and sonic_interface_name not in portchannel_info["member_mapping"]
            ):
                # Check if connected device has the required tag
                has_osism_tag = False
                if connected_device.tags:
                    has_osism_tag = any(
                        tag.slug == "managed-by-osism" for tag in connected_device.tags
                    )

                if has_osism_tag:
                    # Get Loopback0 IP addresses from the connected device
                    try:
                        # Get all interfaces for connected device (using cache)
                        all_connected_interfaces = get_cached_device_interfaces(
                            connected_device.id
                        )
                        loopback_interfaces: List[Any] = [
                            iface
                            for iface in all_connected_interfaces
                            if iface.name == "Loopback0"
                        ]

                        for loopback_iface in loopback_interfaces:
                            # Get IP addresses assigned to Loopback0
                            ip_addresses = utils.nb.ipam.ip_addresses.filter(
                                assigned_object_id=loopback_iface.id,
                            )

                            for ip_addr in ip_addresses:
                                if ip_addr.address:
                                    # Extract just the IP address without prefix
                                    ip_only = ip_addr.address.split("/")[0]
                                    bgp_neighbors.append(
                                        {
                                            "ip": ip_only,
                                            "device": connected_device,
                                            "interface": sonic_interface_name,
                                        }
                                    )

                    except Exception as e:
                        logger.debug(
                            f"Could not get Loopback0 for device {connected_device.name}: {e}"
                        )
                else:
                    logger.debug(
                        f"Skipping BGP neighbor for device {connected_device.name}: "
                        f"missing 'managed-by-osism' tag"
                    )

    except Exception as e:
        logger.warning(f"Could not process BGP neighbors for device {device.name}: {e}")

    return bgp_neighbors


def get_connected_interface_ipv4_address(device, sonic_port_name, netbox):
    """
    Get the IPv4 address(es) of the connected endpoint interface for a given SONiC port.
    Checks for direct IP addresses first, then for FHRP VIP addresses.

    Args:
        device: The SONiC device
        sonic_port_name: The SONiC port name
        netbox: The NetBox API client

    Returns:
        - For direct IP: The IPv4 address string of the connected interface
        - For FHRP VIP: The first VIP address found (if multiple VIPs exist, logs all but returns first)
        - None if no addresses found
    """
    try:
        interface = netbox.dcim.interfaces.get(
            device_id=device.id, name=sonic_port_name
        )
        if not interface:
            return None

        # Check if interface has connected_endpoints using the modern API
        if not (
            hasattr(interface, "connected_endpoints") and interface.connected_endpoints
        ):
            return None

        # Ensure connected_endpoints_reachable is True
        if not getattr(interface, "connected_endpoints_reachable", False):
            return None

        # Process each connected endpoint to find the first valid interface
        connected_interface = None
        for endpoint in interface.connected_endpoints:
            if hasattr(endpoint, "id"):
                connected_interface = endpoint
                break

        if not connected_interface:
            return None

        # First, try to get direct IPv4 addresses assigned to the connected interface
        ip_addresses = netbox.ipam.ip_addresses.filter(
            assigned_object_id=connected_interface.id,
        )

        for ip_address in ip_addresses:
            # Check if it's an IPv4 address
            if "/" in str(ip_address.address):
                address = str(ip_address.address).split("/")[0]
                if "." in address:  # IPv4 address
                    logger.debug(
                        f"Found direct IPv4 address {address} on connected interface "
                        f"{connected_interface.name} for port {sonic_port_name}"
                    )
                    return address

        # If no direct IP found, check for FHRP group membership and VIP addresses
        logger.debug(
            f"No direct IPv4 found on {connected_interface.name}, checking for FHRP VIP addresses"
        )

        # Get FHRP group assignments for the connected interface
        fhrp_assignments = netbox.ipam.fhrp_group_assignments.filter(
            interface_type="dcim.interface", interface_id=connected_interface.id
        )

        # Use cached VIP addresses if available, otherwise query
        if _vip_addresses_cache is not None:
            all_vip_addresses = _vip_addresses_cache
            logger.debug("Using cached VIP addresses")
        else:
            try:
                all_vip_addresses = list(netbox.ipam.ip_addresses.filter(role="vip"))
                logger.debug("VIP cache not loaded, querying VIP addresses")
            except Exception as vip_e:
                logger.debug(f"Could not query VIP addresses: {vip_e}")
                all_vip_addresses = []

        # Collect all VIP IPv4 addresses from all FHRP groups this interface belongs to
        vip_addresses_found = []

        for assignment in fhrp_assignments:
            if not assignment.group:
                continue

            # Find VIP addresses assigned to this specific FHRP group
            for vip in all_vip_addresses:
                # Check if this VIP is assigned to the current FHRP group
                if (
                    hasattr(vip, "assigned_object_type")
                    and vip.assigned_object_type == "ipam.fhrpgroup"
                    and hasattr(vip, "assigned_object_id")
                    and vip.assigned_object_id == assignment.group.id
                ):
                    # Check if it's an IPv4 address
                    if "/" in str(vip.address):
                        address = str(vip.address).split("/")[0]
                        if "." in address:  # IPv4 address
                            vip_addresses_found.append(address)
                            logger.debug(
                                f"Found FHRP VIP address {address} for connected interface "
                                f"{connected_interface.name} (FHRP group: {assignment.group.name or assignment.group.id}) "
                                f"for port {sonic_port_name}"
                            )

        # Return the first VIP address found (for BGP neighbor compatibility)
        if vip_addresses_found:
            logger.debug(
                f"Found {len(vip_addresses_found)} VIP addresses for port {sonic_port_name}: {vip_addresses_found}"
            )
            logger.debug(f"Returning first VIP address: {vip_addresses_found[0]}")
            return vip_addresses_found[0]

        logger.debug(
            f"No IPv4 address (direct or FHRP VIP) found on connected interface "
            f"{connected_interface.name} for port {sonic_port_name}"
        )
        return None

    except Exception as e:
        logger.warning(
            f"Could not get connected interface IPv4 for port {sonic_port_name}: {e}"
        )
        return None
