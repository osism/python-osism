# SPDX-License-Identifier: Apache-2.0

"""Configuration generation logic for SONiC."""

import copy
import ipaddress
import json
import os
import re
from typing import Optional
from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import (
    get_device_interface_ips,
    get_device_loopbacks,
    get_device_oob_ip,
    get_device_vlans,
)
from .bgp import calculate_local_asn_from_ipv4
from .device import get_device_platform, get_device_hostname, get_device_mac_address
from .interface import (
    get_port_config,
    get_speed_from_port_type,
    convert_netbox_interface_to_sonic,
    convert_sonic_interface_to_alias,
    detect_breakout_ports,
    detect_port_channels,
    clear_port_config_cache,
)
from .connections import (
    get_connected_interfaces,
    get_connected_device_for_sonic_interface,
    get_connected_interface_ipv4_address,
)
from .cache import get_cached_device_interfaces

# Global cache for NTP servers to avoid multiple queries
_ntp_servers_cache = None

# Global cache for metalbox IPs per device to avoid duplicate lookups
_metalbox_ip_cache: dict[int, Optional[str]] = {}

# Global cache for all metalbox devices with their interfaces and IPs
_metalbox_devices_cache: Optional[dict] = None


def natural_sort_key(port_name):
    """Extract numeric part from port name for natural sorting."""
    match = re.search(r"(\d+)", port_name)
    return int(match.group(1)) if match else 0


def generate_sonic_config(device, hwsku, device_as_mapping=None, config_version=None):
    """Generate minimal SONiC config.json for a device.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name
        device_as_mapping: Dict mapping device IDs to pre-calculated AS numbers for spine/superspine groups
        config_version: Optional custom CONFIG DB VERSION (e.g., "version_4_0_1")

    Returns:
        dict: Minimal SONiC configuration dictionary
    """
    # Get port configuration for the HWSKU
    port_config = get_port_config(hwsku)

    # Get port channel configuration from NetBox first (needed by get_connected_interfaces)
    portchannel_info = detect_port_channels(device)

    # Get connected interfaces to determine admin_status
    connected_interfaces, connected_portchannels = get_connected_interfaces(
        device, portchannel_info
    )

    # Get OOB IP for management interface
    oob_ip_result = get_device_oob_ip(device)

    # Get VLAN configuration from NetBox
    vlan_info = get_device_vlans(device)

    # Get Loopback configuration from NetBox
    loopback_info = get_device_loopbacks(device)

    # Get VRF configuration from NetBox
    vrf_info = _get_vrf_info(device)

    # Get interface IP addresses from NetBox
    interface_ips = get_device_interface_ips(device)

    # Get IPv4 addresses from transfer role prefixes
    transfer_ips = _get_transfer_role_ipv4_addresses(device)

    # Get breakout port configuration from NetBox
    breakout_info = detect_breakout_ports(device)

    # Get all interfaces from NetBox with their speeds and types
    netbox_interfaces = {}
    try:
        interfaces = get_cached_device_interfaces(device.id)
        for interface in interfaces:
            # Convert NetBox interface name to SONiC format for lookup
            interface_speed = getattr(interface, "speed", None)
            # Track if speed was explicitly set in NetBox (not derived from port type)
            speed_explicit = interface_speed is not None
            # If speed is not set, try to get it from port type
            if not interface_speed and hasattr(interface, "type") and interface.type:
                interface_speed = get_speed_from_port_type(interface.type.value)
            sonic_name = convert_netbox_interface_to_sonic(interface, device)
            netbox_interfaces[sonic_name] = {
                "speed": interface_speed,
                "speed_explicit": speed_explicit,
                "type": (
                    getattr(interface.type, "value", None)
                    if hasattr(interface, "type") and interface.type
                    else None
                ),
                "netbox_name": interface.name,
            }
    except Exception as e:
        logger.warning(f"Could not get interface details from NetBox: {e}")

    # Get device metadata using helper functions
    platform = get_device_platform(device, hwsku)
    hostname = get_device_hostname(device)
    mac_address = get_device_mac_address(device)

    # Try to load base configuration from /etc/sonic/config_db.json
    # Always start with a fresh, empty configuration for each device
    base_config_path = "/etc/sonic/config_db.json"
    config = {}

    try:
        if os.path.exists(base_config_path):
            with open(base_config_path, "r") as f:
                base_config = json.load(f)
                # Create a deep copy to ensure no cross-device contamination
                config = copy.deepcopy(base_config)
                logger.info(
                    f"Loaded fresh base configuration from {base_config_path} for device {device.name}"
                )
        else:
            logger.debug(
                f"Base config file {base_config_path} not found, starting with empty config for device {device.name}"
            )
    except Exception as e:
        logger.warning(
            f"Could not load base configuration from {base_config_path} for device {device.name}: {e}"
        )
        # Ensure we start fresh even on error
        config = {}

    # Update DEVICE_METADATA with NetBox information
    if "localhost" not in config["DEVICE_METADATA"]:
        config["DEVICE_METADATA"]["localhost"] = {}

    config["DEVICE_METADATA"]["localhost"].update(
        {
            "hostname": hostname,
            "hwsku": hwsku,
            "platform": platform,
            "mac": mac_address,
        }
    )

    # Add BGP_GLOBALS configuration with router_id set to primary IP address
    primary_ip = None
    if device.primary_ip4:
        primary_ip = str(device.primary_ip4.address).split("/")[0]
    elif device.primary_ip6:
        primary_ip = str(device.primary_ip6.address).split("/")[0]

    if primary_ip:
        if "default" not in config["BGP_GLOBALS"]:
            config["BGP_GLOBALS"]["default"] = {}
        config["BGP_GLOBALS"]["default"]["router_id"] = primary_ip

        # Calculate and add local_asn from router_id (only for IPv4)
        if device.primary_ip4:
            try:
                # Check if device is in a spine/superspine group with pre-calculated AS
                if device_as_mapping and device.id in device_as_mapping:
                    local_asn = device_as_mapping[device.id]
                    logger.debug(
                        f"Using group-calculated AS {local_asn} for spine/superspine device {device.name}"
                    )
                else:
                    # Use normal AS calculation for leaf switches and non-grouped devices
                    local_asn = calculate_local_asn_from_ipv4(primary_ip)

                config["BGP_GLOBALS"]["default"]["local_asn"] = str(local_asn)
            except ValueError as e:
                logger.warning(
                    f"Could not calculate local ASN for device {device.name}: {e}"
                )

    # Add port configurations
    _add_port_configurations(
        config,
        port_config,
        connected_interfaces,
        portchannel_info,
        breakout_info,
        netbox_interfaces,
        vlan_info,
        device,
    )

    # Add interface configurations
    _add_interface_configurations(
        config,
        connected_interfaces,
        portchannel_info,
        interface_ips,
        netbox_interfaces,
        device,
    )

    # Add BGP configurations
    _add_bgp_configurations(
        config,
        connected_interfaces,
        connected_portchannels,
        portchannel_info,
        device,
        device_as_mapping,
        interface_ips,
        netbox_interfaces,
        transfer_ips,
        utils.nb,
        vlan_info,
    )

    # Add NTP server configuration (device-specific)
    _add_ntp_configuration(config, device)

    # Add DNS server configuration (device-specific)
    _add_dns_configuration(config, device)

    # Add VLAN configuration
    _add_vlan_configuration(config, vlan_info, netbox_interfaces, device)

    # Add Loopback configuration
    _add_loopback_configuration(config, loopback_info)

    # Add management interface configuration
    if oob_ip_result:
        oob_ip, prefix_len = oob_ip_result
        config["MGMT_INTERFACE"]["eth0"] = {"admin_status": "up"}
        config["MGMT_INTERFACE"][f"eth0|{oob_ip}/{prefix_len}"] = {}

    # Add breakout configuration
    if breakout_info["breakout_cfgs"]:
        config["BREAKOUT_CFG"].update(breakout_info["breakout_cfgs"])
    if breakout_info["breakout_ports"]:
        config["BREAKOUT_PORTS"].update(breakout_info["breakout_ports"])

    # Add port channel configuration
    _add_portchannel_configuration(config, portchannel_info)

    # Add VRF configuration
    _add_vrf_configuration(config, vrf_info, netbox_interfaces)

    # Set DATABASE VERSION from config_version parameter or default
    if "VERSION" not in config:
        config["VERSION"] = {}
    if "DATABASE" not in config["VERSION"]:
        config["VERSION"]["DATABASE"] = {}

    if config_version:
        # Normalize config_version: add "version_" prefix if not present
        normalized_version = config_version
        if not config_version.startswith("version_"):
            normalized_version = f"version_{config_version}"
            logger.debug(
                f"Normalized config_version from '{config_version}' to '{normalized_version}' for device {device.name}"
            )

        config["VERSION"]["DATABASE"]["VERSION"] = normalized_version
        logger.info(
            f"Using custom config_version '{normalized_version}' for device {device.name}"
        )
    elif "VERSION" not in config.get("VERSION", {}).get("DATABASE", {}):
        config["VERSION"]["DATABASE"]["VERSION"] = "version_4_0_1"
        logger.debug(
            f"Using default config_version 'version_4_0_1' for device {device.name}"
        )

    return config


