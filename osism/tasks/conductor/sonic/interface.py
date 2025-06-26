# SPDX-License-Identifier: Apache-2.0

"""Interface conversion and port detection functions for SONiC configuration."""

import copy
import os
import re
from loguru import logger

from .constants import PORT_TYPE_TO_SPEED_MAP, HIGH_SPEED_PORTS, PORT_CONFIG_PATH
from .cache import get_cached_device_interfaces

# Global cache for port configurations to avoid repeated file reads
_port_config_cache: dict[str, dict[str, dict[str, str]]] = {}


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


def convert_netbox_interface_to_sonic(device_interface, device=None):
    """Convert NetBox interface name to SONiC interface name with device-specific mapping.

    Args:
        device_interface: NetBox interface object or interface name string
        device: NetBox device object (required if device_interface is string)

    Returns:
        str: SONiC interface name (e.g., "Ethernet0", "Ethernet4")
    """
    # Extract interface name and determine device context
    if isinstance(device_interface, str):
        # Legacy mode: interface name as string
        interface_name = device_interface
        if device is None:
            logger.warning(
                "Device object required when interface is provided as string"
            )
            return interface_name
    else:
        # New mode: interface object
        interface_name = device_interface.name
        if device is None:
            logger.warning(
                "Device object required for device-specific interface mapping"
            )
            return interface_name

    # Check if this is already in SONiC format (Ethernet*)
    if interface_name.startswith("Ethernet"):
        return interface_name

    # Get HWSKU from device sonic_parameters
    device_hwsku = None
    if (
        hasattr(device, "custom_fields")
        and "sonic_parameters" in device.custom_fields
        and device.custom_fields["sonic_parameters"]
        and "hwsku" in device.custom_fields["sonic_parameters"]
    ):
        device_hwsku = device.custom_fields["sonic_parameters"]["hwsku"]

    if not device_hwsku:
        logger.warning(f"No HWSKU found for device {device.name}")
        return interface_name

    # Get all device interfaces for breakout detection (using cache)
    try:
        all_interfaces = get_cached_device_interfaces(device.id)
        interface_names = [iface.name for iface in all_interfaces]
    except Exception as e:
        logger.warning(f"Could not fetch device interfaces: {e}")
        return interface_name

    # Get port configuration for HWSKU
    try:
        port_config = get_port_config(device_hwsku)
        if not port_config:
            logger.warning(f"No port config found for HWSKU {device_hwsku}")
            return interface_name
    except Exception as e:
        logger.warning(f"Could not load port config for {device_hwsku}: {e}")
        return interface_name

    # Handle different interface naming patterns
    return _map_interface_name_to_sonic(
        interface_name, interface_names, port_config, device_hwsku
    )


def _map_interface_name_to_sonic(
    interface_name, all_interface_names, port_config, device_hwsku
):
    """Map interface name to SONiC format based on port config and breakout detection.

    Args:
        interface_name: The interface name to map
        all_interface_names: List of all interface names on the device
        port_config: Port configuration dictionary from HWSKU
        device_hwsku: Hardware SKU name for logging

    Returns:
        str: SONiC interface name
    """
    # Check for EthX/Y/Z format (potential breakout)
    breakout_match = re.match(r"Eth(\d+)/(\d+)/(\d+)", interface_name)
    if breakout_match:
        return _handle_breakout_interface(
            interface_name, all_interface_names, port_config, device_hwsku
        )

    # Check for EthX/Y format (standard format)
    standard_match = re.match(r"Eth(\d+)/(\d+)", interface_name)
    if standard_match:
        return _handle_standard_interface(interface_name, port_config, device_hwsku)

    # For any other format, try to find by alias in port config
    for sonic_port, config in port_config.items():
        if config.get("alias") == interface_name:
            logger.debug(f"Found {interface_name} -> {sonic_port} via alias mapping")
            return sonic_port

    logger.warning(
        f"Could not map interface {interface_name} using HWSKU {device_hwsku}"
    )
    return interface_name


