# SPDX-License-Identifier: Apache-2.0

import ipaddress
import json
import os
import re
from loguru import logger

from osism import utils
from osism import settings
from osism.tasks.conductor.netbox import (
    get_device_loopbacks,
    get_device_oob_ip,
    get_device_vlans,
    get_nb_device_query_list_sonic,
)

# Default AS prefix for local ASN calculation
DEFAULT_LOCAL_AS_PREFIX = 4200

# Port type to speed mapping (in Mbps)
PORT_TYPE_TO_SPEED_MAP = {
    # RJ45/BASE-T Types
    "100base-tx": 100,  # 100Mbps RJ45
    "1000base-t": 1000,  # 1G RJ45
    "2.5gbase-t": 2500,  # 2.5G RJ45
    "5gbase-t": 5000,  # 5G RJ45
    "10gbase-t": 10000,  # 10G RJ45
    # CX4
    "10gbase-cx4": 10000,  # 10G CX4
    # 1G Optical
    "1000base-x-gbic": 1000,  # 1G GBIC
    "1000base-x-sfp": 1000,  # 1G SFP
    # 10G Optical
    "10gbase-x-sfpp": 10000,  # 10G SFP+
    "10gbase-x-xfp": 10000,  # 10G XFP
    "10gbase-x-xenpak": 10000,  # 10G XENPAK
    "10gbase-x-x2": 10000,  # 10G X2
    # 25G Optical
    "25gbase-x-sfp28": 25000,  # 25G SFP28
    # 40G Optical
    "40gbase-x-qsfpp": 40000,  # 40G QSFP+
    # 50G Optical
    "50gbase-x-sfp28": 50000,  # 50G SFP28
    # 100G Optical
    "100gbase-x-cfp": 100000,  # 100G CFP
    "100gbase-x-cfp2": 100000,  # 100G CFP2
    "100gbase-x-cfp4": 100000,  # 100G CFP4
    "100gbase-x-cpak": 100000,  # 100G CPAK
    "100gbase-x-qsfp28": 100000,  # 100G QSFP28
    # 200G Optical
    "200gbase-x-cfp2": 200000,  # 200G CFP2
    "200gbase-x-qsfp56": 200000,  # 200G QSFP56
    # 400G Optical
    "400gbase-x-qsfpdd": 400000,  # 400G QSFP-DD
    "400gbase-x-osfp": 400000,  # 400G OSFP
    # Virtual interface
    "virtual": 0,  # Virtual interface (no physical speed)
}


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
    high_speed_ports = {
        100000,
        200000,
        400000,
        800000,
    }  # 100G, 200G, 400G, 800G in Mbps

    if interface_speed and interface_speed in high_speed_ports:
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
        high_speed_ports = {
            100000,
            200000,
            400000,
            800000,
        }  # 100G, 200G, 400G, 800G in Mbps

        if interface_speed and interface_speed in high_speed_ports:
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


# Constants
DEFAULT_SONIC_ROLES = [
    "accessleaf",
    "borderleaf",
    "computeleaf",
    "dataleaf",
    "leaf",
    "serviceleaf",
    "spine",
    "storageleaf",
    "switch",
    "transferleaf",
]

DEFAULT_SONIC_VERSION = "4.5.0"


def get_device_platform(device, hwsku):
    """Get platform for device from sonic_parameters or generate from HWSKU.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name

    Returns:
        str: Platform string (e.g., 'x86_64-accton_as7326_56x-r0')
    """
    platform = None
    if (
        hasattr(device, "custom_fields")
        and "sonic_parameters" in device.custom_fields
        and device.custom_fields["sonic_parameters"]
        and "platform" in device.custom_fields["sonic_parameters"]
    ):
        platform = device.custom_fields["sonic_parameters"]["platform"]

    if not platform:
        # Generate platform from hwsku: x86_64-{hwsku_lower_with_underscores}-r0
        hwsku_formatted = hwsku.lower().replace("-", "_")
        platform = f"x86_64-{hwsku_formatted}-r0"

    return platform


def get_device_hostname(device):
    """Get hostname for device from inventory_hostname custom field or device name.

    Args:
        device: NetBox device object

    Returns:
        str: Hostname for the device
    """
    hostname = device.name
    if (
        hasattr(device, "custom_fields")
        and "inventory_hostname" in device.custom_fields
        and device.custom_fields["inventory_hostname"]
    ):
        hostname = device.custom_fields["inventory_hostname"]

    return hostname