def _add_port_configurations(
    config,
    port_config,
    connected_interfaces,
    portchannel_info,
    breakout_info,
    netbox_interfaces,
    vlan_info,
    device,
):
    """Add port configurations to config."""
    # Sort ports naturally (Ethernet0, Ethernet4, Ethernet8, ...)
    sorted_ports = sorted(port_config.keys(), key=natural_sort_key)

    for port_name in sorted_ports:
        port_info = port_config[port_name]

        # Skip master ports that have breakout configurations
        # These will be replaced by their individual breakout ports
        if port_name in breakout_info["breakout_cfgs"]:
            logger.debug(
                f"Skipping master port {port_name} - has breakout configuration"
            )
            continue

        # Set admin_status to "up" if port is connected or is a port channel member, otherwise "down"
        admin_status = (
            "up"
            if (
                port_name in connected_interfaces
                or port_name in portchannel_info["member_mapping"]
            )
            else "down"
        )

        # Check if this port is a breakout port and adjust speed and lanes accordingly
        port_speed = port_info["speed"]
        port_lanes = port_info["lanes"]

        # Override with NetBox data if available
        # - Always use explicitly set NetBox speed (overrides port config)
        # - Use derived speed (from port type) only if port config has no speed
        # Note: NetBox stores speed in kbps, SONiC expects Mbps (divide by 1000)
        if port_name in netbox_interfaces:
            netbox_speed = netbox_interfaces[port_name]["speed"]
            speed_explicit = netbox_interfaces[port_name].get("speed_explicit", False)
            if netbox_speed:
                # Convert NetBox speed (kbps) to SONiC speed (Mbps)
                sonic_speed = str(int(netbox_speed) // 1000)
                if speed_explicit:
                    # Explicitly set speed in NetBox always takes precedence
                    if sonic_speed != str(port_speed):
                        logger.info(
                            f"Using explicit NetBox speed {netbox_speed} kbps -> {sonic_speed} Mbps for port {port_name} "
                            f"(overriding port config speed: {port_speed})"
                        )
                    port_speed = sonic_speed
                elif not port_speed or port_speed == "0":
                    # Derived speed (from port type) only used if port config has no speed
                    logger.info(
                        f"Using derived NetBox speed {netbox_speed} kbps -> {sonic_speed} Mbps for port {port_name} "
                        f"(hardware config had: {port_speed})"
                    )
                    port_speed = sonic_speed

        if port_name in breakout_info["breakout_ports"]:
            # Get the master port to determine original speed and lanes
            master_port = breakout_info["breakout_ports"][port_name]["master"]

            # Override with individual breakout port speed from NetBox if available
            if port_name in netbox_interfaces and netbox_interfaces[port_name]["speed"]:
                # Convert NetBox speed (kbps) to SONiC speed (Mbps)
                netbox_speed = netbox_interfaces[port_name]["speed"]
                port_speed = str(int(netbox_speed) // 1000)
                logger.debug(
                    f"Using NetBox speed {netbox_speed} kbps -> {port_speed} Mbps for breakout port {port_name}"
                )
            elif master_port in breakout_info["breakout_cfgs"]:
                # Fallback to extracting speed from breakout mode
                brkout_mode = breakout_info["breakout_cfgs"][master_port]["brkout_mode"]
                if "25G" in brkout_mode:
                    port_speed = "25000"
                elif "50G" in brkout_mode:
                    port_speed = "50000"
                elif "100G" in brkout_mode:
                    port_speed = "100000"
                elif "200G" in brkout_mode:
                    port_speed = "200000"

            # Calculate individual lane for this breakout port
            port_lanes = _calculate_breakout_port_lane(
                port_name, master_port, port_config
            )

        # Generate correct alias based on port name and speed
        interface_speed = int(port_speed) if port_speed else None
        is_breakout_port = port_name in breakout_info["breakout_ports"]
        correct_alias = convert_sonic_interface_to_alias(
            port_name, interface_speed, is_breakout_port, port_config
        )

        # Use master port index for breakout ports
        port_index = port_info["index"]
        if is_breakout_port:
            master_port = breakout_info["breakout_ports"][port_name]["master"]
            if master_port in port_config:
                port_index = port_config[master_port]["index"]

        port_data = {
            "admin_status": admin_status,
            "alias": correct_alias,
            "index": port_index,
            "lanes": port_lanes,
            "speed": port_speed,
            "mtu": "9100",
            "adv_speeds": "all",
            "autoneg": "off",
            "link_training": "off",
            "unreliable_los": "auto",
        }

        # Add valid_speeds if available in port_info, otherwise use port speed
        if "valid_speeds" in port_info:
            port_data["valid_speeds"] = port_info["valid_speeds"]
        elif port_speed:
            # Use port speed as valid_speeds if not configured in port_info
            port_data["valid_speeds"] = port_speed

        # Override valid_speeds for breakout ports based on their individual speed
        if port_name in breakout_info["breakout_ports"]:
            # For breakout ports, set valid_speeds based on the port's speed
            breakout_valid_speeds = _get_breakout_port_valid_speeds(port_speed)
            if breakout_valid_speeds:
                port_data["valid_speeds"] = breakout_valid_speeds

        config["PORT"][port_name] = port_data

    # Add all breakout ports (since master ports were skipped above)
    _add_missing_breakout_ports(
        config,
        breakout_info,
        port_config,
        connected_interfaces,
        portchannel_info,
        netbox_interfaces,
    )

    # Add tagged VLANs to PORT configuration
    _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device)


def _get_breakout_port_valid_speeds(port_speed):
    """Get valid speeds for a breakout port based on its configured speed."""
    if not port_speed:
        return None

    speed_int = int(port_speed)

    if speed_int == 25000:
        return "25000,10000,1000"
    elif speed_int == 50000:
        return "50000,25000,10000,1000"
    elif speed_int == 100000:
        return "100000,50000,25000,10000,1000"
    elif speed_int == 200000:
        return "200000,100000,50000,25000,10000,1000"
    else:
        # For other speeds, include common lower speeds
        return f"{port_speed},10000,1000"


def _calculate_breakout_port_lane(port_name, master_port, port_config):
    """Calculate lane(s) for a breakout port.

    Supports both standard breakout (4 lanes -> 4x1 lane ports) and
    400G breakout (8 lanes -> 4x2 lane ports).

    Examples:
        Standard 100G -> 4x25G (4 lanes total):
            Master: Ethernet0 with lanes "1,2,3,4"
            Ethernet0 -> "1"
            Ethernet1 -> "2"
            Ethernet2 -> "3"
            Ethernet3 -> "4"

        400G -> 4x100G (8 lanes total):
            Master: Ethernet0 with lanes "73,74,75,76,77,78,79,80"
            Ethernet0 -> "73,74"
            Ethernet2 -> "75,76"
            Ethernet4 -> "77,78"
            Ethernet6 -> "79,80"
    """
    # Get master port's lanes from port_config
    if master_port in port_config:
        master_lanes = port_config[master_port]["lanes"]
        # Parse lane range (e.g., "1,2,3,4" or "1-4")
        if "," in master_lanes:
            lanes_list = [int(lane.strip()) for lane in master_lanes.split(",")]
        elif "-" in master_lanes:
            start, end = map(int, master_lanes.split("-"))
            lanes_list = list(range(start, end + 1))
        else:
            # Single lane or simple number
            lanes_list = [int(master_lanes)]

        total_lanes = len(lanes_list)

        # Determine lanes per port based on total lanes
        if total_lanes == 8:
            # 400G breakout: 8 lanes -> 4 ports with 2 lanes each
            lanes_per_port = 2
            logger.debug(
                f"Detected 400G breakout for {master_port}: 8 lanes -> 4x2 lanes per port"
            )
        elif total_lanes == 4:
            # Standard breakout: 4 lanes -> 4 ports with 1 lane each
            lanes_per_port = 1
        else:
            # Unexpected lane count, log warning and use default
            logger.warning(
                f"Unexpected lane count {total_lanes} for master port {master_port}, defaulting to 1 lane per port"
            )
            lanes_per_port = 1

        # Calculate which lane(s) this breakout port should use
        port_match = re.match(r"Ethernet(\d+)", port_name)
        if port_match:
            sonic_port_num = int(port_match.group(1))
            master_port_match = re.match(r"Ethernet(\d+)", master_port)
            if master_port_match:
                master_port_num = int(master_port_match.group(1))

                # Calculate port increment (considering the port naming pattern)
                port_increment = sonic_port_num - master_port_num

                # Calculate subport index based on lanes per port
                # For 400G: Ethernet0,2,4,6 -> indices 0,1,2,3
                # For standard: Ethernet0,1,2,3 -> indices 0,1,2,3
                subport_index = port_increment // lanes_per_port

                # Extract the appropriate lanes for this subport
                start_lane_idx = subport_index * lanes_per_port
                end_lane_idx = start_lane_idx + lanes_per_port

                if end_lane_idx <= len(lanes_list):
                    selected_lanes = lanes_list[start_lane_idx:end_lane_idx]
                    result = ",".join(str(lane) for lane in selected_lanes)
                    logger.debug(
                        f"Breakout lane calculation: {port_name} (offset={port_increment}, "
                        f"subport_index={subport_index}) -> lanes {result}"
                    )
                    return result
                else:
                    logger.warning(
                        f"Breakout port {port_name}: calculated lane range [{start_lane_idx}:{end_lane_idx}] "
                        f"out of bounds for lanes_list {lanes_list}"
                    )
    return "1"  # Default fallback


def _add_missing_breakout_ports(
    config,
    breakout_info,
    port_config,
    connected_interfaces,
    portchannel_info,
    netbox_interfaces,
):
    """Add all breakout ports to config (master ports are skipped in main loop)."""
    for port_name in breakout_info["breakout_ports"]:
        if port_name not in config["PORT"]:
            # Get the master port to determine configuration
            master_port = breakout_info["breakout_ports"][port_name]["master"]

            # Override with individual breakout port speed from NetBox if available
            if port_name in netbox_interfaces and netbox_interfaces[port_name]["speed"]:
                port_speed = str(netbox_interfaces[port_name]["speed"])
                logger.debug(
                    f"Using NetBox speed {port_speed} for missing breakout port {port_name}"
                )
            elif master_port in breakout_info["breakout_cfgs"]:
                # Fallback to extracting speed from breakout mode
                brkout_mode = breakout_info["breakout_cfgs"][master_port]["brkout_mode"]
                if "25G" in brkout_mode:
                    port_speed = "25000"
                elif "50G" in brkout_mode:
                    port_speed = "50000"
                elif "100G" in brkout_mode:
                    port_speed = "100000"
                elif "200G" in brkout_mode:
                    port_speed = "200000"
                else:
                    port_speed = "25000"  # Default fallback
            else:
                port_speed = "25000"  # Default fallback

            # Set admin_status based on connection or port channel membership
            admin_status = (
                "up"
                if (
                    port_name in connected_interfaces
                    or port_name in portchannel_info["member_mapping"]
                )
                else "down"
            )

            # Generate correct alias (breakout port always gets subport notation)
            interface_speed = int(port_speed)
            correct_alias = convert_sonic_interface_to_alias(
                port_name, interface_speed, is_breakout=True, port_config=port_config
            )

            # Use master port index for breakout ports
            port_index = "1"  # Default fallback
            if master_port in port_config:
                port_index = port_config[master_port]["index"]

            # Calculate individual lane for this breakout port
            port_lanes = _calculate_breakout_port_lane(
                port_name, master_port, port_config
            )

            port_data = {
                "admin_status": admin_status,
                "alias": correct_alias,
                "index": port_index,
                "lanes": port_lanes,
                "speed": port_speed,
                "mtu": "9100",
                "adv_speeds": "all",
                "autoneg": "off",
                "link_training": "off",
                "unreliable_los": "auto",
            }

            # For breakout ports, check if master port has valid_speeds
            if (
                master_port in port_config
                and "valid_speeds" in port_config[master_port]
            ):
                port_data["valid_speeds"] = port_config[master_port]["valid_speeds"]

            # Override valid_speeds for breakout ports based on their individual speed
            breakout_valid_speeds = _get_breakout_port_valid_speeds(port_speed)
            if breakout_valid_speeds:
                port_data["valid_speeds"] = breakout_valid_speeds

            config["PORT"][port_name] = port_data


def _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device):
    """Add tagged VLANs to PORT configuration."""
    # Build reverse mapping once: NetBox interface name -> SONiC interface name (O(1) lookups)
    netbox_name_to_sonic = {
        info["netbox_name"]: sonic_name
        for sonic_name, info in netbox_interfaces.items()
    }

    # Build a mapping of ports to their tagged VLANs
    port_tagged_vlans = {}
    for vid, members in vlan_info["vlan_members"].items():
        for netbox_interface_name, tagging_mode in members.items():
            # Convert NetBox interface name to SONiC format using O(1) lookup
            sonic_interface_name = netbox_name_to_sonic.get(netbox_interface_name)
            if not sonic_interface_name:
                logger.warning(
                    f"Interface {netbox_interface_name} not found in mapping"
                )
                continue

            # Only add if this is a tagged VLAN (not untagged)
            if tagging_mode == "tagged":
                if sonic_interface_name not in port_tagged_vlans:
                    port_tagged_vlans[sonic_interface_name] = []
                port_tagged_vlans[sonic_interface_name].append(str(vid))

    # Update PORT configuration with tagged VLANs
    for port_name in config["PORT"]:
        if port_name in port_tagged_vlans:
            # Sort the VLAN IDs numerically for consistent ordering
            tagged_vlans = sorted(port_tagged_vlans[port_name], key=int)
            config["PORT"][port_name]["tagged_vlans"] = tagged_vlans