def _handle_breakout_interface(
    interface_name, all_interface_names, port_config, device_hwsku
):
    """Handle EthX/Y/Z format interfaces with breakout detection.

    Args:
        interface_name: Interface name in EthX/Y/Z format
        all_interface_names: List of all interface names on the device
        port_config: Port configuration dictionary
        device_hwsku: Hardware SKU name for logging

    Returns:
        str: SONiC interface name
    """
    match = re.match(r"Eth(\d+)/(\d+)/(\d+)", interface_name)
    if not match:
        return interface_name

    module = int(match.group(1))
    port = int(match.group(2))
    subport = int(match.group(3))

    # Find all interfaces with same module and port (potential breakout group)
    breakout_group = []
    for iface_name in all_interface_names:
        breakout_match = re.match(r"Eth(\d+)/(\d+)/(\d+)", iface_name)
        if breakout_match:
            iface_module = int(breakout_match.group(1))
            iface_port = int(breakout_match.group(2))
            iface_subport = int(breakout_match.group(3))

            if iface_module == module and iface_port == port:
                breakout_group.append((iface_subport, iface_name))

    # Check if this is a breakout port (more than one interface with same module/port)
    if len(breakout_group) > 1:
        # Sort by subport number
        breakout_group.sort(key=lambda x: x[0])

        # Find the alias for the interface with the smallest subport
        min_subport_interface = breakout_group[0][1]

        # Map the min subport interface to find base SONiC name
        base_sonic_name = _find_sonic_name_by_alias_mapping(
            min_subport_interface, port_config
        )
        if base_sonic_name:
            # Extract base port number (e.g., "Ethernet0" -> 0)
            base_match = re.match(r"Ethernet(\d+)", base_sonic_name)
            if base_match:
                base_port_num = int(base_match.group(1))

                # Calculate offset from minimum subport
                min_subport = breakout_group[0][0]
                current_offset = subport - min_subport

                sonic_port_num = base_port_num + current_offset
                result = f"Ethernet{sonic_port_num}"

                logger.debug(
                    f"Breakout mapping: {interface_name} -> {result} (base: {base_sonic_name}, offset: {current_offset})"
                )
                return result

    # Not a breakout or couldn't find base mapping, try direct alias mapping
    return _find_sonic_name_by_alias_mapping(interface_name, port_config)


def _handle_standard_interface(interface_name, port_config, device_hwsku):
    """Handle EthX/Y format interfaces.

    Args:
        interface_name: Interface name in EthX/Y format
        port_config: Port configuration dictionary
        device_hwsku: Hardware SKU name for logging

    Returns:
        str: SONiC interface name
    """
    return _find_sonic_name_by_alias_mapping(interface_name, port_config)


