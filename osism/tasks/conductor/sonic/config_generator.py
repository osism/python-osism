# SPDX-License-Identifier: Apache-2.0

"""Configuration generation logic for SONiC."""

import copy
import ipaddress
import json
import os
import re
from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import (
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
    get_connected_interfaces,
    detect_breakout_ports,
    detect_port_channels,
    clear_port_config_cache,
)
from .cache import get_cached_device_interfaces

# Global cache for NTP servers to avoid multiple queries
_ntp_servers_cache = None


def natural_sort_key(port_name):
    """Extract numeric part from port name for natural sorting."""
    match = re.search(r"(\d+)", port_name)
    return int(match.group(1)) if match else 0


def generate_sonic_config(device, hwsku, device_as_mapping=None):
    """Generate minimal SONiC config.json for a device.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name
        device_as_mapping: Dict mapping device IDs to pre-calculated AS numbers for spine/superspine groups

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

    # Get breakout port configuration from NetBox
    breakout_info = detect_breakout_ports(device)

    # Get all interfaces from NetBox with their speeds and types
    netbox_interfaces = {}
    try:
        interfaces = get_cached_device_interfaces(device.id)
        for interface in interfaces:
            # Convert NetBox interface name to SONiC format for lookup
            interface_speed = getattr(interface, "speed", None)
            # If speed is not set, try to get it from port type
            if not interface_speed and hasattr(interface, "type") and interface.type:
                interface_speed = get_speed_from_port_type(interface.type.value)
            sonic_name = convert_netbox_interface_to_sonic(interface, device)
            netbox_interfaces[sonic_name] = {
                "speed": interface_speed,
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
    _add_interface_configurations(config, connected_interfaces, portchannel_info)

    # Add BGP configurations
    _add_bgp_configurations(
        config,
        connected_interfaces,
        connected_portchannels,
        portchannel_info,
        device,
        device_as_mapping,
    )

    # Add NTP server configuration (device-specific)
    _add_ntp_configuration(config, device)

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

        # Override with NetBox data if available and hardware config has no speed
        if port_name in netbox_interfaces:
            netbox_speed = netbox_interfaces[port_name]["speed"]
            if netbox_speed and (not port_speed or port_speed == "0"):
                logger.info(
                    f"Using NetBox speed {netbox_speed} for port {port_name} (hardware config had: {port_speed})"
                )
                port_speed = str(netbox_speed)

        if port_name in breakout_info["breakout_ports"]:
            # Get the master port to determine original speed and lanes
            master_port = breakout_info["breakout_ports"][port_name]["master"]

            # Override with individual breakout port speed from NetBox if available
            if port_name in netbox_interfaces and netbox_interfaces[port_name]["speed"]:
                port_speed = str(netbox_interfaces[port_name]["speed"])
                logger.debug(
                    f"Using NetBox speed {port_speed} for breakout port {port_name}"
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
            port_name, interface_speed, is_breakout_port
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

        # Add valid_speeds if available in port_info
        if "valid_speeds" in port_info:
            port_data["valid_speeds"] = port_info["valid_speeds"]

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
    """Calculate individual lane for a breakout port."""
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

        # Calculate which lane this breakout port should use
        port_match = re.match(r"Ethernet(\d+)", port_name)
        if port_match:
            sonic_port_num = int(port_match.group(1))
            master_port_match = re.match(r"Ethernet(\d+)", master_port)
            if master_port_match:
                master_port_num = int(master_port_match.group(1))
                # Calculate subport index (0, 1, 2, 3 for 4x breakout)
                subport_index = sonic_port_num - master_port_num
                if 0 <= subport_index < len(lanes_list):
                    return str(lanes_list[subport_index])
                else:
                    logger.warning(
                        f"Breakout port {port_name}: subport_index {subport_index} out of range for lanes_list {lanes_list}"
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
                port_name, interface_speed, is_breakout=True
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
    # Build a mapping of ports to their tagged VLANs
    port_tagged_vlans = {}
    for vid, members in vlan_info["vlan_members"].items():
        for netbox_interface_name, tagging_mode in members.items():
            # Convert NetBox interface name to SONiC format
            # Try to find speed from netbox_interfaces
            speed = None
            for sonic_name, iface_info in netbox_interfaces.items():
                if iface_info["netbox_name"] == netbox_interface_name:
                    speed = iface_info["speed"]
                    break
            sonic_interface_name = convert_netbox_interface_to_sonic(
                netbox_interface_name, device
            )

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


def _add_interface_configurations(config, connected_interfaces, portchannel_info):
    """Add INTERFACE configuration for connected interfaces."""
    for port_name in config["PORT"]:
        # Check if this port is in the connected interfaces set and not a port channel member
        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            # Add interface to INTERFACE section with ipv6_use_link_local_only enabled
            config["INTERFACE"][port_name] = {"ipv6_use_link_local_only": "enable"}


def _add_bgp_configurations(
    config,
    connected_interfaces,
    connected_portchannels,
    portchannel_info,
    device,
    device_as_mapping=None,
):
    """Add BGP configurations."""
    # Add BGP_NEIGHBOR_AF configuration for connected interfaces
    for port_name in config["PORT"]:
        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            ipv4_key = f"default|{port_name}|ipv4_unicast"
            ipv6_key = f"default|{port_name}|ipv6_unicast"
            config["BGP_NEIGHBOR_AF"][ipv4_key] = {"admin_status": "true"}
            config["BGP_NEIGHBOR_AF"][ipv6_key] = {"admin_status": "true"}

    # Add BGP_NEIGHBOR_AF configuration for connected port channels
    for pc_name in connected_portchannels:
        ipv4_key = f"default|{pc_name}|ipv4_unicast"
        ipv6_key = f"default|{pc_name}|ipv6_unicast"
        config["BGP_NEIGHBOR_AF"][ipv4_key] = {"admin_status": "true"}
        config["BGP_NEIGHBOR_AF"][ipv6_key] = {"admin_status": "true"}

    # Add BGP_NEIGHBOR configuration for connected interfaces
    for port_name in config["PORT"]:
        if (
            port_name in connected_interfaces
            and port_name not in portchannel_info["member_mapping"]
        ):
            neighbor_key = f"default|{port_name}"

            # Determine peer_type based on connected device AS
            peer_type = "external"  # Default
            connected_device = _get_connected_device_for_interface(device, port_name)
            if connected_device:
                peer_type = _determine_peer_type(
                    device, connected_device, device_as_mapping
                )

            config["BGP_NEIGHBOR"][neighbor_key] = {
                "peer_type": peer_type,
                "v6only": "true",
            }

    # Add BGP_NEIGHBOR configuration for connected port channels
    for pc_name in connected_portchannels:
        neighbor_key = f"default|{pc_name}"

        # Determine peer_type based on connected device AS
        peer_type = "external"  # Default
        connected_device = _get_connected_device_for_interface(device, pc_name)
        if connected_device:
            peer_type = _determine_peer_type(
                device, connected_device, device_as_mapping
            )

        config["BGP_NEIGHBOR"][neighbor_key] = {
            "peer_type": peer_type,
            "v6only": "true",
        }

    # Add additional BGP_NEIGHBOR configuration using Loopback0 IP addresses
    _add_loopback_bgp_neighbors(
        config, device, portchannel_info, connected_interfaces, device_as_mapping
    )


def _get_connected_device_for_interface(device, interface_name):
    """Get the connected device for a given interface name.

    Args:
        device: NetBox device object
        interface_name: SONiC interface name (e.g., "Ethernet0")

    Returns:
        NetBox device object or None if not found
    """
    try:
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Convert NetBox interface name to SONiC format
            interface_speed = getattr(interface, "speed", None)
            if not interface_speed and hasattr(interface, "type") and interface.type:
                interface_speed = get_speed_from_port_type(interface.type.value)
            sonic_name = convert_netbox_interface_to_sonic(interface, device)

            if sonic_name == interface_name:
                # Check if interface has connected_endpoints
                if (
                    hasattr(interface, "connected_endpoints")
                    and interface.connected_endpoints
                ):
                    if not getattr(interface, "connected_endpoints_reachable", False):
                        continue

                    for endpoint in interface.connected_endpoints:
                        if (
                            hasattr(endpoint, "device")
                            and endpoint.device.id != device.id
                        ):
                            return endpoint.device

                # Fallback to cable-based lookup
                if hasattr(interface, "cable") and interface.cable:
                    cable = interface.cable

                    # Try modern cable API
                    if hasattr(cable, "a_terminations") and hasattr(
                        cable, "b_terminations"
                    ):
                        for termination in list(cable.a_terminations) + list(
                            cable.b_terminations
                        ):
                            if (
                                hasattr(termination, "device")
                                and termination.device.id != device.id
                            ):
                                return termination.device

                    # Try legacy cable API
                    elif hasattr(cable, "termination_a") and hasattr(
                        cable, "termination_b"
                    ):
                        if cable.termination_a.device.id != device.id:
                            return cable.termination_a.device
                        elif cable.termination_b.device.id != device.id:
                            return cable.termination_b.device
                break

    except Exception as e:
        logger.debug(
            f"Could not find connected device for interface {interface_name}: {e}"
        )

    return None


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


def _add_loopback_bgp_neighbors(
    config, device, portchannel_info, connected_interfaces, device_as_mapping=None
):
    """Add BGP_NEIGHBOR configuration using Loopback0 IP addresses from connected devices."""
    try:
        # Get all interfaces for the device to find connected devices (using cache)
        interfaces = get_cached_device_interfaces(device.id)

        for interface in interfaces:
            # Skip management-only interfaces
            if hasattr(interface, "mgmt_only") and interface.mgmt_only:
                continue

            # Check if interface is connected via cable
            if hasattr(interface, "cable") and interface.cable:
                # Convert NetBox interface name to SONiC format to check if it's in our PORT config
                interface_speed = getattr(interface, "speed", None)
                # If speed is not set, try to get it from port type
                if (
                    not interface_speed
                    and hasattr(interface, "type")
                    and interface.type
                ):
                    interface_speed = get_speed_from_port_type(interface.type.value)
                sonic_interface_name = convert_netbox_interface_to_sonic(
                    interface, device
                )

                # Only process if this interface is in our PORT configuration and not a port channel member
                if (
                    sonic_interface_name in config["PORT"]
                    and sonic_interface_name in connected_interfaces
                    and sonic_interface_name not in portchannel_info["member_mapping"]
                ):
                    try:
                        # Get the cable and find the connected device
                        cable = interface.cable
                        connected_device = None

                        # Try to get cable terminations (modern NetBox API)
                        if hasattr(cable, "a_terminations") and hasattr(
                            cable, "b_terminations"
                        ):
                            for termination in list(cable.a_terminations) + list(
                                cable.b_terminations
                            ):
                                # Termination is the interface object directly
                                if (
                                    hasattr(termination, "device")
                                    and termination.device.id != device.id
                                ):
                                    connected_device = termination.device
                                    break

                        # Fallback: try legacy cable API structure
                        if not connected_device:
                            if hasattr(cable, "termination_a") and hasattr(
                                cable, "termination_b"
                            ):
                                if cable.termination_a.device.id != device.id:
                                    connected_device = cable.termination_a.device
                                elif cable.termination_b.device.id != device.id:
                                    connected_device = cable.termination_b.device

                        if connected_device:
                            # Check if connected device has the required tag
                            has_osism_tag = False
                            if connected_device.tags:
                                has_osism_tag = any(
                                    tag.slug == "managed-by-osism"
                                    for tag in connected_device.tags
                                )

                            if has_osism_tag:
                                # Get Loopback0 IP addresses from the connected device
                                connected_device_interfaces = (
                                    utils.nb.dcim.interfaces.filter(
                                        device_id=connected_device.id
                                    )
                                )

                                for conn_interface in connected_device_interfaces:
                                    # Look for Loopback0 interface
                                    if conn_interface.name == "Loopback0":
                                        # Get IP addresses assigned to this Loopback0 interface
                                        ip_addresses = (
                                            utils.nb.ipam.ip_addresses.filter(
                                                assigned_object_id=conn_interface.id,
                                            )
                                        )

                                        for ip_addr in ip_addresses:
                                            if ip_addr.address:
                                                # Extract just the IP address without prefix
                                                ip_only = ip_addr.address.split("/")[0]
                                                neighbor_key = f"default|{ip_only}"

                                                # Determine peer_type based on AS comparison
                                                peer_type = _determine_peer_type(
                                                    device,
                                                    connected_device,
                                                    device_as_mapping,
                                                )

                                                config["BGP_NEIGHBOR"][neighbor_key] = {
                                                    "peer_type": peer_type
                                                }
                                        break
                            else:
                                logger.debug(
                                    f"Skipping BGP neighbor for device {connected_device.name}: missing 'managed-by-osism' tag"
                                )

                    except Exception as e:
                        logger.warning(
                            f"Could not get connected device for interface {interface.name}: {e}"
                        )

    except Exception as e:
        logger.warning(f"Could not process BGP neighbors for device {device.name}: {e}")


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
    """Add NTP_SERVER configuration to device config."""
    try:
        ntp_servers = _get_ntp_servers()

        # Add NTP servers to this device's configuration
        for ip, ntp_config in ntp_servers.items():
            config["NTP_SERVER"][ip] = copy.deepcopy(ntp_config)

        if ntp_servers:
            logger.debug(
                f"Added {len(ntp_servers)} NTP servers to device {device.name}"
            )
        else:
            logger.debug(f"No NTP servers found for device {device.name}")

    except Exception as e:
        logger.warning(f"Could not add NTP configuration to device {device.name}: {e}")


def clear_ntp_cache():
    """Clear the NTP servers cache. Should be called at the start of sync_sonic."""
    global _ntp_servers_cache
    _ntp_servers_cache = None
    logger.debug("Cleared NTP servers cache")


def clear_all_caches():
    """Clear all caches in config_generator module."""
    clear_ntp_cache()
    clear_port_config_cache()
    logger.debug("Cleared all config_generator caches")


def _add_vlan_configuration(config, vlan_info, netbox_interfaces, device):
    """Add VLAN configuration from NetBox."""
    # Add VLAN configuration
    for vid, vlan_data in vlan_info["vlans"].items():
        vlan_name = f"Vlan{vid}"

        # Get member ports for this VLAN and convert interface names
        members = []
        if vid in vlan_info["vlan_members"]:
            for netbox_interface_name in vlan_info["vlan_members"][vid].keys():
                # Convert NetBox interface name to SONiC format
                # Try to find speed from netbox_interfaces
                speed = None
                for sonic_name, iface_info in netbox_interfaces.items():
                    if iface_info["netbox_name"] == netbox_interface_name:
                        speed = iface_info["speed"]
                        break
                sonic_interface_name = convert_netbox_interface_to_sonic(
                    netbox_interface_name, device
                )
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
            # Convert NetBox interface name to SONiC format
            # Try to find speed from netbox_interfaces
            speed = None
            for sonic_name, iface_info in netbox_interfaces.items():
                if iface_info["netbox_name"] == netbox_interface_name:
                    speed = iface_info["speed"]
                    break
            sonic_interface_name = convert_netbox_interface_to_sonic(
                netbox_interface_name, device
            )
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