def _add_interface_configurations(
    config,
    connected_interfaces,
    portchannel_info,
    interface_ips,
    netbox_interfaces,
    device,
):
    """Add INTERFACE configuration for connected interfaces."""
    for port_name in config["PORT"]:
        # Check if this port is in the connected interfaces set and not a port channel member
        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            # Find the NetBox interface name for this SONiC port
            netbox_interface_name = None
            if port_name in netbox_interfaces:
                netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]

            # Check if this interface has an IPv4 address assigned
            ipv4_address = None
            if netbox_interface_name and netbox_interface_name in interface_ips:
                ipv4_address = interface_ips[netbox_interface_name]
                logger.info(
                    f"Interface {port_name} ({netbox_interface_name}) has IPv4 address: {ipv4_address}"
                )

            if ipv4_address:
                # If IPv4 address is available, configure the interface with it
                # Add base interface entry (similar to VLAN_INTERFACE and LOOPBACK_INTERFACE patterns)
                config["INTERFACE"][port_name] = {}
                # Add IP address suffixed entry with scope and family parameters
                config["INTERFACE"][f"{port_name}|{ipv4_address}"] = {
                    "scope": "global",
                    "family": "IPv4",
                }
                logger.info(
                    f"Configured interface {port_name} with IPv4 address {ipv4_address}"
                )
            else:
                # Add interface to INTERFACE section with ipv6_use_link_local_only enabled
                config["INTERFACE"][port_name] = {"ipv6_use_link_local_only": "enable"}
                logger.debug(
                    f"Configured interface {port_name} with IPv6 link-local only"
                )