def _find_sonic_name_by_alias_mapping(interface_name, port_config):
    """Find SONiC interface name by mapping through alias in port config.

    The mapping works as follows:
    - tenGigE1 alias maps to Eth1/1/1 or Eth1/1
    - tenGigE48 alias maps to Eth1/48/1 or Eth1/48
    - hundredGigE49 alias maps to Eth1/49/1 or Eth1/49
    - Eth1(Port1) -> Ethernet0, Eth2(Port2) -> Ethernet1, Eth3(Port) -> Ethernet2

    Args:
        interface_name: NetBox interface name (e.g., "Eth1/1", "Eth1/1/1", or "Eth1(Port1)")
        port_config: Port configuration dictionary

    Returns:
        str: SONiC interface name or original name if not found
    """
    logger.debug(f"Finding SONiC name for interface: '{interface_name}'")
    logger.debug(f"Port config contains {len(port_config)} entries")

    # Handle new Eth1(Port1) format first
    paren_match = re.match(r"Eth(\d+)\(Port(\d*)\)", interface_name)
    if paren_match:
        eth_num = int(paren_match.group(1))
        # Map EthX(PortY) to EthernetX-1 (1-based to 0-based conversion)
        ethernet_num = eth_num - 1
        sonic_name = f"Ethernet{ethernet_num}"
        logger.debug(
            f"Alias mapping: {interface_name} -> {sonic_name} via Eth(Port) format (eth_num={eth_num}, ethernet_num={ethernet_num})"
        )
        return sonic_name

    # Create reverse mapping: expected NetBox name -> alias -> SONiC name
    for sonic_port, config in port_config.items():
        alias = config.get("alias", "")
        if not alias:
            logger.debug(f"Skipping {sonic_port}: no alias")
            continue

        # Extract number from alias (e.g., tenGigE1 -> 1, hundredGigE49 -> 49)
        alias_match = re.search(r"(\d+)$", alias)
        if not alias_match:
            logger.debug(
                f"Skipping {sonic_port}: alias '{alias}' has no trailing number"
            )
            continue

        alias_num = int(alias_match.group(1))

        # Generate expected NetBox interface names for this alias
        expected_names = [
            f"Eth1/{alias_num}",  # Standard format
            f"Eth1/{alias_num}/1",  # Breakout format (first subport)
        ]

        logger.debug(
            f"Checking {sonic_port} (alias='{alias}', alias_num={alias_num}) against expected_names: {expected_names}"
        )

        if interface_name in expected_names:
            logger.debug(
                f"Alias mapping: {interface_name} -> {sonic_port} via alias {alias}"
            )
            return sonic_port

    logger.warning(f"No alias mapping found for '{interface_name}'")
    logger.debug(
        f"Available aliases in port_config: {[(sonic_port, config.get('alias', '')) for sonic_port, config in port_config.items()]}"
    )
    return interface_name


def convert_sonic_interface_to_alias(
    sonic_interface_name, interface_speed=None, is_breakout=False, port_config=None
):
    """Convert SONiC interface name to NetBox-style alias.

    Args:
        sonic_interface_name: SONiC interface name (e.g., "Ethernet0", "Ethernet4")
        interface_speed: Interface speed in Mbps (optional, for speed-based calculation)
        is_breakout: Whether this is a breakout port (adds subport notation)
        port_config: Port configuration dictionary (optional, for alias-based calculation)

    Returns:
        str: NetBox-style alias (e.g., "Eth1/1", "Eth1/2" or "Eth1/1/1", "Eth1/1/2" for breakout)

    Examples:
        - Regular ports: Ethernet0 with alias "twentyFiveGigE1" -> Eth1/1
        - Breakout ports: Ethernet2 with base port alias "twentyFiveGigE1" -> Eth1/1/3
    """
    logger.debug(
        f"Converting SONiC interface to alias: {sonic_interface_name}, speed={interface_speed}, is_breakout={is_breakout}"
    )

    # Extract port number from SONiC format (Ethernet0, Ethernet4, etc.)
    match = re.match(r"Ethernet(\d+)", sonic_interface_name)
    if not match:
        # If it doesn't match expected pattern, return as-is
        logger.debug(
            f"Interface {sonic_interface_name} doesn't match Ethernet pattern, returning as-is"
        )
        return sonic_interface_name

    ethernet_num = int(match.group(1))
    logger.debug(f"Extracted ethernet_num: {ethernet_num}")

    # If port_config is provided, use alias-based calculation
    if port_config:
        return _convert_using_port_config(
            sonic_interface_name, ethernet_num, is_breakout, port_config
        )

    # Fallback to legacy speed-based calculation
    return _convert_using_speed_calculation(ethernet_num, interface_speed, is_breakout)


