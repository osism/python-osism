# SPDX-License-Identifier: Apache-2.0

"""Interface conversion and port detection functions for SONiC configuration."""

import os
import re
from loguru import logger

from osism import utils
from .connections import is_interface_connected
from .constants import PORT_TYPE_TO_SPEED_MAP, HIGH_SPEED_PORTS


def get_speed_from_port_type(port_type):
    """Get speed from port type when speed is not provided.

    Args:
        port_type: NetBox interface type value (e.g., "10gbase-x-sfpp", "100gbase-x-qsfp28")

    Returns:
        int: Speed in Mbps, or None if port type is not recognized
    """
    if not port_type:
        return None

    # Convert to lowercase for case-insensitive matching
    port_type_lower = str(port_type).lower()

    # Try to get speed from mapping
    speed = PORT_TYPE_TO_SPEED_MAP.get(port_type_lower)

    if speed:
        logger.debug(f"Resolved port type '{port_type}' to speed {speed} Mbps")
    else:
        logger.warning(f"Unknown port type '{port_type}', unable to determine speed")

    return speed


def convert_netbox_interface_to_sonic(interface_name, interface_speed=None):
    """Convert NetBox interface name to SONiC interface name.

    Args:
        interface_name: NetBox interface name (e.g., "Eth1/1", "Eth1/2")
        interface_speed: Interface speed in Mbps (optional, for future high-speed ports)

    Returns:
        str: SONiC interface name (e.g., "Ethernet0", "Ethernet4")

    Examples:
        - 100G ports: Eth1/1 -> Ethernet0, Eth1/2 -> Ethernet4, Eth1/3 -> Ethernet8
        - Other speeds: Eth1/1 -> Ethernet0, Eth1/2 -> Ethernet1, Eth1/3 -> Ethernet2
    """
    # Check if this is already in SONiC format (Ethernet*)
    if interface_name.startswith("Ethernet"):
        return interface_name

    # Extract port number from NetBox format (Eth1/1, Eth1/2, etc.)
    match = re.match(r"Eth(\d+)/(\d+)", interface_name)
    if not match:
        # If it doesn't match expected pattern, return as-is
        return interface_name

    module = int(match.group(1))
    port = int(match.group(2))

    # Calculate base port number (assuming module 1 starts at port 1)
    port_number = port - 1  # Convert to 0-based indexing

    # Determine speed category and multiplier
    if interface_speed and interface_speed in HIGH_SPEED_PORTS:
        # High-speed ports use 4x multiplier (lanes)
        multiplier = 4
    else:
        # Default for 1G, 10G, 25G ports - sequential numbering
        multiplier = 1

    sonic_port_number = port_number * multiplier

    return f"Ethernet{sonic_port_number}"