def _get_transfer_role_ipv4_addresses(device):
    """Get IPv4 addresses from IP prefixes with 'transfer' role.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary mapping interface names to their transfer role IPv4 addresses
              {
                  'interface_name': 'ip_address/prefix_length',
                  ...
              }
    """
    transfer_ips = {}

    try:
        # Use cached interfaces to avoid redundant API calls
        interfaces = get_cached_device_interfaces(device.id)

        # Bulk fetch all IP addresses for this device (single API call)
        all_ip_addresses = list(utils.nb.ipam.ip_addresses.filter(device_id=device.id))

        # Bulk fetch all transfer role prefixes (single API call)
        transfer_prefixes = list(utils.nb.ipam.prefixes.filter(role="transfer"))

        # Convert transfer prefixes to ipaddress network objects for efficient containment checks
        transfer_networks = []
        for prefix in transfer_prefixes:
            try:
                transfer_networks.append(ipaddress.ip_network(str(prefix.prefix)))
            except (ValueError, ipaddress.AddressValueError) as e:
                logger.debug(f"Invalid transfer prefix {prefix.prefix}: {e}")
                continue

        # Build a mapping from interface ID to interface object
        interface_map = {}
        for interface in interfaces:
            # Skip management interfaces and virtual interfaces
            if interface.mgmt_only or (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
            ):
                continue
            interface_map[interface.id] = interface

        # Process IP addresses and check if they belong to transfer role prefixes
        for ip_addr in all_ip_addresses:
            # Skip if IP not assigned to a valid interface
            if (
                not hasattr(ip_addr, "assigned_object_id")
                or not ip_addr.assigned_object_id
            ):
                continue

            if ip_addr.assigned_object_id not in interface_map:
                continue

            interface = interface_map[ip_addr.assigned_object_id]

            # Check if interface already has a transfer IP assigned
            if interface.name in transfer_ips:
                continue

            if ip_addr.address:
                try:
                    ip_obj = ipaddress.ip_interface(ip_addr.address)
                    if ip_obj.version == 4:
                        # Check if this IP belongs to any transfer role prefix
                        # Using in-memory containment check with ipaddress module
                        for transfer_net in transfer_networks:
                            if ip_obj.ip in transfer_net:
                                transfer_ips[interface.name] = ip_addr.address
                                logger.debug(
                                    f"Found transfer role IPv4 {ip_addr.address} on interface {interface.name} of device {device.name}"
                                )
                                break
                except (ValueError, ipaddress.AddressValueError):
                    # Skip invalid IP addresses
                    continue

    except Exception as e:
        logger.warning(
            f"Failed to get transfer role IPv4 addresses for device {device.name}: {e}"
        )

    return transfer_ips


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


def _is_untagged_vlan_member(port_name, vlan_info, netbox_interfaces):
    """Check if an interface is an untagged member of any VLAN.

    When an interface is an untagged VLAN member, BGP peering should happen
    over the VLAN interface (SVI) instead of the physical interface.

    Args:
        port_name: SONiC interface name (e.g., "Ethernet0")
        vlan_info: VLAN information dict with vlan_members structure
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info

    Returns:
        bool: True if interface is an untagged VLAN member, False otherwise
    """
    if not vlan_info or not netbox_interfaces:
        return False

    # Get the NetBox interface name for this SONiC port
    if port_name not in netbox_interfaces:
        return False

    netbox_interface_name = netbox_interfaces[port_name]["netbox_name"]

    # Check all VLANs to see if this interface is an untagged member
    for vid, members in vlan_info.get("vlan_members", {}).items():
        if netbox_interface_name in members:
            tagging_mode = members[netbox_interface_name]
            if tagging_mode == "untagged":
                logger.debug(
                    f"Interface {port_name} ({netbox_interface_name}) is untagged member of VLAN {vid}"
                )
                return True

    return False


