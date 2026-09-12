# SPDX-License-Identifier: Apache-2.0

import json
import socket
import subprocess
from typing import Optional

from loguru import logger

from osism import utils
from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path


def resolve_hostname_to_ip(hostname: str) -> Optional[str]:
    """
    Attempt to resolve hostname to IPv4 address using DNS.

    Args:
        hostname: The hostname to resolve

    Returns:
        IPv4 address string if successful, None if resolution fails
    """
    try:
        ip_address = socket.gethostbyname(hostname)
        logger.debug(f"Resolved hostname {hostname} to {ip_address}")
        return ip_address
    except socket.gaierror as e:
        logger.debug(f"DNS resolution failed for {hostname}: {e}")
        return None


def get_primary_ipv4_from_netbox(hostname: str) -> Optional[str]:
    """
    Retrieve primary IPv4 address for hostname from Netbox.

    Args:
        hostname: The hostname to look up in Netbox

    Returns:
        Primary IPv4 address string if found, None otherwise
    """
    if not utils.nb:
        logger.debug("Netbox integration not available")
        return None

    try:
        device = utils.nb.dcim.devices.get(name=hostname)
        if device and device.primary_ip4:
            ip_address = str(device.primary_ip4.address).split("/")[0]
            logger.info(f"Found primary IPv4 for {hostname} in Netbox: {ip_address}")
            return ip_address
        else:
            logger.debug(f"No device or primary IPv4 found for {hostname} in Netbox")
            return None
    except Exception as e:
        logger.warning(f"Error querying Netbox for {hostname}: {e}")
        return None


def resolve_host_with_fallback(hostname: str) -> str:
    """
    Resolve hostname with Netbox fallback.

    First attempts DNS resolution. If that fails and Netbox integration is enabled,
    attempts to retrieve the primary IPv4 address from Netbox.

    Args:
        hostname: The hostname to resolve

    Returns:
        Resolved IP address or original hostname if all resolution attempts fail
    """
    # First try DNS resolution
    ip_address = resolve_hostname_to_ip(hostname)
    if ip_address:
        return ip_address

    # Fallback to Netbox if DNS resolution failed
    logger.info(f"DNS resolution failed for {hostname}, trying Netbox fallback")
    netbox_ip = get_primary_ipv4_from_netbox(hostname)
    if netbox_ip:
        logger.info(f"Using IPv4 address {netbox_ip} from Netbox for {hostname}")
        return netbox_ip

    # If both methods fail, return original hostname and let SSH handle the error
    logger.warning(
        f"Could not resolve {hostname} via DNS or Netbox, using original hostname"
    )
    return hostname


def get_hosts_from_group(group: str) -> list:
    """Resolve an Ansible inventory group to its list of hosts.

    Args:
        group: The inventory group name to resolve

    Returns:
        Sorted list of hostnames in the group, or empty list if the
        group does not exist or cannot be resolved.
    """
    try:
        inventory_path = get_inventory_path("/ansible/inventory/hosts.yml")
        result = subprocess.check_output(
            [
                "ansible-inventory",
                "-i",
                inventory_path,
                "--list",
                "--limit",
                group,
            ],
            stderr=subprocess.DEVNULL,
        )
        inventory = json.loads(result)
        hosts = get_hosts_from_inventory(inventory)
        return sorted(hosts)
    except Exception:
        logger.debug("Could not resolve group %r", group, exc_info=True)
        return []


def select_host_from_list(hosts: list) -> Optional[str]:
    """Display a numbered list of hosts and let the user choose one.

    Args:
        hosts: List of hostnames to choose from

    Returns:
        The selected hostname, or None if the selection was cancelled.
    """
    from prompt_toolkit import prompt as pt_prompt

    print(f"\nGroup contains {len(hosts)} hosts:\n")
    for i, host in enumerate(hosts, 1):
        print(f"  {i}) {host}")
    print()

    while True:
        answer = pt_prompt("Select host [1-{}]: ".format(len(hosts)))
        if answer.strip().lower() in ("q", "quit", "exit"):
            return None
        try:
            index = int(answer.strip())
            if 1 <= index <= len(hosts):
                return hosts[index - 1]
        except ValueError:
            pass
        print(f"Please enter a number between 1 and {len(hosts)}, or 'q' to cancel.")