def get_device_mac_address(device):
    """Get MAC address from device's management interface.

    Args:
        device: NetBox device object

    Returns:
        str: MAC address or default '00:00:00:00:00:00'
    """
    mac_address = "00:00:00:00:00:00"  # Default MAC
    try:
        # Get all interfaces for the device
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)
        for interface in interfaces:
            # Check if interface is marked as management only
            if interface.mgmt_only:
                if interface.mac_address:
                    mac_address = interface.mac_address
                    logger.debug(
                        f"Using MAC address {mac_address} from management interface {interface.name}"
                    )
                    break
    except Exception as e:
        logger.warning(f"Could not get MAC address for device {device.name}: {e}")

    return mac_address


def get_device_version(device):
    """Get SONiC version for device from sonic_parameters or use default.

    Args:
        device: NetBox device object

    Returns:
        str: SONiC version formatted for VERSION field (e.g., 'version_4_5_0')
    """
    version = DEFAULT_SONIC_VERSION
    if (
        hasattr(device, "custom_fields")
        and "sonic_parameters" in device.custom_fields
        and device.custom_fields["sonic_parameters"]
        and "version" in device.custom_fields["sonic_parameters"]
    ):
        version = device.custom_fields["sonic_parameters"]["version"]

    # Format version for VERSION field: "4.5.0" -> "version_4_5_0"
    version_formatted = f"version_{version.replace('.', '_')}"
    return version_formatted


