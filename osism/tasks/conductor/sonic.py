# SPDX-License-Identifier: Apache-2.0

import os
from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import get_nb_device_query_list


# Constants
DEFAULT_SONIC_ROLES = [
    "leaf",
    "spine",
    "access-leaf",
    "switch",
    "service-leaf",
    "data-leaf",
    "storage-leaf",
    "compute-leaf",
    "border-leaf",
    "transfer-leaf",
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

    # Get device metadata using helper functions
    platform = get_device_platform(device, hwsku)
    hostname = get_device_hostname(device)
    mac_address = get_device_mac_address(device)
    version = get_device_version(device)

    # Create minimal config structure
    config = {
        "DEVICE_METADATA": {
            "localhost": {
                "hostname": hostname,
                "hwsku": hwsku,
                "platform": platform,
                "mac": mac_address,
                "type": "LeafRouter",
            }
        },
        "PORT": {},
        "LOOPBACK": {"Loopback0": {"admin_status": "up"}},
        "LOOPBACK_INTERFACE": {"Loopback0": {}},
        "FEATURE": {
            "bgp": {"state": "enabled", "auto_restart": "enabled"},
            "swss": {"state": "enabled", "auto_restart": "enabled"},
            "syncd": {"state": "enabled", "auto_restart": "enabled"},
            "teamd": {"state": "enabled", "auto_restart": "enabled"},
            "pmon": {"state": "enabled", "auto_restart": "enabled"},
            "lldp": {"state": "enabled", "auto_restart": "enabled"},
            "database": {"state": "always_enabled"},
        },
        "FLEX_COUNTER_TABLE": {"PORT": {"FLEX_COUNTER_STATUS": "enable"}},
        "VERSIONS": {"DATABASE": {"VERSION": version}},
    }

    # Add port configurations
    for port_name, port_info in port_config.items():
        config["PORT"][port_name] = {
            "admin_status": "down",
            "alias": port_info["alias"],
            "index": port_info["index"],
            "lanes": port_info["lanes"],
            "speed": port_info["speed"],
            "mtu": "9100",
        }

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

    # Get device query list from NETBOX_FILTER_CONDUCTOR
    nb_device_query_list = get_nb_device_query_list()

    devices = []
    for nb_device_query in nb_device_query_list:
        # Query devices with the NETBOX_FILTER_CONDUCTOR criteria
        for device in utils.nb.dcim.devices.filter(**nb_device_query):
            # Check if device role matches allowed roles
            if device.role and device.role.slug in DEFAULT_SONIC_ROLES:
                # Check if device has the required tag
                if device.tags and any(
                    tag.slug == "managed-by-osism" for tag in device.tags
                ):
                    devices.append(device)
                    logger.debug(
                        f"Found device: {device.name} with role: {device.role.slug}"
                    )
                else:
                    logger.debug(
                        f"Skipping device {device.name}: missing 'managed-by-osism' tag"
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

        logger.info(
            f"Generated SONiC config for device {device.name} with {len(sonic_config['PORT'])} ports"
        )

    logger.info(f"Generated SONiC configurations for {len(device_configs)} devices")

    # Return the dictionary with all device configurations
    return device_configs
