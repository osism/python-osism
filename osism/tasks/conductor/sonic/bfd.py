# SPDX-License-Identifier: Apache-2.0

"""BFD configuration functions for SONiC switches."""

from loguru import logger
from typing import Set, Dict, Any

from .connections import get_connected_device_for_sonic_interface

# Node device roles that should trigger BFD configuration
NETBOX_NODE_ROLES = [
    "compute",
    "storage",
    "resource",
    "control",
    "manager",
    "network",
    "metalbox",
    "dpu",
    "loadbalancer",
    "router",
    "firewall",
]

# Switch device roles that should trigger BFD configuration
NETBOX_SWITCH_ROLES = [
    "accessleaf",
    "borderleaf",
    "computeleaf",
    "dataleaf",
    "leaf",
    "serviceleaf",
    "spine",
    "storageleaf",
    "superspine",
    "switch",
    "transferleaf",
]

# Combined list of all device roles that should have BFD enabled
BFD_ENABLED_ROLES = NETBOX_NODE_ROLES + NETBOX_SWITCH_ROLES


def should_interface_have_bfd(
    port_name: str,
    connected_interfaces: Set[str],
    connected_portchannels: Set[str],
    portchannel_info: Dict[str, Any],
    device: Any,
    interface_ips: Dict[str, str] = None,
    netbox_interfaces: Dict[str, Any] = None,
    transfer_ips: Dict[str, str] = None,
    bgp_neighbors: Set[str] = None,
) -> bool:
    """Determine if an interface should have BFD configuration.

    BFD should be enabled on switch ports that meet ALL these criteria:
    1. Connected to devices with roles from NETBOX_NODE_ROLES or NETBOX_SWITCH_ROLES
    2. Have IP addresses from transfer networks (role "transfer") OR are in IPv6-only mode
    3. Are already present in BGP configuration
    4. Are not port channel members (but port channels themselves can have BFD)

    Args:
        port_name: SONiC interface name (e.g., "Ethernet0", "PortChannel1")
        connected_interfaces: Set of connected interface names
        connected_portchannels: Set of connected port channel names
        portchannel_info: Port channel membership information
        device: NetBox device object
        interface_ips: Dict of direct IPv4 addresses on interfaces
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
        transfer_ips: Dict of IPv4 addresses from transfer role prefixes
        bgp_neighbors: Set of interfaces that already have BGP neighbors configured

    Returns:
        bool: True if interface should have BFD configuration
    """
    # Skip if interface is a member of a port channel (BFD will be on the port channel itself)
    if portchannel_info and port_name in portchannel_info.get("member_mapping", {}):
        logger.debug(f"Skipping BFD for {port_name} - it's a port channel member")
        return False

    # Check if interface is connected (either regular interface or port channel)
    is_connected = (
        port_name in connected_interfaces or port_name in connected_portchannels
    )

    if not is_connected:
        logger.debug(f"Skipping BFD for {port_name} - not connected")
        return False

    # Check if interface is already in BGP configuration (required)
    if bgp_neighbors and port_name not in bgp_neighbors:
        logger.debug(f"Skipping BFD for {port_name} - not in BGP configuration")
        return False

    # Check if connected device has appropriate role
    connected_device = get_connected_device_for_sonic_interface(device, port_name)
    if not connected_device:
        logger.debug(f"Skipping BFD for {port_name} - no connected device found")
        return False

    if not (connected_device.role and connected_device.role.slug in BFD_ENABLED_ROLES):
        logger.debug(
            f"Skipping BFD for {port_name} - connected device {connected_device.name} "
            f"has role '{connected_device.role.slug if connected_device.role else None}' "
            f"which is not in BFD-enabled roles"
        )
        return False

    # Check if interface meets IP address criteria
    has_transfer_ipv4 = _has_transfer_role_ipv4(
        port_name, transfer_ips, netbox_interfaces
    )
    has_direct_ipv4 = _has_direct_ipv4_address(
        port_name, interface_ips, netbox_interfaces
    )

    # Include interfaces with transfer role IPv4 or IPv6-only mode (no direct IPv4)
    if has_transfer_ipv4 or not has_direct_ipv4:
        logger.debug(
            f"Including BFD for {port_name} connected to {connected_device.name} "
            f"(transfer_ipv4={has_transfer_ipv4}, direct_ipv4={has_direct_ipv4})"
        )
        return True

    logger.debug(
        f"Skipping BFD for {port_name} - has direct IPv4 but not from transfer role"
    )
    return False