def get_port_config(hwsku):
    """Get port configuration for a given HWSKU.

    Args:
        hwsku: Hardware SKU name (e.g., 'Accton-AS5835-54T')

    Returns:
        dict: Port configuration with port names as keys and their properties as values
              Example: {'Ethernet0': {'lanes': '2', 'alias': 'tenGigE1', 'index': '1', 'speed': '10000'}}
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
    except Exception as e:
        logger.error(f"Error parsing port config file {config_path}: {e}")

    return port_config


def save_config_to_netbox(device, config):
    """Save SONiC configuration to NetBox device config context.

    Args:
        device: NetBox device object
        config: SONiC configuration dictionary
    """
    try:
        # Get existing config contexts for the device
        config_contexts = utils.nb.extras.config_contexts.filter(device_id=device.id)

        # Look for existing SONiC config context
        sonic_context = None
        for context in config_contexts:
            if context.name == f"SONiC Config - {device.name}":
                sonic_context = context
                break

        # Prepare config context data
        context_data = {
            "name": f"SONiC Config - {device.name}",
            "weight": 1000,
            "data": {"sonic_config": config},
            "is_active": True,
        }

        if sonic_context:
            # Update existing config context
            sonic_context.data = {"sonic_config": config}
            sonic_context.save()
            logger.info(f"Updated SONiC config context for device {device.name}")
        else:
            # Create new config context
            new_context = utils.nb.extras.config_contexts.create(**context_data)
            # Assign the config context to the device
            new_context.devices = [device.id]
            new_context.save()
            logger.info(f"Created new SONiC config context for device {device.name}")

    except Exception as e:
        logger.error(f"Failed to save config context for device {device.name}: {e}")


def export_config_to_file(device, config):
    """Export SONiC configuration to local file.

    Args:
        device: NetBox device object
        config: SONiC configuration dictionary
    """
    try:
        # Get configuration from settings
        export_dir = settings.SONIC_EXPORT_DIR
        prefix = settings.SONIC_EXPORT_PREFIX
        suffix = settings.SONIC_EXPORT_SUFFIX

        # Create export directory if it doesn't exist
        os.makedirs(export_dir, exist_ok=True)

        # Get device hostname from inventory_hostname custom field or device name
        hostname = get_device_hostname(device)

        # Generate filename: prefix + hostname + suffix
        filename = f"{prefix}{hostname}{suffix}"
        filepath = os.path.join(export_dir, filename)

        # Export configuration to JSON file
        with open(filepath, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Exported SONiC config for device {device.name} to {filepath}")

    except Exception as e:
        logger.error(f"Failed to export config for device {device.name}: {e}")


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
            if not interface_speed or interface_speed not in {
                100000,
                200000,
                400000,
                800000,
            }:
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


def get_connected_interfaces(device):
    """Get list of interface names that are connected to other devices.

    Args:
        device: NetBox device object

    Returns:
        set: Set of interface names that are connected
    """
    connected_interfaces = set()

    try:
        # Get all interfaces for the device
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)

        for interface in interfaces:
            # Skip management-only interfaces
            if hasattr(interface, "mgmt_only") and interface.mgmt_only:
                continue

            # Check if interface is connected via cable
            if hasattr(interface, "cable") and interface.cable:
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
            # Alternative check using is_connected property if available
            elif hasattr(interface, "is_connected") and interface.is_connected:
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

    except Exception as e:
        logger.warning(
            f"Could not get interface connections for device {device.name}: {e}"
        )

    return connected_interfaces


def generate_sonic_config(device, hwsku):
    """Generate minimal SONiC config.json for a device.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name

    Returns:
        dict: Minimal SONiC configuration dictionary
    """
    # Get port configuration for the HWSKU
    port_config = get_port_config(hwsku)

    # Get connected interfaces to determine admin_status
    connected_interfaces = get_connected_interfaces(device)

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
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)
        for interface in interfaces:
            # Convert NetBox interface name to SONiC format for lookup
            interface_speed = getattr(interface, "speed", None)
            # If speed is not set, try to get it from port type
            if not interface_speed and hasattr(interface, "type") and interface.type:
                interface_speed = get_speed_from_port_type(interface.type.value)
            sonic_name = convert_netbox_interface_to_sonic(
                interface.name, interface_speed
            )
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
    version = get_device_version(device)

    # Try to load base configuration from /etc/sonic/config_db.json
    base_config_path = "/etc/sonic/config_db.json"
    config = {}

    try:
        if os.path.exists(base_config_path):
            with open(base_config_path, "r") as f:
                config = json.load(f)
                logger.info(f"Loaded base configuration from {base_config_path}")
    except Exception as e:
        logger.warning(
            f"Could not load base configuration from {base_config_path}: {e}"
        )

    # Ensure all required sections exist in the config
    required_sections = {
        "DEVICE_METADATA": {},
        "PORT": {},
        "INTERFACE": {},
        "VLAN": {},
        "VLAN_MEMBER": {},
        "VLAN_INTERFACE": {},
        "MGMT_INTERFACE": {},
        "LOOPBACK": {},
        "LOOPBACK_INTERFACE": {},
        "BREAKOUT_CFG": {},
        "BREAKOUT_PORTS": {},
        "BGP_GLOBALS": {},
        "BGP_NEIGHBOR": {},
        "BGP_NEIGHBOR_AF": {},
        "BGP_GLOBALS_AF_NETWORK": {},
        "NTP_SERVER": {},
        "VERSIONS": {},
    }

    for section, default_value in required_sections.items():
        if section not in config:
            config[section] = default_value

    # Update DEVICE_METADATA with NetBox information
    if "localhost" not in config["DEVICE_METADATA"]:
        config["DEVICE_METADATA"]["localhost"] = {}

    config["DEVICE_METADATA"]["localhost"].update(
        {
            "hostname": hostname,
            "hwsku": hwsku,
            "platform": platform,
            "mac": mac_address,
            "type": "LeafRouter",
        }
    )

    # Update VERSIONS if not present
    if "DATABASE" not in config["VERSIONS"]:
        config["VERSIONS"]["DATABASE"] = {"VERSION": version}

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
                local_asn = calculate_local_asn_from_ipv4(primary_ip)
                config["BGP_GLOBALS"]["default"]["local_asn"] = str(local_asn)
            except ValueError as e:
                logger.warning(
                    f"Could not calculate local ASN for device {device.name}: {e}"
                )

    # Add port configurations in sorted order
    # Sort ports naturally (Ethernet0, Ethernet4, Ethernet8, ...)
    def natural_sort_key(port_name):
        """Extract numeric part from port name for natural sorting."""
        match = re.search(r"(\d+)", port_name)
        return int(match.group(1)) if match else 0

    sorted_ports = sorted(port_config.keys(), key=natural_sort_key)

    for port_name in sorted_ports:
        port_info = port_config[port_name]

        # Set admin_status to "up" if port is connected, otherwise "down"
        admin_status = "up" if port_name in connected_interfaces else "down"

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
            if master_port in breakout_info["breakout_cfgs"]:
                brkout_mode = breakout_info["breakout_cfgs"][master_port]["brkout_mode"]
                # Extract breakout speed from mode (e.g., "4x25G" -> "25000")
                if "25G" in brkout_mode:
                    port_speed = "25000"
                elif "50G" in brkout_mode:
                    port_speed = "50000"
                elif "100G" in brkout_mode:
                    port_speed = "100000"
                elif "200G" in brkout_mode:
                    port_speed = "200000"

            # Calculate individual lane for this breakout port (always for breakout ports)
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
                            port_lanes = str(lanes_list[subport_index])
                            logger.debug(
                                f"Breakout port {port_name}: master={master_port}, master_lanes={master_lanes}, subport_index={subport_index}, assigned_lane={port_lanes}"
                            )
                        else:
                            logger.warning(
                                f"Breakout port {port_name}: subport_index {subport_index} out of range for lanes_list {lanes_list}"
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

        config["PORT"][port_name] = {
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

    # Add breakout ports that might not be in the original port_config
    for port_name in breakout_info["breakout_ports"]:
        if port_name not in config["PORT"]:
            # Get the master port to determine configuration
            master_port = breakout_info["breakout_ports"][port_name]["master"]
            if master_port in breakout_info["breakout_cfgs"]:
                brkout_mode = breakout_info["breakout_cfgs"][master_port]["brkout_mode"]

                # Extract breakout speed from mode
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

                # Set admin_status based on connection
                admin_status = "up" if port_name in connected_interfaces else "down"

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
                port_lanes = "1"  # Default fallback
                port_match = re.match(r"Ethernet(\d+)", port_name)
                if master_port in port_config and port_match:
                    master_lanes = port_config[master_port]["lanes"]
                    # Parse lane range (e.g., "1,2,3,4" or "1-4")
                    if "," in master_lanes:
                        lanes_list = [
                            int(lane.strip()) for lane in master_lanes.split(",")
                        ]
                    elif "-" in master_lanes:
                        start, end = map(int, master_lanes.split("-"))
                        lanes_list = list(range(start, end + 1))
                    else:
                        # Single lane or simple number
                        lanes_list = [int(master_lanes)]

                    # Calculate which lane this breakout port should use
                    sonic_port_num = int(port_match.group(1))
                    master_port_match = re.match(r"Ethernet(\d+)", master_port)
                    if master_port_match:
                        master_port_num = int(master_port_match.group(1))
                        # Calculate subport index (0, 1, 2, 3 for 4x breakout)
                        subport_index = sonic_port_num - master_port_num
                        if 0 <= subport_index < len(lanes_list):
                            port_lanes = str(lanes_list[subport_index])
                            logger.debug(
                                f"Breakout port {port_name}: master={master_port}, master_lanes={master_lanes}, subport_index={subport_index}, assigned_lane={port_lanes}"
                            )
                        else:
                            logger.warning(
                                f"Breakout port {port_name}: subport_index {subport_index} out of range for lanes_list {lanes_list}"
                            )

                config["PORT"][port_name] = {
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

    # Add tagged VLANs to PORT configuration
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
                netbox_interface_name, speed
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

    # Add INTERFACE configuration for connected interfaces (except management-only)
    # This enables IPv6 link-local only mode for all connected non-management interfaces
    for port_name in config["PORT"]:
        # Check if this port is in the connected interfaces set
        if port_name in connected_interfaces:
            # Add interface to INTERFACE section with ipv6_use_link_local_only enabled
            config["INTERFACE"][port_name] = {"ipv6_use_link_local_only": "enable"}

    # Add BGP_NEIGHBOR_AF configuration for connected interfaces (except management-only)
    # This enables BGP for both IPv4 and IPv6 unicast on all connected non-management interfaces
    for port_name in config["PORT"]:
        # Check if this port is in the connected interfaces set
        if port_name in connected_interfaces:
            # Add BGP neighbor address family configuration for IPv4 and IPv6
            ipv4_key = f"default|{port_name}|ipv4_unicast"
            ipv6_key = f"default|{port_name}|ipv6_unicast"

            config["BGP_NEIGHBOR_AF"][ipv4_key] = {"admin_status": "true"}
            config["BGP_NEIGHBOR_AF"][ipv6_key] = {"admin_status": "true"}

    # Add BGP_NEIGHBOR configuration for connected interfaces (except management-only and virtual)
    # This configures BGP neighbors as external peers with IPv6-only mode
    for port_name in config["PORT"]:
        # Check if this port is in the connected interfaces set
        if port_name in connected_interfaces:
            # Add BGP neighbor configuration
            neighbor_key = f"default|{port_name}"
            config["BGP_NEIGHBOR"][neighbor_key] = {
                "peer_type": "external",
                "v6only": "true",
            }

    # Add additional BGP_NEIGHBOR configuration using Loopback0 IP addresses from connected devices
    try:
        # Get all interfaces for the device to find connected devices
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)

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
                    interface.name, interface_speed
                )

                # Only process if this interface is in our PORT configuration
                if (
                    sonic_interface_name in config["PORT"]
                    and sonic_interface_name in connected_interfaces
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
                                                config["BGP_NEIGHBOR"][neighbor_key] = {
                                                    "peer_type": "external"
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

    # Add NTP_SERVER configuration using Loopback0 IP addresses from devices with manager or metalbox roles
    try:
        # Get devices with manager or metalbox device roles
        devices_manager = utils.nb.dcim.devices.filter(role="manager")
        devices_metalbox = utils.nb.dcim.devices.filter(role="metalbox")

        # Combine both device lists
        ntp_devices = list(devices_manager) + list(devices_metalbox)

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
                                config["NTP_SERVER"][ip_only] = {
                                    "maxpoll": "10",
                                    "minpoll": "6",
                                    "prefer": "false",
                                }
                                logger.info(
                                    f"Added NTP server {ip_only} from device {ntp_device.name} with role {ntp_device.role.slug}"
                                )
                    break

    except Exception as e:
        logger.warning(f"Could not process NTP servers: {e}")

    # Add VLAN configuration from NetBox
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
                    netbox_interface_name, speed
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
                netbox_interface_name, speed
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

    # Add Loopback configuration from NetBox
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

    # Add management interface configuration if OOB IP is available
    if oob_ip_result:
        oob_ip, prefix_len = oob_ip_result

        config["MGMT_INTERFACE"]["eth0"] = {"admin_status": "up"}
        # Add IP configuration to MGMT_INTERFACE with CIDR notation
        config["MGMT_INTERFACE"][f"eth0|{oob_ip}/{prefix_len}"] = {}

    # Add breakout configuration from NetBox
    if breakout_info["breakout_cfgs"]:
        config["BREAKOUT_CFG"].update(breakout_info["breakout_cfgs"])

    if breakout_info["breakout_ports"]:
        config["BREAKOUT_PORTS"].update(breakout_info["breakout_ports"])

    return config


def sync_sonic():
    """Sync SONiC configurations for eligible devices.

    Returns:
        dict: Dictionary with device names as keys and their SONiC configs as values
    """
    logger.info("Preparing SONIC configuration files")

    # Dictionary to store configurations for all devices
    device_configs = {}

    # List of supported HWSKUs
    supported_hwskus = [
        "Accton-AS5835-54T",
        "Accton-AS7326-56X",
        "Accton-AS7726-32X",
        "Accton-AS9716-32D",
    ]

    logger.debug(f"Supported HWSKUs: {', '.join(supported_hwskus)}")

    # Get device query list from NETBOX_FILTER_CONDUCTOR_SONIC
    nb_device_query_list = get_nb_device_query_list_sonic()

    devices = []
    for nb_device_query in nb_device_query_list:
        # Query devices with the NETBOX_FILTER_CONDUCTOR_SONIC criteria
        for device in utils.nb.dcim.devices.filter(**nb_device_query):
            # Check if device role matches allowed roles
            if device.role and device.role.slug in DEFAULT_SONIC_ROLES:
                devices.append(device)
                logger.debug(
                    f"Found device: {device.name} with role: {device.role.slug}"
                )

    logger.info(f"Found {len(devices)} devices matching criteria")

    # Generate SONIC configuration for each device
    for device in devices:
        # Get HWSKU from sonic_parameters custom field, default to None
        hwsku = None
        if (
            hasattr(device, "custom_fields")
            and "sonic_parameters" in device.custom_fields
            and device.custom_fields["sonic_parameters"]
            and "hwsku" in device.custom_fields["sonic_parameters"]
        ):
            hwsku = device.custom_fields["sonic_parameters"]["hwsku"]

        # Skip devices without HWSKU
        if not hwsku:
            logger.debug(f"Skipping device {device.name}: no HWSKU configured")
            continue

        logger.debug(f"Processing device: {device.name} with HWSKU: {hwsku}")

        # Validate that HWSKU is supported
        if hwsku not in supported_hwskus:
            logger.warning(
                f"Device {device.name} has unsupported HWSKU: {hwsku}. Supported HWSKUs: {', '.join(supported_hwskus)}"
            )
            continue

        # Generate SONIC configuration based on device HWSKU
        sonic_config = generate_sonic_config(device, hwsku)

        # Store configuration in the dictionary
        device_configs[device.name] = sonic_config

        # Save the generated configuration to NetBox config context
        save_config_to_netbox(device, sonic_config)

        # Export the generated configuration to local file
        export_config_to_file(device, sonic_config)

        logger.info(
            f"Generated SONiC config for device {device.name} with {len(sonic_config['PORT'])} ports"
        )

    logger.info(f"Generated SONiC configurations for {len(device_configs)} devices")

    # Return the dictionary with all device configurations
    return device_configs
