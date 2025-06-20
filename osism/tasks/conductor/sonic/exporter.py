# SPDX-License-Identifier: Apache-2.0

"""Configuration export functions for SONiC."""

import json
import os
from loguru import logger

from osism import utils, settings
from .device import get_device_hostname


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
        identifier_type = settings.SONIC_EXPORT_IDENTIFIER

        # Create export directory if it doesn't exist
        os.makedirs(export_dir, exist_ok=True)

        # Get identifier based on configuration
        if identifier_type == "serial-number":
            # Get serial number from device
            identifier = (
                device.serial if hasattr(device, "serial") and device.serial else None
            )
            if not identifier:
                logger.warning(
                    f"Serial number not found for device {device.name}, falling back to hostname"
                )
                identifier = get_device_hostname(device)
            else:
                logger.debug(
                    f"Using serial number {identifier} as identifier for device {device.name}"
                )
        else:
            # Default to hostname (inventory_hostname custom field or device name)
            identifier = get_device_hostname(device)

        # Generate filename: prefix + identifier + suffix
        filename = f"{prefix}{identifier}{suffix}"
        filepath = os.path.join(export_dir, filename)

        # Export configuration to JSON file
        with open(filepath, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Exported SONiC config for device {device.name} to {filepath}")

        # Create hostname symlink if using serial number identifier
        if (
            identifier_type == "serial-number"
            and hasattr(device, "serial")
            and device.serial
        ):
            try:
                hostname = get_device_hostname(device)
                hostname_filename = f"{prefix}{hostname}{suffix}"
                hostname_filepath = os.path.join(export_dir, hostname_filename)

                logger.debug(
                    f"Attempting to create symlink: {hostname_filepath} -> {filename}"
                )
                logger.debug(f"Hostname: {hostname}, Serial: {device.serial}")

                # Create symlink from hostname file to serial number file
                if os.path.exists(hostname_filepath) or os.path.islink(
                    hostname_filepath
                ):
                    logger.debug(f"Removing existing file/symlink: {hostname_filepath}")
                    os.remove(hostname_filepath)

                os.symlink(filename, hostname_filepath)
                logger.info(
                    f"Created hostname symlink {hostname_filepath} -> {filename}"
                )
            except Exception as symlink_error:
                logger.error(
                    f"Failed to create hostname symlink for device {device.name}: {symlink_error}"
                )
        else:
            logger.debug(
                f"Symlink conditions not met - identifier_type: {identifier_type}, has_serial: {hasattr(device, 'serial')}, serial_value: {getattr(device, 'serial', None)}"
            )

    except Exception as e:
        logger.error(f"Failed to export config for device {device.name}: {e}")
