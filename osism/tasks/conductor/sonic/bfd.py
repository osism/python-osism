# SPDX-License-Identifier: Apache-2.0

"""BFD configuration logic for SONiC."""

from loguru import logger
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

# Combined list of all BFD-enabled roles
BFD_ENABLED_ROLES = NETBOX_NODE_ROLES + NETBOX_SWITCH_ROLES


def should_interface_have_bfd(
    port_name,
    device,
    bgp_neighbor_interfaces,
    interface_ips=None,
    netbox_interfaces=None,
    transfer_ips=None,
    portchannel_info=None,
):
    """Determine if an interface should have BFD configuration.

    An interface qualifies for BFD configuration if ALL these criteria are met:
    1. The interface already has BGP neighbor configuration
    2. The connected device has a role from BFD_ENABLED_ROLES
    3. The interface has either:
       - IPv4 addresses from transfer role prefixes, OR
       - No direct IPv4 addresses (IPv6-only mode)
    4. Regular interfaces must not be port channel members (BFD is configured on the port channel itself)

    Args:
        port_name: SONiC interface name (e.g., "Ethernet0", "PortChannel1")
        device: NetBox device object
        bgp_neighbor_interfaces: Set of interface names that have BGP neighbors
        interface_ips: Dict of direct IPv4 addresses on interfaces
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
        transfer_ips: Dict of IPv4 addresses from transfer role prefixes
        portchannel_info: Port channel membership information

    Returns:
        bool: True if interface should have BFD configuration, False otherwise
    """
    # Check if interface already has BGP neighbor configuration
    if port_name not in bgp_neighbor_interfaces:
        logger.debug(
            f"Interface {port_name} excluded from BFD: no BGP neighbor configuration"
        )
        return False

    # Check if this is a port channel member (BFD should be on the port channel, not member)
    if portchannel_info and port_name in portchannel_info.get("member_mapping", {}):
        logger.debug(f"Interface {port_name} excluded from BFD: port channel member")
        return False

    # Get connected device
    connected_device = get_connected_device_for_sonic_interface(device, port_name)
    if not connected_device:
        logger.debug(
            f"Interface {port_name} excluded from BFD: no connected device found"
        )
        return False

    # Check if connected device has a BFD-enabled role
    if not connected_device.role or connected_device.role.slug not in BFD_ENABLED_ROLES:
        logger.debug(
            f"Interface {port_name} excluded from BFD: connected device {connected_device.name} "
            f"has role '{connected_device.role.slug if connected_device.role else 'None'}' "
            f"(not in BFD_ENABLED_ROLES)"
        )
        return False

    # Check network type criteria (transfer role IPv4 OR IPv6-only mode)
    has_direct_ipv4 = _has_direct_ipv4_address(
        port_name, interface_ips, netbox_interfaces
    )
    has_transfer_ipv4 = _has_transfer_role_ipv4(
        port_name, transfer_ips, netbox_interfaces
    )

    # Include interfaces with transfer role IPv4 or no direct IPv4 (IPv6-only)
    if has_transfer_ipv4 or not has_direct_ipv4:
        logger.debug(
            f"Interface {port_name} qualifies for BFD: connected to {connected_device.name} "
            f"({connected_device.role.slug}), transfer_ipv4={has_transfer_ipv4}, "
            f"direct_ipv4={has_direct_ipv4}"
        )
        return True
    else:
        logger.debug(
            f"Interface {port_name} excluded from BFD: has direct IPv4 but not transfer role"
        )
        return False


def add_bfd_configurations(
    config,
    bgp_neighbor_interfaces,
    device,
    interface_ips=None,
    netbox_interfaces=None,
    transfer_ips=None,
    portchannel_info=None,
):
    """Add BFD configuration sections to the SONiC configuration.

    This function adds BFD_PROFILE and BFD_PEER configurations for interfaces
    that qualify for BFD based on the specified criteria.

    Args:
        config: Configuration dictionary to update
        bgp_neighbor_interfaces: Set of interface names that have BGP neighbors
        device: NetBox device object
        interface_ips: Dict of direct IPv4 addresses on interfaces
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
        transfer_ips: Dict of IPv4 addresses from transfer role prefixes
        portchannel_info: Port channel membership information
    """
    # Initialize BFD configuration sections
    if "BFD_PROFILE" not in config:
        config["BFD_PROFILE"] = {}
    if "BFD_PEER" not in config:
        config["BFD_PEER"] = {}

    # Add default BFD profile with SONiC best practices
    config["BFD_PROFILE"]["default"] = {
        "detect_multiplier": "3",  # Number of missed packets before declaring failure
        "desired_min_tx": "300",  # Desired minimum TX interval (ms)
        "required_min_rx": "300",  # Required minimum RX interval (ms)
        "passive_mode": "false",  # Active BFD mode
    }

    bfd_interface_count = 0

    # Check all interfaces for BFD eligibility
    all_interfaces = set()

    # Add regular interfaces
    if "PORT" in config:
        all_interfaces.update(config["PORT"].keys())

    # Add port channels
    if "PORTCHANNEL" in config:
        all_interfaces.update(config["PORTCHANNEL"].keys())

    for interface_name in all_interfaces:
        if should_interface_have_bfd(
            interface_name,
            device,
            bgp_neighbor_interfaces,
            interface_ips,
            netbox_interfaces,
            transfer_ips,
            portchannel_info,
        ):
            # Add BFD peer configuration
            peer_key = f"default|{interface_name}"
            config["BFD_PEER"][peer_key] = {
                "profile": "default",  # Use default BFD profile
                "multihop": "false",  # Single-hop BFD (directly connected)
            }
            bfd_interface_count += 1
            logger.info(f"Added BFD configuration for interface {interface_name}")

    logger.info(
        f"Added BFD configuration for {bfd_interface_count} interfaces on device {device.name}"
    )


def _has_direct_ipv4_address(port_name, interface_ips, netbox_interfaces):
    """Check if an interface has a direct IPv4 address assigned.

    Args:
        port_name: SONiC interface name (e.g., "Ethernet0")
        interface_ips: Dict mapping NetBox interface names to IPv4 addresses
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info

    Returns:
        bool: True if interface has a direct IPv4 address, False otherwise
    """
    if not interface_ips or not netbox_interfaces:
        return False

    if port_name in netbox_interfaces:
        netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]
        return netbox_interface_name in interface_ips

    return False


def _has_transfer_role_ipv4(port_name, transfer_ips, netbox_interfaces):
    """Check if an interface has an IPv4 from a transfer role prefix.

    Args:
        port_name: SONiC interface name (e.g., "Ethernet0")
        transfer_ips: Dict mapping NetBox interface names to transfer role IPv4 addresses
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info

    Returns:
        bool: True if interface has a transfer role IPv4 address, False otherwise
    """
    if not transfer_ips or not netbox_interfaces:
        return False

    if port_name in netbox_interfaces:
        netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]
        return netbox_interface_name in transfer_ips

    return False
