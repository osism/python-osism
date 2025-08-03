# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
from typing import List, Optional
from loguru import logger

from osism import utils


def get_host_identifiers(hostname: str) -> List[str]:
    """
    Get all possible host identifiers for SSH known_hosts cleanup.

    This includes the hostname itself and its resolved IP address
    (both via DNS and Netbox fallback if available).

    Args:
        hostname: The hostname to get identifiers for

    Returns:
        List of unique host identifiers (hostname, IPs)
    """
    identifiers = [hostname]

    # Try DNS resolution first
    try:
        import socket

        ip_address = socket.gethostbyname(hostname)
        if ip_address and ip_address not in identifiers:
            identifiers.append(ip_address)
            logger.debug(f"Resolved hostname {hostname} to {ip_address} via DNS")
    except socket.gaierror as e:
        logger.debug(f"DNS resolution failed for {hostname}: {e}")

    # Try Netbox fallback if available
    if utils.nb:
        try:
            device = utils.nb.dcim.devices.get(name=hostname)
            if device and device.primary_ip4:
                ip_address = str(device.primary_ip4.address).split("/")[0]
                if ip_address and ip_address not in identifiers:
                    identifiers.append(ip_address)
                    logger.debug(
                        f"Found primary IPv4 for {hostname} in Netbox: {ip_address}"
                    )
        except Exception as e:
            logger.debug(f"Error querying Netbox for {hostname}: {e}")

    return identifiers


def remove_known_hosts_entries(
    hostname: str, known_hosts_path: str = "/share/known_hosts"
) -> bool:
    """
    Remove SSH known_hosts entries for a given hostname and its IP addresses.

    This function safely removes entries from the SSH known_hosts file for both
    the hostname and any resolved IP addresses (DNS + Netbox fallback).

    Args:
        hostname: The hostname to remove entries for
        known_hosts_path: Path to the SSH known_hosts file (default: /share/known_hosts)

    Returns:
        True if cleanup was successful, False otherwise
    """
    if not hostname or not hostname.strip():
        logger.warning("Empty hostname provided for SSH known_hosts cleanup")
        return False

    if not os.path.exists(known_hosts_path):
        logger.debug(f"SSH known_hosts file does not exist: {known_hosts_path}")
        return True

    # Assume ssh-keygen is available (it's a standard SSH tool)

    # Get all possible host identifiers
    try:
        identifiers = get_host_identifiers(hostname)
        if not identifiers:
            logger.warning(f"No host identifiers found for {hostname}")
            return False

        logger.info(f"Cleaning SSH known_hosts entries for {hostname}: {identifiers}")
    except Exception as e:
        logger.error(f"Error getting host identifiers for {hostname}: {e}")
        return False

    success = True
    entries_removed = 0

    for identifier in identifiers:
        if not identifier or not identifier.strip():
            logger.debug("Skipping empty identifier")
            continue

        try:
            # Use ssh-keygen to remove entries safely
            # The -R option removes all keys for the specified host
            result = subprocess.run(
                ["ssh-keygen", "-R", identifier, "-f", known_hosts_path],
                capture_output=True,
                text=True,
                timeout=30,  # Increased timeout for safety
            )

            if result.returncode == 0:
                # ssh-keygen returns 0 even if no entries were found
                # Check stderr for messages about entries being updated
                stderr_lower = result.stderr.lower()
                if "updated" in stderr_lower or identifier in stderr_lower:
                    entries_removed += 1
                    logger.debug(f"Removed SSH known_hosts entries for {identifier}")
                else:
                    logger.debug(f"No SSH known_hosts entries found for {identifier}")
            else:
                # Log stderr for debugging but don't fail entirely
                logger.warning(
                    f"ssh-keygen returned non-zero exit code for {identifier}: {result.stderr.strip()}"
                )

        except subprocess.TimeoutExpired:
            logger.error(
                f"Timeout while removing SSH known_hosts entries for {identifier}"
            )
            success = False
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Error removing SSH known_hosts entries for {identifier}: {e}"
            )
            success = False
        except Exception as e:
            logger.error(
                f"Unexpected error removing SSH known_hosts entries for {identifier}: {e}"
            )
            success = False

    if entries_removed > 0:
        logger.info(
            f"Successfully cleaned {entries_removed} SSH known_hosts entries for {hostname}"
        )
    else:
        logger.debug(f"No SSH known_hosts entries found to clean for {hostname}")

    return success


def backup_known_hosts(
    known_hosts_path: str = "/share/known_hosts",
) -> Optional[str]:
    """
    Create a backup of the SSH known_hosts file before making changes.

    Args:
        known_hosts_path: Path to the SSH known_hosts file

    Returns:
        Path to the backup file if successful, None otherwise
    """
    if not known_hosts_path or not known_hosts_path.strip():
        logger.warning("Empty known_hosts path provided for backup")
        return None

    if not os.path.exists(known_hosts_path):
        logger.debug(
            f"SSH known_hosts file does not exist, no backup needed: {known_hosts_path}"
        )
        return None

    try:
        # Check if file is readable
        if not os.access(known_hosts_path, os.R_OK):
            logger.warning(f"SSH known_hosts file is not readable: {known_hosts_path}")
            return None

        # Create backup with timestamp
        import datetime

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{known_hosts_path}.backup_{timestamp}"

        # Ensure backup directory exists and is writable
        backup_dir = os.path.dirname(backup_path)
        if not os.path.exists(backup_dir):
            logger.warning(f"Backup directory does not exist: {backup_dir}")
            return None

        if not os.access(backup_dir, os.W_OK):
            logger.warning(f"Backup directory is not writable: {backup_dir}")
            return None

        # Copy the file
        import shutil

        shutil.copy2(known_hosts_path, backup_path)

        # Verify backup was created successfully
        if os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
            logger.debug(f"Created SSH known_hosts backup: {backup_path}")
            return backup_path
        else:
            logger.warning(f"Backup file was not created properly: {backup_path}")
            return None

    except PermissionError as e:
        logger.warning(f"Permission denied creating SSH known_hosts backup: {e}")
        return None
    except OSError as e:
        logger.warning(f"OS error creating SSH known_hosts backup: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error creating SSH known_hosts backup: {e}")
        return None


def cleanup_ssh_known_hosts_for_node(hostname: str, create_backup: bool = True) -> bool:
    """
    High-level function to clean up SSH known_hosts entries for a node.

    This is the main function that should be called from reset/undeploy commands.
    It optionally creates a backup and then removes all SSH known_hosts entries
    for the specified hostname and its IP addresses.

    Args:
        hostname: The hostname/node name to clean up entries for
        create_backup: Whether to create a backup before cleanup (default: True)

    Returns:
        True if cleanup was successful, False otherwise
    """
    known_hosts_path = "/share/known_hosts"

    try:
        # Create backup if requested
        if create_backup:
            backup_path = backup_known_hosts(known_hosts_path)
            if backup_path:
                logger.debug(f"SSH known_hosts backup created: {backup_path}")

        # Perform the cleanup
        success = remove_known_hosts_entries(hostname, known_hosts_path)

        return success

    except Exception as e:
        logger.error(f"Error during SSH known_hosts cleanup for {hostname}: {e}")
        return False