def _add_bgp_configurations(
    config,
    connected_interfaces,
    connected_portchannels,
    portchannel_info,
    device,
    device_as_mapping=None,
    interface_ips=None,
    netbox_interfaces=None,
    transfer_ips=None,
    netbox=None,
    vlan_info=None,
):
    """Add BGP configurations.

    Args:
        config: Configuration dictionary to update
        connected_interfaces: Set of connected interface names
        connected_portchannels: Set of connected port channel names
        portchannel_info: Port channel membership information
        device: NetBox device object
        device_as_mapping: Mapping of device names to AS numbers
        interface_ips: Dict of direct IPv4 addresses on interfaces
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
        transfer_ips: Dict of IPv4 addresses from transfer role prefixes
        netbox: NetBox API client for querying connected interface IPs
        vlan_info: VLAN information dict for checking untagged VLAN membership
    """
    # Add BGP_NEIGHBOR_AF configuration for connected interfaces
    for port_name in config["PORT"]:
        has_direct_ipv4 = _has_direct_ipv4_address(
            port_name, interface_ips, netbox_interfaces
        )
        has_transfer_ipv4 = _has_transfer_role_ipv4(
            port_name, transfer_ips, netbox_interfaces
        )
        is_untagged_vlan_member = _is_untagged_vlan_member(
            port_name, vlan_info, netbox_interfaces
        )

        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            # Skip interfaces that are untagged VLAN members - BGP peering happens over VLAN interface
            if is_untagged_vlan_member:
                logger.info(
                    f"Excluding interface {port_name} from BGP configuration (untagged VLAN member)"
                )
                continue

            # Include interfaces with transfer role IPv4 or no direct IPv4
            if has_transfer_ipv4 or not has_direct_ipv4:
                # Try to get the IPv4 address of the connected endpoint interface
                connected_ipv4 = None
                if netbox:
                    connected_ipv4 = get_connected_interface_ipv4_address(
                        device, port_name, netbox
                    )

                # For BGP_NEIGHBOR_AF, always use interface name like IPv6 does
                neighbor_id = port_name

                ipv4_key = f"default|{neighbor_id}|ipv4_unicast"
                config["BGP_NEIGHBOR_AF"][ipv4_key] = {"admin_status": "true"}

                # Only add ipv6_unicast if v6only would be true (no transfer role IPv4)
                if not has_transfer_ipv4:
                    ipv6_key = f"default|{neighbor_id}|ipv6_unicast"
                    config["BGP_NEIGHBOR_AF"][ipv6_key] = {"admin_status": "true"}
                    logger.debug(
                        f"Added BGP_NEIGHBOR_AF with ipv4_unicast and ipv6_unicast for interface {port_name} (no direct IPv4)"
                    )
                else:
                    logger.debug(
                        f"Added BGP_NEIGHBOR_AF with ipv4_unicast only for interface {port_name} (transfer role IPv4, v6only=false)"
                    )
            elif has_direct_ipv4 and not has_transfer_ipv4:
                logger.info(
                    f"Excluding interface {port_name} from BGP detection (has direct IPv4 address, not transfer role)"
                )

    # Add BGP_NEIGHBOR_AF configuration for connected port channels
    for pc_name in connected_portchannels:
        # Try to get the IPv4 address of the connected endpoint interface for port channel
        connected_ipv4 = None
        if netbox:
            connected_ipv4 = get_connected_interface_ipv4_address(
                device, pc_name, netbox
            )

        # For BGP_NEIGHBOR_AF, always use port channel name like interfaces
        neighbor_id = pc_name

        ipv4_key = f"default|{neighbor_id}|ipv4_unicast"
        ipv6_key = f"default|{neighbor_id}|ipv6_unicast"
        config["BGP_NEIGHBOR_AF"][ipv4_key] = {"admin_status": "true"}
        config["BGP_NEIGHBOR_AF"][ipv6_key] = {"admin_status": "true"}

    # Add BGP_NEIGHBOR configuration for connected interfaces
    for port_name in config["PORT"]:
        has_direct_ipv4 = _has_direct_ipv4_address(
            port_name, interface_ips, netbox_interfaces
        )
        has_transfer_ipv4 = _has_transfer_role_ipv4(
            port_name, transfer_ips, netbox_interfaces
        )
        is_untagged_vlan_member = _is_untagged_vlan_member(
            port_name, vlan_info, netbox_interfaces
        )

        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            # Skip interfaces that are untagged VLAN members - BGP peering happens over VLAN interface
            if is_untagged_vlan_member:
                logger.info(
                    f"Excluding interface {port_name} from BGP_NEIGHBOR configuration (untagged VLAN member)"
                )
                continue

            # Include interfaces with transfer role IPv4 or no direct IPv4
            if has_transfer_ipv4 or not has_direct_ipv4:
                # Try to get the IPv4 address of the connected endpoint interface
                connected_ipv4 = None
                if netbox:
                    connected_ipv4 = get_connected_interface_ipv4_address(
                        device, port_name, netbox
                    )

                # Use the connected interface's IPv4 address if available, otherwise use interface name
                if connected_ipv4:
                    neighbor_key = f"default|{connected_ipv4}"
                    logger.debug(
                        f"Using connected interface IPv4 address {connected_ipv4} for BGP neighbor on {port_name}"
                    )
                else:
                    neighbor_key = f"default|{port_name}"
                    logger.debug(
                        f"No connected interface IPv4 found, using interface name {port_name} for BGP neighbor"
                    )

                # Determine peer_type based on connected device AS
                peer_type = "external"  # Default
                connected_device = get_connected_device_for_sonic_interface(
                    device, port_name
                )
                if connected_device:
                    peer_type = _determine_peer_type(
                        device, connected_device, device_as_mapping
                    )

                # Set v6only based on whether interface has transfer role IPv4
                # - Transfer role IPv4: v6only=false (dual-stack BGP)
                # - No direct IPv4: v6only=true (IPv6-only BGP)
                bgp_neighbor_config = {
                    "peer_type": peer_type,
                    "v6only": "false" if has_transfer_ipv4 else "true",
                }

                # If using IP address as key, also store the local address
                if connected_ipv4:
                    # Get the local interface IPv4 address
                    local_ipv4 = None
                    if port_name in netbox_interfaces:
                        netbox_interface_name = netbox_interfaces[port_name][
                            "netbox_name"
                        ]
                        if netbox_interface_name in interface_ips:
                            local_ipv4 = interface_ips[netbox_interface_name].split(
                                "/"
                            )[0]
                        elif netbox_interface_name in transfer_ips:
                            local_ipv4 = transfer_ips[netbox_interface_name].split("/")[
                                0
                            ]

                    if local_ipv4:
                        bgp_neighbor_config["local_addr"] = local_ipv4

                config["BGP_NEIGHBOR"][neighbor_key] = bgp_neighbor_config

                if has_transfer_ipv4:
                    logger.debug(
                        f"Added BGP_NEIGHBOR for interface {port_name} (transfer role IPv4, v6only=false)"
                    )
                else:
                    logger.debug(
                        f"Added BGP_NEIGHBOR for interface {port_name} (no direct IPv4, v6only=true)"
                    )

    # Add BGP_NEIGHBOR configuration for connected port channels
    for pc_name in connected_portchannels:
        # Try to get the IPv4 address of the connected endpoint interface for port channel
        connected_ipv4 = None
        if netbox:
            connected_ipv4 = get_connected_interface_ipv4_address(
                device, pc_name, netbox
            )

        # Use the connected interface's IPv4 address if available, otherwise use port channel name
        if connected_ipv4:
            neighbor_key = f"default|{connected_ipv4}"
            logger.debug(
                f"Using connected interface IPv4 address {connected_ipv4} for BGP neighbor on {pc_name}"
            )
        else:
            neighbor_key = f"default|{pc_name}"
            logger.debug(
                f"No connected interface IPv4 found, using port channel name {pc_name} for BGP neighbor"
            )

        # Determine peer_type based on connected device AS
        peer_type = "external"  # Default
        connected_device = get_connected_device_for_sonic_interface(device, pc_name)
        if connected_device:
            peer_type = _determine_peer_type(
                device, connected_device, device_as_mapping
            )

        bgp_neighbor_config = {
            "peer_type": peer_type,
            "v6only": "true",
        }

        # If using IP address as key, also store the local address
        if connected_ipv4:
            # For port channels, get the local IPv4 address from interface IPs
            # Note: Port channels don't have direct IP assignments in NetBox,
            # so we use the connected interface IP logic
            local_ipv4 = None
            # Port channels don't have NetBox interface entries,
            # so we skip local_addr for port channels for now
            # TODO: Implement port channel local address lookup if needed

        config["BGP_NEIGHBOR"][neighbor_key] = bgp_neighbor_config

    # Add BGP configuration for VLAN interfaces (SVIs) based on peer IP addresses
    # For each VLAN interface with IP addresses, find the connected peer interfaces
    # and use their IP addresses (direct IP or FHRP VIP) as BGP neighbors
    if vlan_info and "vlan_interfaces" in vlan_info and "vlan_members" in vlan_info:
        for vid, vlan_interface_data in vlan_info["vlan_interfaces"].items():
            if "addresses" not in vlan_interface_data:
                continue

            addresses = vlan_interface_data["addresses"]
            if not addresses:
                continue

            # Find untagged member interfaces for this VLAN
            # Only untagged members are relevant for VLAN BGP neighbors
            if vid not in vlan_info["vlan_members"]:
                logger.debug(
                    f"No VLAN members found for VLAN {vid}, skipping BGP configuration"
                )
                continue

            vlan_members = vlan_info["vlan_members"][vid]
            untagged_members = [
                iface_name
                for iface_name, tagging_mode in vlan_members.items()
                if tagging_mode == "untagged"
            ]

            if not untagged_members:
                logger.debug(
                    f"No untagged members found for VLAN {vid}, skipping BGP configuration"
                )
                continue

            # For each untagged member interface, get the peer IP address
            # and create BGP neighbor with the peer IP (not local VLAN IP!)
            peer_ips_found = set()  # Track unique peer IPs to avoid duplicates

            for netbox_iface_name in untagged_members:
                # Convert NetBox interface name to SONiC name
                sonic_iface_name = None
                if netbox_interfaces:
                    for sonic_name, iface_info in netbox_interfaces.items():
                        if iface_info.get("netbox_name") == netbox_iface_name:
                            sonic_iface_name = sonic_name
                            break

                if not sonic_iface_name:
                    logger.debug(
                        f"Could not find SONiC name for NetBox interface {netbox_iface_name} "
                        f"in VLAN {vid}, skipping"
                    )
                    continue

                # Get peer IP address using the existing FHRP VIP detection logic
                peer_ipv4 = None
                if netbox:
                    peer_ipv4 = get_connected_interface_ipv4_address(
                        device, sonic_iface_name, netbox
                    )

                if peer_ipv4:
                    # Avoid duplicate peer IPs across multiple untagged members
                    if peer_ipv4 in peer_ips_found:
                        logger.debug(
                            f"Peer IP {peer_ipv4} already configured for VLAN {vid}, "
                            f"skipping duplicate from interface {sonic_iface_name}"
                        )
                        continue

                    peer_ips_found.add(peer_ipv4)

                    # Create BGP neighbor with peer IP address (FHRP VIP or direct IP)
                    neighbor_key = f"default|{peer_ipv4}"

                    # Determine peer_type - for VLAN interfaces, default to external
                    peer_type = "external"

                    # Set v6only=false for IPv4 BGP neighbor
                    bgp_neighbor_config = {
                        "peer_type": peer_type,
                        "v6only": "false",
                    }

                    config["BGP_NEIGHBOR"][neighbor_key] = bgp_neighbor_config

                    # Add BGP_NEIGHBOR_AF for IPv4 unicast
                    ipv4_af_key = f"default|{peer_ipv4}|ipv4_unicast"
                    config["BGP_NEIGHBOR_AF"][ipv4_af_key] = {"admin_status": "true"}

                    logger.info(
                        f"Added BGP neighbor configuration for VLAN {vid} using peer IP {peer_ipv4} "
                        f"from connected interface {sonic_iface_name} (NetBox: {netbox_iface_name})"
                    )
                else:
                    logger.debug(
                        f"No peer IPv4 address found for interface {sonic_iface_name} "
                        f"(NetBox: {netbox_iface_name}) in VLAN {vid}"
                    )

            if not peer_ips_found:
                logger.warning(
                    f"No peer IP addresses found for any untagged member of VLAN {vid}, "
                    f"no BGP neighbors configured"
                )


