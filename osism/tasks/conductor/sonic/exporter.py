# SPDX-License-Identifier: Apache-2.0

"""Configuration export functions for SONiC."""

import json
import os
import difflib
from loguru import logger
from deepdiff import DeepDiff

from osism import utils, settings
from .device import get_device_hostname


def save_config_to_netbox(device, config, return_diff=False):
    """Save SONiC configuration to NetBox device local context with diff checking.

    Checks for existing local context and only saves if configuration has changed.
    Logs diff when changes are detected.

    Args:
        device: NetBox device object
        config: SONiC configuration dictionary
        return_diff (bool, optional): Whether to return diff output. Defaults to False.

    Returns:
        bool or tuple: If return_diff is False, returns True if config was saved (changed), False if no changes.
                      If return_diff is True, returns (changed, diff_output) tuple.
    """
    try:
        # Get existing local context data
        existing_local_context = device.local_context_data or {}

        # Prepare new local context data
        new_config_data = {"sonic_config": config}
        diff_output = None

        if existing_local_context:
            # Compare existing local context with new config

            # Generate diff
            diff = DeepDiff(existing_local_context, new_config_data, ignore_order=True)

            if not diff:
                logger.info(
                    f"No changes detected for SONiC local context of device {device.name}"
                )
                return (False, None) if return_diff else False

            # Log the unified diff
            logger.info(f"Configuration changes detected for device {device.name}:")
            existing_json = json.dumps(
                existing_local_context, indent=2, sort_keys=True
            ).splitlines()
            new_json = json.dumps(
                new_config_data, indent=2, sort_keys=True
            ).splitlines()
            unified_diff = difflib.unified_diff(
                existing_json,
                new_json,
                fromfile=f"SONiC Config - {device.name} (existing)",
                tofile=f"SONiC Config - {device.name} (new)",
                lineterm="",
            )
            diff_output = "\n".join(unified_diff)
            if diff_output:
                logger.info(f"Diff:\n{diff_output}")

                # Save diff to device journal log
                try:
                    journal_entry = utils.nb.extras.journal_entries.create(
                        assigned_object_type="dcim.device",
                        assigned_object_id=device.id,
                        kind="info",
                        comments=f"SONiC Configuration Update\n\n```diff\n{diff_output}\n```",
                    )
                    logger.info(
                        f"Saved configuration diff to journal for device {device.name}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to save diff to journal for device {device.name}: {e}"
                    )
            else:
                logger.info(f"Diff: {diff}")

            # Update existing local context
            device.local_context_data = new_config_data
            device.save()
            logger.info(f"Updated SONiC local context for device {device.name}")
            return (True, diff_output) if return_diff else True
        else:
            # Create new local context (no existing context to compare)
            device.local_context_data = new_config_data
            device.save()
            logger.info(
                f"Created new SONiC local context for device {device.name} (first-time configuration)"
            )
            return (True, None) if return_diff else True

    except Exception as e:
        logger.error(f"Failed to save local context for device {device.name}: {e}")
        return (False, None) if return_diff else False


def export_config_to_file(device, config):
    """Export SONiC configuration to local file with diff checking.

    Only writes to file if configuration has changed compared to existing file.

    Args:
        device: NetBox device object
        config: SONiC configuration dictionary

    Returns:
        bool: True if config was written (changed), False if no changes
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

        # Check if file exists and compare content
        config_changed = True
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    existing_config = json.load(f)

                # Compare configurations
                diff = DeepDiff(existing_config, config, ignore_order=True)

                if not diff:
                    logger.info(
                        f"No changes detected for SONiC config file of device {device.name}"
                    )
                    config_changed = False
                else:
                    logger.info(
                        f"Configuration file changes detected for device {device.name}"
                    )

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(
                    f"Could not read existing config file {filepath}: {e}. Will overwrite."
                )
                config_changed = True

        if config_changed:
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
                        logger.debug(
                            f"Removing existing file/symlink: {hostname_filepath}"
                        )
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

        return config_changed

    except Exception as e:
        logger.error(f"Failed to export config for device {device.name}: {e}")
        return False
