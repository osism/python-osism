# SPDX-License-Identifier: Apache-2.0

"""Main SONiC synchronization function."""

from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import get_nb_device_query_list_sonic
from .bgp import find_interconnected_spine_groups, calculate_minimum_as_for_group
from .config_generator import generate_sonic_config, clear_all_caches
from .constants import DEFAULT_SONIC_ROLES, SUPPORTED_HWSKUS
from .exporter import save_config_to_netbox, export_config_to_file
from .cache import clear_interface_cache, get_interface_cache_stats


def sync_sonic():
    """Sync SONiC configurations for eligible devices.

    Returns:
        dict: Dictionary with device names as keys and their SONiC configs as values
    """
    logger.info("Preparing SONIC configuration files")

    # Clear all caches at start of sync
    clear_interface_cache()
    clear_all_caches()
    logger.debug("Initialized all caches for sync_sonic task")

    # Dictionary to store configurations for all devices
    device_configs = {}

    logger.debug(f"Supported HWSKUs: {', '.join(SUPPORTED_HWSKUS)}")

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

    # Find interconnected spine/superspine groups for special AS calculation
    spine_groups = find_interconnected_spine_groups(devices)
    logger.info(f"Found {len(spine_groups)} interconnected spine/superspine groups")

    # Create mapping from device ID to its assigned AS number
    device_as_mapping = {}

    # Calculate AS numbers for spine/superspine groups
    for group in spine_groups:
        min_as = calculate_minimum_as_for_group(group)
        if min_as:
            for device in group:
                device_as_mapping[device.id] = min_as
            logger.debug(
                f"Assigned AS {min_as} to {len(group)} devices in spine/superspine group"
            )

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
        if hwsku not in SUPPORTED_HWSKUS:
            logger.warning(
                f"Device {device.name} has unsupported HWSKU: {hwsku}. Supported HWSKUs: {', '.join(SUPPORTED_HWSKUS)}"
            )
            continue

        # Generate SONIC configuration based on device HWSKU
        sonic_config = generate_sonic_config(device, hwsku, device_as_mapping)

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

    # Log cache statistics and cleanup
    cache_stats = get_interface_cache_stats()
    if cache_stats:
        logger.debug(
            f"Interface cache stats: {cache_stats['cached_devices']} devices, {cache_stats['total_interfaces']} interfaces"
        )

    clear_interface_cache()
    clear_all_caches()
    logger.debug("Cleared all caches after sync_sonic task completion")

    # Return the dictionary with all device configurations
    return device_configs