def _get_connected_device_for_interface(device, interface_name):
    """Get the connected device for a given interface name.

    Args:
        device: NetBox device object
        interface_name: SONiC interface name (e.g., "Ethernet0")

    Returns:
        NetBox device object or None if not found
    """
    return get_connected_device_for_sonic_interface(device, interface_name)


def _determine_peer_type(local_device, connected_device, device_as_mapping=None):
    """Determine BGP peer type (internal/external) based on AS number comparison.

    Args:
        local_device: Local NetBox device object
        connected_device: Connected NetBox device object
        device_as_mapping: Dict mapping device IDs to pre-calculated AS numbers

    Returns:
        str: "internal" if AS numbers match, "external" otherwise
    """
    try:
        # Get local AS number
        local_as = None
        if device_as_mapping and local_device.id in device_as_mapping:
            local_as = device_as_mapping[local_device.id]
        elif local_device.primary_ip4:
            local_as = calculate_local_asn_from_ipv4(
                str(local_device.primary_ip4.address)
            )

        # Get connected device AS number
        connected_as = None
        if device_as_mapping and connected_device.id in device_as_mapping:
            connected_as = device_as_mapping[connected_device.id]
        elif connected_device.primary_ip4:
            # If not in mapping (e.g., not in a spine/superspine group),
            # calculate AS directly from IPv4 address
            connected_as = calculate_local_asn_from_ipv4(
                str(connected_device.primary_ip4.address)
            )

        # Compare AS numbers
        if local_as and connected_as and local_as == connected_as:
            return "internal"
        else:
            return "external"

    except Exception as e:
        logger.debug(
            f"Could not determine peer type between {local_device.name} and {connected_device.name}: {e}"
        )
        return "external"  # Default to external on error


def _load_metalbox_devices_cache():
    """Load all metalbox devices with their interfaces and IPs into cache.

    This function performs bulk fetching at the start of sync to avoid
    repeated queries per device. It loads all metalbox devices, their
    interfaces, and IP addresses in a single pass.
    """
    global _metalbox_devices_cache

    logger.debug("Loading metalbox devices cache...")
    _metalbox_devices_cache = {}

    try:
        # Bulk fetch all metalbox devices
        metalbox_devices = list(utils.nb.dcim.devices.filter(role="metalbox"))
        logger.debug(f"Found {len(metalbox_devices)} metalbox devices")

        for metalbox in metalbox_devices:
            metalbox_data = {
                "device": metalbox,
                "interfaces": {},
            }

            # Bulk fetch all interfaces for this metalbox
            try:
                interfaces = list(
                    utils.nb.dcim.interfaces.filter(device_id=metalbox.id)
                )
                logger.debug(
                    f"Metalbox {metalbox.name} has {len(interfaces)} interfaces"
                )

                for interface in interfaces:
                    # Skip management-only interfaces
                    if hasattr(interface, "mgmt_only") and interface.mgmt_only:
                        continue

                    # Check if this is a VLAN interface (SVI)
                    is_vlan_interface = (
                        hasattr(interface, "type")
                        and interface.type
                        and interface.type.value == "virtual"
                        and interface.name.startswith("Vlan")
                    )

                    # Bulk fetch IP addresses for this interface
                    ip_addresses = list(
                        utils.nb.ipam.ip_addresses.filter(
                            assigned_object_id=interface.id,
                        )
                    )

                    # Store interface with its IPs
                    metalbox_data["interfaces"][interface.id] = {
                        "interface": interface,
                        "is_vlan": is_vlan_interface,
                        "ips": [ip_addr for ip_addr in ip_addresses if ip_addr.address],
                    }

            except Exception as e:
                logger.warning(
                    f"Could not fetch interfaces for metalbox {metalbox.name}: {e}"
                )

            _metalbox_devices_cache[metalbox.id] = metalbox_data

        logger.info(
            f"Loaded metalbox cache with {len(_metalbox_devices_cache)} devices"
        )

    except Exception as e:
        logger.warning(f"Could not load metalbox devices cache: {e}")
        _metalbox_devices_cache = {}


