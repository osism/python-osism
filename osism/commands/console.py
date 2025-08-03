# SPDX-License-Identifier: Apache-2.0

import socket
import subprocess
from typing import Optional

from cliff.command import Command
from loguru import logger
from prompt_toolkit import prompt

from osism import utils


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


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--type",
            default="ssh",
            choices=["ansible", "clush", "container", "ssh"],
            help="Type of the console (default: %(default)s)",
        )
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname or address of the console to connect",
        )
        return parser

    def take_action(self, parsed_args):
        type_console = parsed_args.type
        host = parsed_args.host[0]

        # If certain characters are contained in the hostname, then
        # enforce a certain console type.

        # ctl001/
        if host.endswith("/"):
            type_console = "container_prompt"
        # ctl001/rabbitmq
        elif "/" in host:
            type_console = "container"
        # .ctl001
        elif host.startswith("."):
            type_console = "ansible"
            host = host[1:]
        # :ctl00[1-3]
        elif host.startswith(":"):
            type_console = "clush"
            host = host[1:]

        ssh_options = "-o StrictHostKeyChecking=no -o LogLevel=ERROR -o UserKnownHostsFile=/share/known_hosts"

        if type_console == "ansible":
            subprocess.call(f"/run-ansible-console.sh {host}", shell=True)
        elif type_console == "clush":
            subprocess.call(
                f"/usr/local/bin/clush -l dragon -g {host}",
                shell=True,
            )
        elif type_console == "ssh":
            # Resolve hostname with Netbox fallback
            resolved_host = resolve_host_with_fallback(host)
            # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
            subprocess.call(
                f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{resolved_host}",
                shell=True,
            )
        elif type_console == "container_prompt":
            while True:
                command = prompt(f"{host[:-1]}>>> ")
                if command in ["Exit", "exit", "EXIT"]:
                    break

                ssh_command = f"docker {command}"
                # Resolve hostname with Netbox fallback
                resolved_host = resolve_host_with_fallback(host[:-1])
                # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
                subprocess.call(
                    f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{resolved_host} {ssh_command}",
                    shell=True,
                )
        elif type_console == "container":
            target_containername = host.split("/")[1]
            target_host = host.split("/")[0]
            target_command = "bash"

            ssh_command = f"docker exec -it {target_containername} {target_command}"
            ssh_options = "-o RequestTTY=force -o StrictHostKeyChecking=no -o LogLevel=ERROR -o UserKnownHostsFile=/share/known_hosts"

            # Resolve hostname with Netbox fallback
            resolved_target_host = resolve_host_with_fallback(target_host)
            # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
            subprocess.call(
                f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{resolved_target_host} {ssh_command}",
                shell=True,
            )