def _has_direct_ipv4_address(
    port_name: str, interface_ips: Dict[str, str], netbox_interfaces: Dict[str, Any]
) -> bool:
    """Check if an interface has a direct IPv4 address assigned."""
    if not interface_ips or not netbox_interfaces:
        return False

    if port_name in netbox_interfaces:
        netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]
        return netbox_interface_name in interface_ips

    return False


def _has_transfer_role_ipv4(
    port_name: str, transfer_ips: Dict[str, str], netbox_interfaces: Dict[str, Any]
) -> bool:
    """Check if an interface has an IPv4 from a transfer role prefix."""
    if not transfer_ips or not netbox_interfaces:
        return False

    if port_name in netbox_interfaces:
        netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]
        return netbox_interface_name in transfer_ips

    return False


def add_bfd_configurations(
    config: Dict[str, Any],
    connected_interfaces: Set[str],
    connected_portchannels: Set[str],
    portchannel_info: Dict[str, Any],
    device: Any,
    interface_ips: Dict[str, str] = None,
    netbox_interfaces: Dict[str, Any] = None,
    transfer_ips: Dict[str, str] = None,
    bgp_neighbor_interfaces: Set[str] = None,
) -> None:
    """Add BFD configuration to SONiC config.

    Adds BFD_PROFILE and BFD_PEER configurations for qualifying interfaces.

    Args:
        config: SONiC configuration dictionary to update
        connected_interfaces: Set of connected interface names
        connected_portchannels: Set of connected port channel names
        portchannel_info: Port channel membership information
        device: NetBox device object
        interface_ips: Dict of direct IPv4 addresses on interfaces
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
        transfer_ips: Dict of IPv4 addresses from transfer role prefixes
        bgp_neighbor_interfaces: Set of interfaces with BGP neighbors
    """
    # Initialize BFD configuration sections if they don't exist
    if "BFD_PROFILE" not in config:
        config["BFD_PROFILE"] = {}
    if "BFD_PEER" not in config:
        config["BFD_PEER"] = {}

    # Add default BFD profile
    config["BFD_PROFILE"]["default"] = {
        "detect_multiplier": "3",
        "desired_min_tx": "300",
        "required_min_rx": "300",
        "passive_mode": "false",
    }

    bfd_interface_count = 0

    # Process regular interfaces
    for port_name in config.get("PORT", {}):
        if should_interface_have_bfd(
            port_name=port_name,
            connected_interfaces=connected_interfaces,
            connected_portchannels=connected_portchannels,
            portchannel_info=portchannel_info,
            device=device,
            interface_ips=interface_ips,
            netbox_interfaces=netbox_interfaces,
            transfer_ips=transfer_ips,
            bgp_neighbors=bgp_neighbor_interfaces,
        ):
            # Add BFD peer configuration for this interface
            peer_key = f"default|{port_name}"
            config["BFD_PEER"][peer_key] = {"profile": "default", "multihop": "false"}
            bfd_interface_count += 1
            logger.debug(f"Added BFD configuration for interface {port_name}")

    # Process port channels
    for pc_name in connected_portchannels:
        if should_interface_have_bfd(
            port_name=pc_name,
            connected_interfaces=connected_interfaces,
            connected_portchannels=connected_portchannels,
            portchannel_info=portchannel_info,
            device=device,
            interface_ips=interface_ips,
            netbox_interfaces=netbox_interfaces,
            transfer_ips=transfer_ips,
            bgp_neighbors=bgp_neighbor_interfaces,
        ):
            # Add BFD peer configuration for this port channel
            peer_key = f"default|{pc_name}"
            config["BFD_PEER"][peer_key] = {"profile": "default", "multihop": "false"}
            bfd_interface_count += 1
            logger.debug(f"Added BFD configuration for port channel {pc_name}")

    logger.info(
        f"Added BFD configuration to {bfd_interface_count} interfaces on device {device.name}"
    )
