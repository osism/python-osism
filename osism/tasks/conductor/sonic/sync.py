# SPDX-License-Identifier: Apache-2.0

"""Main SONiC synchronization function."""

from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import get_nb_device_query_list_sonic
from .bgp import calculate_minimum_as_for_group
from .connections import find_interconnected_devices
from .config_generator import generate_sonic_config, clear_all_caches
from .constants import DEFAULT_SONIC_ROLES, SUPPORTED_HWSKUS
from .exporter import save_config_to_netbox, export_config_to_file
from .cache import clear_interface_cache, get_interface_cache_stats


def sync_sonic(device_name=None, task_id=None, show_diff=True):
    """Sync SONiC configurations for eligible devices.

    Args:
        device_name (str, optional): Name of specific device to sync. If None, sync all eligible devices.
        task_id (str, optional): Task ID for output logging.
        show_diff (bool, optional): Whether to show diffs when changes are detected. Defaults to True.

    Returns:
        dict: Dictionary with device names as keys and their SONiC configs as values
    """
    if device_name:
        logger.info(f"Preparing SONIC configuration for device: {device_name}")
    else:
        logger.info("Preparing SONIC configuration files")

    # Clear all caches at start of sync
    clear_interface_cache()
    clear_all_caches()
    logger.debug("Initialized all caches for sync_sonic task")

    # Dictionary to store configurations for all devices
    device_configs = {}

    logger.debug(f"Supported HWSKUs: {', '.join(SUPPORTED_HWSKUS)}")

    devices = []

    if device_name:
        # When specific device is requested, fetch it directly
        try:
            device = utils.nb.dcim.devices.get(name=device_name)
            if device:
                # Check if device role matches allowed roles
                if device.role and device.role.slug in DEFAULT_SONIC_ROLES:
                    devices.append(device)
                    logger.debug(
                        f"Found device: {device.name} with role: {device.role.slug}"
                    )
                else:
                    logger.warning(
                        f"Device {device_name} has role '{device.role.slug if device.role else 'None'}' "
                        f"which is not in allowed SONiC roles: {', '.join(DEFAULT_SONIC_ROLES)}"
                    )
                    return device_configs
            else:
                logger.error(f"Device {device_name} not found in NetBox")
                return device_configs
        except Exception as e:
            logger.error(f"Error fetching device {device_name}: {e}")
            return device_configs
    else:
        # Get device query list from NETBOX_FILTER_CONDUCTOR_SONIC
        nb_device_query_list = get_nb_device_query_list_sonic()

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
    # When processing a single device, we need to consider all spine/superspine devices
    # to properly detect interconnected groups, not just the requested device
    if device_name and devices:
        # Check if the single device is a spine/superspine
        target_device = devices[0]
        if target_device.role and target_device.role.slug in ["spine", "superspine"]:
            # Fetch ALL spine/superspine devices to properly detect groups
            logger.debug(
                "Single spine/superspine device detected, fetching all spine/superspine devices for group detection"
            )
            all_spine_devices = []
            nb_device_query_list = get_nb_device_query_list_sonic()
            for nb_device_query in nb_device_query_list:
                for device in utils.nb.dcim.devices.filter(**nb_device_query):
                    if device.role and device.role.slug in ["spine", "superspine"]:
                        all_spine_devices.append(device)
            spine_groups = find_interconnected_devices(
                all_spine_devices, ["spine", "superspine"]
            )
        else:
            # For non-spine devices, use the original logic
            spine_groups = find_interconnected_devices(devices, ["spine", "superspine"])
    else:
        # For multi-device processing, use the original logic
        spine_groups = find_interconnected_devices(devices, ["spine", "superspine"])

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

        # Output current device being processed if task_id is available
        if task_id:
            utils.push_task_output(task_id, f"Processing device: {device.name}\n")

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

        # Save the generated configuration to NetBox config context (only if changed)
        if show_diff:
            netbox_changed, diff_output = save_config_to_netbox(
                device, sonic_config, return_diff=True
            )

            # Output diff to task if available and there are changes
            if task_id and netbox_changed and diff_output:
                utils.push_task_output(task_id, f"\n{'='*60}\n")
                utils.push_task_output(
                    task_id, f"Configuration diff for {device.name}:\n"
                )
                utils.push_task_output(task_id, f"{'='*60}\n")
                utils.push_task_output(task_id, f"{diff_output}\n")
                utils.push_task_output(task_id, f"{'='*60}\n\n")
            elif task_id and netbox_changed and not diff_output:
                # First-time configuration (no diff available)
                utils.push_task_output(
                    task_id, f"First-time configuration created for {device.name}\n"
                )
        else:
            netbox_changed = save_config_to_netbox(device, sonic_config)

        # Export the generated configuration to local file (only if changed)
        file_changed = export_config_to_file(device, sonic_config)

        if netbox_changed or file_changed:
            logger.info(f"Configuration updated for device {device.name}")
        else:
            logger.info(f"No configuration changes for device {device.name}")

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

    # Finish task output if task_id is available
    if task_id:
        utils.finish_task_output(task_id, rc=0)

    # Return the dictionary with all device configurations
    return device_configs