def _get_metalbox_ip_for_device(device):
    """Get Metalbox IP for a SONiC device based on OOB connection.

    Returns the IP address of the metalbox device interface that is connected to the
    OOB switch. If VLANs are used, returns the IP of the VLAN interface where the
    SONiC switch management interface (eth0) has access.

    This IP is used for both NTP and DNS services.

    Uses the pre-loaded metalbox devices cache for optimal performance.

    Args:
        device: SONiC device object

    Returns:
        str: IP address of the Metalbox or None if not found
    """
    # Check cache first
    if device.id in _metalbox_ip_cache:
        logger.debug(f"Using cached metalbox IP for device {device.name}")
        return _metalbox_ip_cache[device.id]

    try:
        # Get the OOB IP configuration for this SONiC device
        oob_ip_result = get_device_oob_ip(device)
        if not oob_ip_result:
            logger.debug(f"No OOB IP found for device {device.name}")
            _metalbox_ip_cache[device.id] = None
            return None

        oob_ip, prefix_len = oob_ip_result
        logger.debug(f"Device {device.name} has OOB IP {oob_ip}/{prefix_len}")

        # Find the network/subnet that contains this OOB IP
        from ipaddress import IPv4Network, IPv4Address

        device_network = IPv4Network(f"{oob_ip}/{prefix_len}", strict=False)

        # Use the pre-loaded metalbox devices cache
        if _metalbox_devices_cache is None:
            logger.warning(
                "Metalbox devices cache not loaded - call _load_metalbox_devices_cache() first"
            )
            _metalbox_ip_cache[device.id] = None
            return None

        # Iterate through cached metalbox devices
        for metalbox_id, metalbox_data in _metalbox_devices_cache.items():
            metalbox = metalbox_data["device"]
            logger.debug(f"Checking metalbox device {metalbox.name} for services")

            # Iterate through cached interfaces for this metalbox
            for interface_id, interface_data in metalbox_data["interfaces"].items():
                interface = interface_data["interface"]
                is_vlan_interface = interface_data["is_vlan"]

                # Check all cached IP addresses for this interface
                for ip_addr in interface_data["ips"]:
                    # Extract IP address without prefix
                    ip_only = ip_addr.address.split("/")[0]

                    # Check if it's IPv4 and in the same network as the SONiC device
                    try:
                        metalbox_ip = IPv4Address(ip_only)
                        if metalbox_ip in device_network:
                            interface_type = (
                                "VLAN interface" if is_vlan_interface else "interface"
                            )
                            logger.info(
                                f"Found Metalbox {ip_only} on {metalbox.name} "
                                f"{interface_type} {interface.name} for SONiC device {device.name}"
                            )
                            # Cache the result
                            _metalbox_ip_cache[device.id] = ip_only
                            return ip_only
                    except ValueError:
                        # Skip non-IPv4 addresses
                        continue

        logger.warning(f"No suitable Metalbox found for SONiC device {device.name}")
        # Cache None result to avoid repeated lookups
        _metalbox_ip_cache[device.id] = None
        return None

    except Exception as e:
        logger.warning(f"Could not determine Metalbox IP for device {device.name}: {e}")
        # Cache None result to avoid repeated lookups
        _metalbox_ip_cache[device.id] = None
        return None


def _get_ntp_servers():
    """Get NTP servers from manager/metalbox devices. Uses caching to avoid repeated queries."""
    global _ntp_servers_cache

    if _ntp_servers_cache is not None:
        logger.debug("Using cached NTP servers")
        return _ntp_servers_cache

    ntp_servers = {}
    try:
        # Get devices with manager or metalbox device roles
        devices_manager = utils.nb.dcim.devices.filter(role="manager")
        devices_metalbox = utils.nb.dcim.devices.filter(role="metalbox")

        # Combine both device lists
        ntp_devices = list(devices_manager) + list(devices_metalbox)
        logger.debug(f"Found {len(ntp_devices)} potential NTP devices")

        for ntp_device in ntp_devices:
            # Get interfaces for this device to find Loopback0
            device_interfaces = utils.nb.dcim.interfaces.filter(device_id=ntp_device.id)

            for interface in device_interfaces:
                # Look for Loopback0 interface
                if interface.name == "Loopback0":
                    # Get IP addresses assigned to this Loopback0 interface
                    ip_addresses = utils.nb.ipam.ip_addresses.filter(
                        assigned_object_id=interface.id,
                    )

                    for ip_addr in ip_addresses:
                        if ip_addr.address:
                            # Extract just the IPv4 address without prefix
                            ip_only = ip_addr.address.split("/")[0]

                            # Check if it's an IPv4 address (simple check)
                            if "." in ip_only and ":" not in ip_only:
                                ntp_servers[ip_only] = {
                                    "maxpoll": "10",
                                    "minpoll": "6",
                                    "prefer": "false",
                                }
                                logger.info(
                                    f"Found NTP server {ip_only} from device {ntp_device.name} with role {ntp_device.role.slug}"
                                )
                    break

        # Cache the results
        _ntp_servers_cache = ntp_servers
        logger.debug(f"Cached {len(ntp_servers)} NTP servers")

    except Exception as e:
        logger.warning(f"Could not process NTP servers: {e}")
        _ntp_servers_cache = {}

    return _ntp_servers_cache


def _add_ntp_configuration(config, device):
    """Add NTP_SERVER configuration to device config.

    Each SONiC switch gets exactly one NTP server - the IP address of the
    metalbox device interface connected to the OOB switch.
    """
    try:
        # Get the Metalbox IP for this device
        metalbox_ip = _get_metalbox_ip_for_device(device)

        if metalbox_ip:
            # Add single NTP server configuration
            config["NTP_SERVER"][metalbox_ip] = {
                "maxpoll": "10",
                "minpoll": "6",
                "prefer": "false",
            }
            logger.info(f"Added NTP server {metalbox_ip} to SONiC device {device.name}")
        else:
            logger.warning(f"No NTP server found for SONiC device {device.name}")

    except Exception as e:
        logger.warning(f"Could not add NTP configuration to device {device.name}: {e}")


def clear_ntp_cache():
    """Clear the NTP servers cache. Should be called at the start of sync_sonic."""
    global _ntp_servers_cache
    _ntp_servers_cache = None
    logger.debug("Cleared NTP servers cache")


def clear_metalbox_ip_cache():
    """Clear the metalbox IP cache. Should be called at the start of sync_sonic."""
    global _metalbox_ip_cache
    _metalbox_ip_cache = {}
    logger.debug("Cleared metalbox IP cache")


def clear_metalbox_devices_cache():
    """Clear the metalbox devices cache. Should be called at the start of sync_sonic."""
    global _metalbox_devices_cache
    _metalbox_devices_cache = None
    logger.debug("Cleared metalbox devices cache")


def _add_dns_configuration(config, device):
    """Add DNS_NAMESERVER configuration to device config.

    Each SONiC switch gets exactly one DNS server - the IP address of the
    metalbox device interface connected to the OOB switch.
    """
    try:
        # Get the Metalbox IP for this device
        metalbox_ip = _get_metalbox_ip_for_device(device)

        if metalbox_ip:
            # Add single DNS server configuration
            config["DNS_NAMESERVER"][metalbox_ip] = {}
            logger.info(f"Added DNS server {metalbox_ip} to SONiC device {device.name}")
        else:
            logger.warning(f"No DNS server found for SONiC device {device.name}")

    except Exception as e:
        logger.warning(f"Could not add DNS configuration to device {device.name}: {e}")


def clear_all_caches():
    """Clear all caches in config_generator module."""
    clear_ntp_cache()
    clear_metalbox_ip_cache()
    clear_metalbox_devices_cache()
    clear_port_config_cache()
    logger.debug("Cleared all config_generator caches")