def _convert_using_port_config(
    sonic_interface_name, ethernet_num, is_breakout, port_config
):
    """Convert using port config alias information."""
    if is_breakout:
        # For breakout ports, find the base port in port_config
        base_port_name = _find_base_port_for_breakout(ethernet_num, port_config)
        if base_port_name and base_port_name in port_config:
            base_alias = port_config[base_port_name].get("alias", "")
            # Extract port number from base alias
            sonic_port_number = _extract_port_number_from_alias(base_alias)
            if sonic_port_number is not None:
                # Calculate subport number: how many ports after the base port
                base_ethernet_num = int(base_port_name.replace("Ethernet", ""))
                subport = (ethernet_num - base_ethernet_num) + 1

                module = 1
                result = f"Eth{module}/{sonic_port_number}/{subport}"
                logger.debug(
                    f"Breakout conversion using port config: {sonic_interface_name} -> {result} "
                    f"(base_port={base_port_name}, base_alias={base_alias}, sonic_port_number={sonic_port_number}, subport={subport})"
                )
                return result

        # Fallback if base port not found
        logger.warning(
            f"Could not find base port for breakout interface {sonic_interface_name}"
        )
        return _convert_using_speed_calculation(ethernet_num, None, is_breakout)
    else:
        # For regular ports, get alias directly
        if sonic_interface_name in port_config:
            alias = port_config[sonic_interface_name].get("alias", "")
            sonic_port_number = _extract_port_number_from_alias(alias)
            if sonic_port_number is not None:
                module = 1
                result = f"Eth{module}/{sonic_port_number}"
                logger.debug(
                    f"Regular conversion using port config: {sonic_interface_name} -> {result} "
                    f"(alias={alias}, sonic_port_number={sonic_port_number})"
                )
                return result

        # Fallback if not in port config
        logger.warning(f"Interface {sonic_interface_name} not found in port config")
        return _convert_using_speed_calculation(ethernet_num, None, is_breakout)


def _find_base_port_for_breakout(ethernet_num, port_config):
    """Find the base port for a breakout interface.

    The base port is the next smaller or equal port that exists in port_config.
    E.g., for Ethernet2 -> check Ethernet2, Ethernet1, Ethernet0 until found.
    """
    for base_num in range(ethernet_num, -1, -1):
        base_port_name = f"Ethernet{base_num}"
        if base_port_name in port_config:
            logger.debug(
                f"Found base port {base_port_name} for breakout interface Ethernet{ethernet_num}"
            )
            return base_port_name

    logger.warning(f"No base port found for breakout interface Ethernet{ethernet_num}")
    return None


def _extract_port_number_from_alias(alias):
    """Extract the port number from the end of an alias.

    E.g., "twentyFiveGigE1" -> 1, "hundredGigE49" -> 49
    """
    if not alias:
        return None

    match = re.search(r"(\d+)$", alias)
    if match:
        port_number = int(match.group(1))
        logger.debug(f"Extracted port number {port_number} from alias '{alias}'")
        return port_number

    logger.warning(f"Could not extract port number from alias '{alias}'")
    return None