def convert_sonic_interface_to_alias(
    sonic_interface_name, interface_speed=None, is_breakout=False
):
    """Convert SONiC interface name to NetBox-style alias.

    Args:
        sonic_interface_name: SONiC interface name (e.g., "Ethernet0", "Ethernet4")
        interface_speed: Interface speed in Mbps (optional, for speed-based calculation)
        is_breakout: Whether this is a breakout port (adds subport notation)

    Returns:
        str: NetBox-style alias (e.g., "Eth1/1", "Eth1/2" or "Eth1/1/1", "Eth1/1/2" for breakout)

    Examples:
        - Regular 100G ports: Ethernet0 -> Eth1/1, Ethernet4 -> Eth1/2, Ethernet8 -> Eth1/3
        - Regular other speeds: Ethernet0 -> Eth1/1, Ethernet1 -> Eth1/2, Ethernet2 -> Eth1/3
        - Breakout ports: Ethernet0 -> Eth1/1/1, Ethernet1 -> Eth1/1/2, Ethernet2 -> Eth1/1/3, Ethernet3 -> Eth1/1/4
    """
    # Extract port number from SONiC format (Ethernet0, Ethernet4, etc.)
    match = re.match(r"Ethernet(\d+)", sonic_interface_name)
    if not match:
        # If it doesn't match expected pattern, return as-is
        return sonic_interface_name

    sonic_port_number = int(match.group(1))

    if is_breakout:
        # For breakout ports: Ethernet0 -> Eth1/1/1, Ethernet1 -> Eth1/1/2, etc.
        # Calculate base port (master port) and subport number
        base_port = (sonic_port_number // 4) * 4  # Get base port (0, 4, 8, 12, ...)
        subport = (sonic_port_number % 4) + 1  # Get subport number (1, 2, 3, 4)

        # Calculate physical port number for the base port
        physical_port = (base_port // 4) + 1  # Convert to 1-based indexing

        # Assume module 1 for now - could be extended for multi-module systems
        module = 1

        return f"Eth{module}/{physical_port}/{subport}"
    else:
        # For regular ports: use speed-based calculation
        # Determine speed category and multiplier
        if interface_speed and interface_speed in HIGH_SPEED_PORTS:
            # High-speed ports use 4x multiplier (lanes)
            multiplier = 4
        else:
            # Default for 1G, 10G, 25G ports - sequential numbering
            multiplier = 1

        # Calculate physical port number
        physical_port = (
            sonic_port_number // multiplier
        ) + 1  # Convert to 1-based indexing

        # Assume module 1 for now - could be extended for multi-module systems
        module = 1

        return f"Eth{module}/{physical_port}"


def get_port_config(hwsku):
    """Get port configuration for a given HWSKU.

    Args:
        hwsku: Hardware SKU name (e.g., 'Accton-AS5835-54T')

    Returns:
        dict: Port configuration with port names as keys and their properties as values
              Example: {'Ethernet0': {'lanes': '2', 'alias': 'tenGigE1', 'index': '1', 'speed': '10000', 'valid_speeds': '10000,25000'}}
    """
    port_config = {}
    config_path = f"/etc/sonic/port_config/{hwsku}.ini"

    if not os.path.exists(config_path):
        logger.error(f"Port config file not found: {config_path}")
        return port_config

    try:
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                parts = line.split()
                if len(parts) >= 5:
                    port_name = parts[0]
                    port_config[port_name] = {
                        "lanes": parts[1],
                        "alias": parts[2],
                        "index": parts[3],
                        "speed": parts[4],
                    }
                    # Check for optional valid_speeds column (6th column)
                    if len(parts) >= 6:
                        port_config[port_name]["valid_speeds"] = parts[5]
    except Exception as e:
        logger.error(f"Error parsing port config file {config_path}: {e}")

    return port_config


def get_connected_interfaces(device, portchannel_info=None):
    """Get list of interface names that are connected to other devices.

    Args:
        device: NetBox device object
        portchannel_info: Optional port channel info dict from detect_port_channels

    Returns:
        tuple: (set of connected interfaces, set of connected port channels)
    """
    connected_interfaces = set()
    connected_portchannels = set()

    try:
        # Get all interfaces for the device
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)

        for interface in interfaces:
            # Check if interface is connected using the centralized function
            if is_interface_connected(interface):
                # Convert NetBox interface name to SONiC format
                interface_speed = getattr(interface, "speed", None)
                # If speed is not set, try to get it from port type
                if (
                    not interface_speed
                    and hasattr(interface, "type")
                    and interface.type
                ):
                    interface_speed = get_speed_from_port_type(interface.type.value)
                sonic_interface_name = convert_netbox_interface_to_sonic(
                    interface.name, interface_speed
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


def detect_breakout_ports(device):
    """Detect breakout ports from NetBox device interfaces.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary with breakout port information
              {
                  'breakout_cfgs': {port_name: {'brkout_mode': mode, 'port': port}},
                  'breakout_ports': {port_name: {'master': master_port}}
              }
    """
    breakout_cfgs = {}
    breakout_ports = {}

    try:
        # Get all interfaces for the device
        interfaces = list(utils.nb.dcim.interfaces.filter(device_id=device.id))

        # Group interfaces by potential breakout groups
        # First, handle SONiC format (Ethernet0, Ethernet1, Ethernet2, Ethernet3)
        sonic_groups = {}
        # Second, handle NetBox format (Eth1/1/1, Eth1/1/2, Eth1/1/3, Eth1/1/4)
        netbox_groups = {}

        for interface in interfaces:
            interface_speed = getattr(interface, "speed", None)
            # If speed is not set, try to get it from port type
            if not interface_speed and hasattr(interface, "type") and interface.type:
                interface_speed = get_speed_from_port_type(interface.type.value)

            # Skip if not high-speed port (100G, 400G, 800G)
            if not interface_speed or interface_speed not in HIGH_SPEED_PORTS:
                continue

            # Check for SONiC format breakout (Ethernet0, Ethernet1, Ethernet2, Ethernet3)
            sonic_match = re.match(r"Ethernet(\d+)", interface.name)
            if sonic_match:
                port_num = int(sonic_match.group(1))
                # Group by base port (0, 4, 8, 12, ...)
                base_port = (port_num // 4) * 4
                if base_port not in sonic_groups:
                    sonic_groups[base_port] = []
                sonic_groups[base_port].append((port_num, interface))

            # Check for NetBox format breakout (Eth1/1/1, Eth1/1/2, Eth1/1/3, Eth1/1/4)
            netbox_match = re.match(r"Eth(\d+)/(\d+)/(\d+)", interface.name)
            if netbox_match:
                module = int(netbox_match.group(1))
                port = int(netbox_match.group(2))
                subport = int(netbox_match.group(3))
                group_key = f"{module}/{port}"
                if group_key not in netbox_groups:
                    netbox_groups[group_key] = []
                netbox_groups[group_key].append((subport, interface))

        # Process SONiC format breakout groups
        for base_port, port_list in sonic_groups.items():
            # Check if we have exactly 4 consecutive ports
            if len(port_list) == 4:
                port_list.sort(key=lambda x: x[0])  # Sort by port number
                expected_ports = [base_port + i for i in range(4)]
                actual_ports = [port[0] for port in port_list]

                if actual_ports == expected_ports:
                    # This is a valid breakout group
                    master_port = f"Ethernet{base_port}"

                    # Calculate breakout mode based on speed
                    interface_speed = getattr(port_list[0][1], "speed", None)
                    if interface_speed == 100000:  # 100G -> 4x25G
                        brkout_mode = "4x25G"
                    elif interface_speed == 200000:  # 200G -> 4x50G
                        brkout_mode = "4x50G"
                    elif interface_speed == 400000:  # 400G -> 4x100G
                        brkout_mode = "4x100G"
                    elif interface_speed == 800000:  # 800G -> 4x200G
                        brkout_mode = "4x200G"
                    else:
                        continue  # Skip unsupported speeds

                    # Add breakout config for master port
                    physical_port_num = (base_port // 4) + 1
                    breakout_cfgs[master_port] = {
                        "breakout_owner": "MANUAL",
                        "brkout_mode": brkout_mode,
                        "port": f"1/{physical_port_num}",
                    }

                    # Add all ports to breakout_ports
                    for port_num, interface in port_list:
                        port_name = f"Ethernet{port_num}"
                        breakout_ports[port_name] = {"master": master_port}

        # Process NetBox format breakout groups
        for group_key, port_list in netbox_groups.items():
            # Check if we have exactly 4 subports
            if len(port_list) == 4:
                port_list.sort(key=lambda x: x[0])  # Sort by subport number
                expected_subports = [1, 2, 3, 4]
                actual_subports = [port[0] for port in port_list]

                if actual_subports == expected_subports:
                    # This is a valid breakout group - convert to SONiC format
                    module, port = group_key.split("/")

                    # Calculate base SONiC port number (assuming 4x multiplier for high-speed)
                    base_sonic_port = (int(port) - 1) * 4
                    master_port = f"Ethernet{base_sonic_port}"

                    # Calculate breakout mode based on speed
                    interface_speed = getattr(port_list[0][1], "speed", None)
                    if interface_speed == 100000:  # 100G -> 4x25G
                        brkout_mode = "4x25G"
                    elif interface_speed == 200000:  # 200G -> 4x50G
                        brkout_mode = "4x50G"
                    elif interface_speed == 400000:  # 400G -> 4x100G
                        brkout_mode = "4x100G"
                    elif interface_speed == 800000:  # 800G -> 4x200G
                        brkout_mode = "4x200G"
                    else:
                        continue  # Skip unsupported speeds

                    # Add breakout config for master port
                    breakout_cfgs[master_port] = {
                        "breakout_owner": "MANUAL",
                        "brkout_mode": brkout_mode,
                        "port": f"{module}/{port}",
                    }

                    # Add all subports to breakout_ports (converted to SONiC format)
                    for subport, interface in port_list:
                        sonic_port_num = base_sonic_port + (subport - 1)
                        port_name = f"Ethernet{sonic_port_num}"
                        breakout_ports[port_name] = {"master": master_port}

    except Exception as e:
        logger.warning(f"Could not detect breakout ports for device {device.name}: {e}")

    return {"breakout_cfgs": breakout_cfgs, "breakout_ports": breakout_ports}


def detect_port_channels(device):
    """Detect port channels (LAGs) from NetBox device interfaces.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary with port channel information
              {
                  'portchannels': {
                      'PortChannel1': {
                          'members': ['Ethernet120', 'Ethernet124'],
                          'admin_status': 'up',
                          'fast_rate': 'false',
                          'min_links': '1',
                          'mtu': '9100'
                      }
                  },
                  'member_mapping': {
                      'Ethernet120': 'PortChannel1',
                      'Ethernet124': 'PortChannel1'
                  }
              }
    """
    portchannels = {}
    member_mapping = {}

    try:
        # Get all interfaces for the device and convert to list for multiple iterations
        interfaces = list(utils.nb.dcim.interfaces.filter(device_id=device.id))

        # First pass: find LAG interfaces
        lag_interfaces = []
        for interface in interfaces:
            # Check if this is a LAG interface
            if hasattr(interface, "type") and interface.type:
                if interface.type.value == "lag":
                    lag_interfaces.append(interface)
                    logger.debug(f"Found LAG interface: {interface.name}")

        # Second pass: map members to LAGs
        for interface in interfaces:
            # Check if this interface has a LAG parent
            if hasattr(interface, "lag") and interface.lag:
                lag_parent = interface.lag

                # Convert NetBox interface name to SONiC format
                interface_speed = getattr(interface, "speed", None)
                if (
                    not interface_speed
                    and hasattr(interface, "type")
                    and interface.type
                ):
                    interface_speed = get_speed_from_port_type(interface.type.value)

                sonic_interface_name = convert_netbox_interface_to_sonic(
                    interface.name, interface_speed
                )

                # Extract port channel number from LAG name
                # Common patterns: PortChannel1, Port-Channel1, LAG1, ae1, bond1
                pc_number = None
                if re.match(r"(?i)portchannel(\d+)", lag_parent.name):
                    match = re.match(r"(?i)portchannel(\d+)", lag_parent.name)
                    pc_number = match.group(1)
                elif re.match(r"(?i)port-channel(\d+)", lag_parent.name):
                    match = re.match(r"(?i)port-channel(\d+)", lag_parent.name)
                    pc_number = match.group(1)
                elif re.match(r"(?i)lag(\d+)", lag_parent.name):
                    match = re.match(r"(?i)lag(\d+)", lag_parent.name)
                    pc_number = match.group(1)
                elif re.match(r"(?i)ae(\d+)", lag_parent.name):
                    match = re.match(r"(?i)ae(\d+)", lag_parent.name)
                    pc_number = match.group(1)
                elif re.match(r"(?i)bond(\d+)", lag_parent.name):
                    match = re.match(r"(?i)bond(\d+)", lag_parent.name)
                    pc_number = match.group(1)
                else:
                    # Try to extract any number from the name
                    numbers = re.findall(r"\d+", lag_parent.name)
                    if numbers:
                        pc_number = numbers[0]
                    else:
                        # Generate a number based on the LAG interface order
                        pc_number = (
                            str(lag_interfaces.index(lag_parent) + 1)
                            if lag_parent in lag_interfaces
                            else "1"
                        )

                portchannel_name = f"PortChannel{pc_number}"

                # Add member to mapping
                member_mapping[sonic_interface_name] = portchannel_name

                # Initialize port channel if not exists
                if portchannel_name not in portchannels:
                    portchannels[portchannel_name] = {
                        "members": [],
                        "admin_status": "up",
                        "fast_rate": "false",
                        "min_links": "1",
                        "mtu": "9100",
                    }

                # Add member to port channel
                if (
                    sonic_interface_name
                    not in portchannels[portchannel_name]["members"]
                ):
                    portchannels[portchannel_name]["members"].append(
                        sonic_interface_name
                    )

                logger.debug(
                    f"Added interface {sonic_interface_name} to {portchannel_name}"
                )

        # Sort members in each port channel for consistent ordering
        for pc_name in portchannels:
            portchannels[pc_name]["members"].sort(
                key=lambda x: (
                    int(re.search(r"\d+", x).group()) if re.search(r"\d+", x) else 0
                )
            )

    except Exception as e:
        logger.warning(f"Could not detect port channels for device {device.name}: {e}")

    return {"portchannels": portchannels, "member_mapping": member_mapping}