def _add_vlan_configuration(config, vlan_info, netbox_interfaces, device):
    """Add VLAN configuration from NetBox."""
    # Build reverse mapping once: NetBox interface name -> SONiC interface name (O(1) lookups)
    netbox_name_to_sonic = {
        info["netbox_name"]: sonic_name
        for sonic_name, info in netbox_interfaces.items()
    }

    # Add VLAN configuration
    for vid, vlan_data in vlan_info["vlans"].items():
        vlan_name = f"Vlan{vid}"

        # Get member ports for this VLAN and convert interface names
        members = []
        if vid in vlan_info["vlan_members"]:
            for netbox_interface_name in vlan_info["vlan_members"][vid].keys():
                # Convert NetBox interface name to SONiC format using O(1) lookup
                sonic_interface_name = netbox_name_to_sonic.get(netbox_interface_name)
                if not sonic_interface_name:
                    logger.warning(
                        f"Interface {netbox_interface_name} not found in mapping"
                    )
                    continue
                members.append(sonic_interface_name)

        config["VLAN"][vlan_name] = {
            "admin_status": "up",
            "autostate": "enable",
            "members": members,
            "vlanid": str(vid),
        }

    # Add VLAN members
    for vid, members in vlan_info["vlan_members"].items():
        vlan_name = f"Vlan{vid}"
        for netbox_interface_name, tagging_mode in members.items():
            # Convert NetBox interface name to SONiC format using O(1) lookup
            sonic_interface_name = netbox_name_to_sonic.get(netbox_interface_name)
            if not sonic_interface_name:
                logger.warning(
                    f"Interface {netbox_interface_name} not found in mapping"
                )
                continue
            # Create VLAN_MEMBER key in format "Vlan<vid>|<port_name>"
            member_key = f"{vlan_name}|{sonic_interface_name}"
            config["VLAN_MEMBER"][member_key] = {"tagging_mode": tagging_mode}

    # Add VLAN interfaces (SVIs)
    for vid, interface_data in vlan_info["vlan_interfaces"].items():
        vlan_name = f"Vlan{vid}"
        if "addresses" in interface_data and interface_data["addresses"]:
            # Add the VLAN interface
            config["VLAN_INTERFACE"][vlan_name] = {"admin_status": "up"}

            # Add IP configuration for each address (IPv4 and IPv6)
            for address in interface_data["addresses"]:
                ip_key = f"{vlan_name}|{address}"
                config["VLAN_INTERFACE"][ip_key] = {}


def _add_loopback_configuration(config, loopback_info):
    """Add Loopback configuration from NetBox."""
    for loopback_name, loopback_data in loopback_info["loopbacks"].items():
        # Add the Loopback interface
        config["LOOPBACK"][loopback_name] = {"admin_status": "up"}

        # Add base Loopback interface entry
        config["LOOPBACK_INTERFACE"][loopback_name] = {}

        # Add IP configuration for each address (IPv4 and IPv6)
        for address in loopback_data["addresses"]:
            ip_key = f"{loopback_name}|{address}"
            config["LOOPBACK_INTERFACE"][ip_key] = {}

        # Add BGP_GLOBALS_AF_NETWORK configuration for Loopback0 devices
        if loopback_name == "Loopback0":
            for address in loopback_data["addresses"]:
                # Determine if this is IPv4 or IPv6 and set appropriate address family
                try:
                    ip_obj = ipaddress.ip_interface(address)
                    if ip_obj.version == 4:
                        af_key = f"default|ipv4_unicast|{address}"
                    elif ip_obj.version == 6:
                        af_key = f"default|ipv6_unicast|{address}"
                    else:
                        continue

                    config["BGP_GLOBALS_AF_NETWORK"][af_key] = {}
                except ValueError:
                    logger.warning(f"Invalid IP address format: {address}")
                    continue


def _get_vrf_info(device):
    """Get VRF configuration from NetBox interfaces.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary with VRF configuration:
            {
                "vrfs": {
                    "Vrf42": {"table_id": 42}
                },
                "interface_vrf_mapping": {
                    "Ethernet0": "Vrf42",
                    "Ethernet4": "Vrf42"
                }
            }
    """
    vrf_info = {"vrfs": {}, "interface_vrf_mapping": {}}

    try:
        # Get all interfaces for this device
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Check if interface has a VRF assigned
            if not hasattr(interface, "vrf") or not interface.vrf:
                continue

            try:
                # Extract VRF table ID from VRF name (e.g., "vrf42" -> 42)
                vrf_name_str = str(interface.vrf.name)
                match = re.match(r"^vrf(\d+)$", vrf_name_str, re.IGNORECASE)

                if not match:
                    logger.warning(
                        f"Interface {interface.name} on device {device.name} has VRF '{vrf_name_str}' "
                        f"that doesn't match expected pattern 'vrf<number>'"
                    )
                    continue

                # Extract table ID and create SONiC VRF name with capital V
                vrf_table_id = int(match.group(1))
                sonic_vrf_name = f"Vrf{vrf_table_id}"

                # Convert NetBox interface name to SONiC format
                sonic_interface_name = convert_netbox_interface_to_sonic(
                    interface, device
                )

                # Add VRF definition if not already present
                if sonic_vrf_name not in vrf_info["vrfs"]:
                    vrf_info["vrfs"][sonic_vrf_name] = {"table_id": vrf_table_id}
                    logger.debug(
                        f"Added VRF definition: {sonic_vrf_name} with table ID {vrf_table_id}"
                    )

                # Add interface to VRF mapping
                vrf_info["interface_vrf_mapping"][sonic_interface_name] = sonic_vrf_name
                logger.debug(
                    f"Mapped interface {sonic_interface_name} to VRF {sonic_vrf_name} "
                    f"for device {device.name}"
                )

            except Exception as e:
                logger.warning(
                    f"Error processing VRF for interface {interface.name} on device {device.name}: {e}"
                )
                continue

    except Exception as e:
        logger.warning(f"Could not get VRF information for device {device.name}: {e}")

    return vrf_info


def _add_vrf_configuration(config, vrf_info, netbox_interfaces):
    """Add VRF configuration to config.

    Args:
        config: Configuration dictionary to update
        vrf_info: VRF information dictionary from _get_vrf_info()
        netbox_interfaces: Dict mapping SONiC names to NetBox interface info
    """
    # Add VRF definitions to config
    for vrf_name, vrf_data in vrf_info["vrfs"].items():
        config["VRF"][vrf_name] = {"vrf_table_id": vrf_data["table_id"]}
        logger.info(f"Added VRF {vrf_name} with table ID {vrf_data['table_id']}")

    # Add VRF assignments to interfaces
    for sonic_interface, vrf_name in vrf_info["interface_vrf_mapping"].items():
        # Check if this is a regular interface
        if sonic_interface in config.get("INTERFACE", {}):
            config["INTERFACE"][sonic_interface]["vrf_name"] = vrf_name
            logger.debug(f"Assigned interface {sonic_interface} to VRF {vrf_name}")

        # Check if this is a port channel interface
        elif sonic_interface in config.get("PORTCHANNEL_INTERFACE", {}):
            config["PORTCHANNEL_INTERFACE"][sonic_interface]["vrf_name"] = vrf_name
            logger.debug(f"Assigned port channel {sonic_interface} to VRF {vrf_name}")
        else:
            logger.debug(
                f"Interface {sonic_interface} has VRF assignment but is not in "
                f"INTERFACE or PORTCHANNEL_INTERFACE config sections"
            )


def _add_portchannel_configuration(config, portchannel_info):
    """Add port channel configuration from NetBox."""
    if portchannel_info["portchannels"]:
        for pc_name, pc_data in portchannel_info["portchannels"].items():
            # Add PORTCHANNEL configuration
            config["PORTCHANNEL"][pc_name] = {
                "admin_status": pc_data["admin_status"],
                "fast_rate": pc_data["fast_rate"],
                "min_links": pc_data["min_links"],
                "mtu": pc_data["mtu"],
            }

            # Add PORTCHANNEL_INTERFACE configuration to enable IPv6 link-local
            config["PORTCHANNEL_INTERFACE"][pc_name] = {
                "ipv6_use_link_local_only": "enable"
            }

            # Add PORTCHANNEL_MEMBER configuration for each member
            for member in pc_data["members"]:
                member_key = f"{pc_name}|{member}"
                config["PORTCHANNEL_MEMBER"][member_key] = {}

            logger.debug(
                f"Added port channel {pc_name} with {len(pc_data['members'])} members"
            )