def _convert_using_speed_calculation(ethernet_num, interface_speed, is_breakout):
    """Legacy speed-based conversion (fallback)."""
    logger.debug(f"Using legacy speed-based calculation for Ethernet{ethernet_num}")

    if is_breakout:
        # For breakout ports: Ethernet0 -> Eth1/1/1, Ethernet1 -> Eth1/1/2, etc.
        # Calculate base port (master port) and subport number
        base_port = (ethernet_num // 4) * 4  # Get base port (0, 4, 8, 12, ...)
        subport = (ethernet_num % 4) + 1  # Get subport number (1, 2, 3, 4)

        # Calculate physical port number for the base port
        physical_port = (base_port // 4) + 1  # Convert to 1-based indexing

        # Assume module 1 for now - could be extended for multi-module systems
        module = 1

        result = f"Eth{module}/{physical_port}/{subport}"
        logger.debug(
            f"Breakout conversion: base_port={base_port}, subport={subport}, physical_port={physical_port}, result={result}"
        )
        return result
    else:
        # For regular ports: use speed-based calculation
        # Determine speed category and multiplier
        if interface_speed and interface_speed in HIGH_SPEED_PORTS:
            # High-speed ports use 4x multiplier (lanes)
            multiplier = 4
        else:
            # Default for 1G, 10G, 25G ports - sequential numbering
            multiplier = 1

        logger.debug(
            f"Regular port calculation: interface_speed={interface_speed}, in_high_speed={interface_speed in HIGH_SPEED_PORTS if interface_speed else False}, multiplier={multiplier}"
        )

        # Calculate physical port number
        physical_port = (ethernet_num // multiplier) + 1  # Convert to 1-based indexing

        # Assume module 1 for now - could be extended for multi-module systems
        module = 1

        result = f"Eth{module}/{physical_port}"
        logger.debug(
            f"Regular conversion: ethernet_num={ethernet_num}, physical_port={physical_port}, result={result}"
        )
        return result


def get_port_config(hwsku):
    """Get port configuration for a given HWSKU. Uses caching to avoid repeated file reads.

    Args:
        hwsku: Hardware SKU name (e.g., 'Accton-AS5835-54T')

    Returns:
        dict: Port configuration with port names as keys and their properties as values
              Example: {'Ethernet0': {'lanes': '2', 'alias': 'tenGigE1', 'index': '1', 'speed': '10000', 'valid_speeds': '10000,25000'}}
    """
    global _port_config_cache  # noqa F824

    # Check if already cached
    if hwsku in _port_config_cache:
        logger.debug(f"Using cached port config for HWSKU {hwsku}")
        # Return a deep copy to ensure isolation between devices
        return copy.deepcopy(_port_config_cache[hwsku])

    port_config = {}
    config_path = f"{PORT_CONFIG_PATH}/{hwsku}.ini"

    if not os.path.exists(config_path):
        logger.error(f"Port config file not found: {config_path}")
        # Cache empty config to avoid repeated file system checks
        _port_config_cache[hwsku] = port_config
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

        # Cache the loaded configuration
        _port_config_cache[hwsku] = port_config
        logger.debug(
            f"Cached port config for HWSKU {hwsku} with {len(port_config)} ports"
        )

    except Exception as e:
        logger.error(f"Error parsing port config file {config_path}: {e}")
        # Cache empty config on error to avoid repeated attempts
        _port_config_cache[hwsku] = port_config

    # Return a deep copy to ensure isolation between devices
    return copy.deepcopy(port_config)


def clear_port_config_cache():
    """Clear the port configuration cache. Should be called at the start of sync_sonic."""
    global _port_config_cache
    _port_config_cache = {}
    logger.debug("Cleared port configuration cache")


# Deprecated: Use connections.get_connected_interfaces instead
# This function is kept for backward compatibility but delegates to the new module
def get_connected_interfaces(device, portchannel_info=None):
    """Get list of interface names that are connected to other devices.

    Args:
        device: NetBox device object
        portchannel_info: Optional port channel info dict from detect_port_channels

    Returns:
        tuple: (set of connected interfaces, set of connected port channels)
    """
    # Import here to avoid circular imports
    from .connections import get_connected_interfaces as _get_connected_interfaces

    return _get_connected_interfaces(device, portchannel_info)


def detect_breakout_ports(device):
    """Detect breakout ports from NetBox device interfaces using the centralized breakout logic.

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
        # Get all interfaces for the device (using cache)
        interfaces = get_cached_device_interfaces(device.id)
        interface_names = [iface.name for iface in interfaces]

        # Get HWSKU for port config
        device_hwsku = None
        if (
            hasattr(device, "custom_fields")
            and "sonic_parameters" in device.custom_fields
            and device.custom_fields["sonic_parameters"]
            and "hwsku" in device.custom_fields["sonic_parameters"]
        ):
            device_hwsku = device.custom_fields["sonic_parameters"]["hwsku"]

        if not device_hwsku:
            logger.warning(f"No HWSKU found for device {device.name}")
            return {"breakout_cfgs": breakout_cfgs, "breakout_ports": breakout_ports}

        # Get port configuration for the HWSKU
        try:
            port_config = get_port_config(device_hwsku)
            if not port_config:
                logger.warning(f"No port config found for HWSKU {device_hwsku}")
                return {
                    "breakout_cfgs": breakout_cfgs,
                    "breakout_ports": breakout_ports,
                }
        except Exception as e:
            logger.warning(f"Could not load port config for {device_hwsku}: {e}")
            return {"breakout_cfgs": breakout_cfgs, "breakout_ports": breakout_ports}

        # Process interfaces that match breakout patterns
        processed_groups = set()

        for interface in interfaces:
            interface_name = interface.name

            # Check for EthX/Y/Z format (NetBox breakout notation)
            breakout_match = re.match(r"Eth(\d+)/(\d+)/(\d+)", interface_name)
            if breakout_match:
                module = int(breakout_match.group(1))
                port = int(breakout_match.group(2))
                subport = int(breakout_match.group(3))

                # Create group key to avoid processing the same group multiple times
                group_key = f"{module}/{port}"
                if group_key in processed_groups:
                    continue
                processed_groups.add(group_key)

                # Use the centralized breakout logic
                sonic_name = _handle_breakout_interface(
                    interface_name, interface_names, port_config, device_hwsku
                )

                # If the breakout logic returned a valid SONiC name, we have a breakout group
                if sonic_name.startswith("Ethernet") and sonic_name != interface_name:
                    # Find all interfaces in this breakout group
                    breakout_group = []
                    for iface in interfaces:
                        iface_match = re.match(r"Eth(\d+)/(\d+)/(\d+)", iface.name)
                        if iface_match:
                            iface_module = int(iface_match.group(1))
                            iface_port = int(iface_match.group(2))
                            iface_subport = int(iface_match.group(3))

                            if iface_module == module and iface_port == port:
                                breakout_group.append((iface_subport, iface))

                    # Check if we have a valid breakout group (more than one interface)
                    if len(breakout_group) > 1:
                        # Sort by subport number
                        breakout_group.sort(key=lambda x: x[0])

                        # Find the master port (interface with smallest subport)
                        min_subport_interface = breakout_group[0][1]
                        master_sonic_name = _handle_breakout_interface(
                            min_subport_interface.name,
                            interface_names,
                            port_config,
                            device_hwsku,
                        )

                        if master_sonic_name.startswith("Ethernet"):
                            # Extract base port number
                            base_match = re.match(r"Ethernet(\d+)", master_sonic_name)
                            if base_match:
                                base_port_num = int(base_match.group(1))
                                master_port = f"Ethernet{base_port_num}"

                                # Determine breakout mode based on number of subports and speed
                                num_subports = len(breakout_group)
                                interface_speed = getattr(
                                    breakout_group[0][1], "speed", None
                                )
                                if (
                                    not interface_speed
                                    and hasattr(breakout_group[0][1], "type")
                                    and breakout_group[0][1].type
                                ):
                                    interface_speed = get_speed_from_port_type(
                                        breakout_group[0][1].type.value
                                    )

                                # Calculate breakout mode
                                if interface_speed == 25000 and num_subports == 4:
                                    brkout_mode = "4x25G"
                                elif interface_speed == 50000 and num_subports == 4:
                                    brkout_mode = "4x50G"
                                elif interface_speed == 100000 and num_subports == 4:
                                    brkout_mode = "4x100G"
                                elif interface_speed == 200000 and num_subports == 4:
                                    brkout_mode = "4x200G"
                                else:
                                    logger.debug(
                                        f"Unsupported breakout configuration: {num_subports} ports at {interface_speed} Mbps"
                                    )
                                    continue

                                # Calculate physical port number (1/1 -> port 1, 1/2 -> port 2, etc.)
                                physical_port_num = f"{module}/{port}"

                                # Add breakout config for master port
                                breakout_cfgs[master_port] = {
                                    "breakout_owner": "MANUAL",
                                    "brkout_mode": brkout_mode,
                                    "port": physical_port_num,
                                }

                                # Add all subports to breakout_ports
                                min_subport = breakout_group[0][0]
                                for subport, iface in breakout_group:
                                    current_offset = subport - min_subport
                                    sonic_port_num = base_port_num + current_offset
                                    port_name = f"Ethernet{sonic_port_num}"
                                    breakout_ports[port_name] = {"master": master_port}

                                logger.debug(
                                    f"Detected breakout group: {group_key} -> {master_port} ({brkout_mode}) with {len(breakout_group)} ports"
                                )

            # Also check for SONiC format breakout (Ethernet0, Ethernet1, Ethernet2, Ethernet3)
            # Only process SONiC breakout if we have explicitly configured breakout ports in NetBox,
            # not automatically assume consecutive Ethernet ports are breakouts
            sonic_match = re.match(r"Ethernet(\d+)", interface_name)
            if sonic_match:
                port_num = int(sonic_match.group(1))
                # Check if this could be part of a breakout group (consecutive Ethernet ports)
                base_port = (port_num // 4) * 4
                group_key = f"sonic_{base_port}"

                if group_key in processed_groups:
                    continue
                processed_groups.add(group_key)

                # Find potential breakout group (4 consecutive Ethernet ports)
                sonic_breakout_group = []
                for i in range(4):
                    ethernet_name = f"Ethernet{base_port + i}"
                    for iface in interfaces:
                        if iface.name == ethernet_name:
                            # Check if this interface has a speed that suggests breakout
                            iface_speed = getattr(iface, "speed", None)
                            if (
                                not iface_speed
                                and hasattr(iface, "type")
                                and iface.type
                            ):
                                iface_speed = get_speed_from_port_type(iface.type.value)

                            # Only consider as breakout if speed is 50G or less AND we have 4 consecutive ports
                            # This prevents regular 100G ports from being treated as breakout ports
                            if (
                                iface_speed and iface_speed <= 50000
                            ):  # 50G or less suggests breakout
                                sonic_breakout_group.append((base_port + i, iface))
                            break

                # If we found 4 consecutive interfaces with true breakout speeds (≤50G)
                if len(sonic_breakout_group) == 4:
                    master_port = f"Ethernet{base_port}"

                    # Determine breakout mode based on speed
                    interface_speed = getattr(sonic_breakout_group[0][1], "speed", None)
                    if (
                        not interface_speed
                        and hasattr(sonic_breakout_group[0][1], "type")
                        and sonic_breakout_group[0][1].type
                    ):
                        interface_speed = get_speed_from_port_type(
                            sonic_breakout_group[0][1].type.value
                        )

                    if interface_speed == 25000:
                        brkout_mode = "4x25G"
                    elif interface_speed == 50000:
                        brkout_mode = "4x50G"
                    else:
                        continue  # Skip unsupported speeds

                    # Calculate physical port number (Ethernet0-3 -> port 1/1, Ethernet4-7 -> port 1/2, etc.)
                    physical_port_index = (base_port // 4) + 1
                    physical_port_num = f"1/{physical_port_index}"

                    # Add breakout config for master port
                    breakout_cfgs[master_port] = {
                        "breakout_owner": "MANUAL",
                        "brkout_mode": brkout_mode,
                        "port": physical_port_num,
                    }

                    # Add all ports to breakout_ports
                    for port_num, iface in sonic_breakout_group:
                        port_name = f"Ethernet{port_num}"
                        breakout_ports[port_name] = {"master": master_port}

                    logger.debug(
                        f"Detected SONiC breakout group: Ethernet{base_port}-{base_port + 3} -> {master_port} ({brkout_mode})"
                    )

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
                          'fast_rate': 'true',
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
        # Get all interfaces for the device (using cache)
        interfaces = get_cached_device_interfaces(device.id)

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
                    interface, device
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
                        "fast_rate": "true",
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
