# SPDX-License-Identifier: Apache-2.0

import ipaddress
import json
import os
import subprocess

from loguru import logger

from osism.utils.inventory import (
    HostContextResolutionError,
    get_hosts_from_inventory,
    get_inventory_path,
    resolve_in_host_context,
)

# The node's internal address, resolved the way osism/defaults resolves it
# (defaults/manager/000-defaults.yml), including the console_interface
# fallback: an operator may set console_interface explicitly and leave
# internal_interface unset, which works in the deployment and must work here.
# With neither set, defaults/all/099-interfaces.yml resolves console_interface
# to the undefined "loopback0", so this fails loudly rather than inventing an
# address.
#
# Ansible names interface facts with "-" replaced by "_" and dots left alone
# (PrefixFactNamespace._underscore), so "br-ex" is ansible_br_ex while
# "bond0.100" is ansible_bond0.100.
INTERNAL_ADDRESS_EXPRESSION = (
    "hostvars[inventory_hostname]"
    "['ansible_' + ((internal_interface | default(console_interface))"
    " | replace('-', '_'))]"
    "['ipv4']['address']"
)


def get_rabbitmq_node_addresses():
    """Get the internal IPv4 addresses of all RabbitMQ nodes from inventory.

    Returns:
        list: List of tuples (ip_address, hostname) for each RabbitMQ node,
              sorted by hostname, or None on error.
    """
    try:
        # Use ansible-inventory with --limit to get hosts in rabbitmq group
        inventory_path = get_inventory_path("/ansible/inventory/hosts.yml")
        result = subprocess.check_output(
            f"ansible-inventory -i {inventory_path} --list --limit rabbitmq",
            shell=True,
            stderr=subprocess.DEVNULL,
        )
        inventory = json.loads(result)

        rabbitmq_hosts = get_hosts_from_inventory(inventory)
        if not rabbitmq_hosts:
            logger.error("No hosts found in rabbitmq group")
            return None

        # Sort for consistent ordering
        rabbitmq_hosts.sort()
        logger.debug(f"RabbitMQ hosts: {rabbitmq_hosts}")

        from osism import utils

        node_addresses = []
        for host in rabbitmq_hosts:
            # A failure on one host must not discard the addresses already
            # collected for the other nodes.
            try:
                # Get ansible facts from Redis cache
                facts_data = utils.redis.get(f"ansible_facts{host}")
                if not facts_data:
                    logger.error(f"No ansible facts found in cache for {host}")
                    continue

                facts = json.loads(facts_data)

                # Resolve internal_interface and the address it carries in one
                # templated lookup, so that any Jinja2 shape works -- not just
                # the ones a hand-written resolver anticipated.
                hostvar_inventory_path = get_inventory_path(
                    "/ansible/inventory/hosts.yml", prefer_minified=False
                )
                try:
                    ipv4_address = resolve_in_host_context(
                        host,
                        INTERNAL_ADDRESS_EXPRESSION,
                        hostvar_inventory_path,
                        facts=facts,
                    )
                except HostContextResolutionError as exc:
                    logger.error(f"Could not resolve address for {host}: {exc}")
                    continue

                # A templating failure is reported by the return code, but a
                # module that returns a non-address string must not be trusted
                # either -- validate rather than pass it on as an address.
                try:
                    ipaddress.IPv4Address(ipv4_address)
                except ValueError:
                    logger.error(
                        f"Resolved address for {host} is not an IPv4 address: {ipv4_address!r}"
                    )
                    continue

                logger.debug(f"IPv4 address for {host}: {ipv4_address}")
                node_addresses.append((ipv4_address, host))
            except Exception as exc:
                logger.error(f"Failed to resolve address for {host}: {exc}")
                continue

        if not node_addresses:
            logger.error("Could not retrieve address for any RabbitMQ node")
            return None

        return node_addresses

    except subprocess.CalledProcessError as exc:
        logger.error(f"Failed to query ansible inventory: {exc}")
        return None
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse inventory data: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Failed to get RabbitMQ node addresses: {exc}")
        return None


def load_rabbitmq_password():
    """Load and decrypt the RabbitMQ password from secrets.yml.

    Returns:
        str: The decrypted RabbitMQ password, or None on error.
    """
    secrets_path = "/opt/configuration/environments/kolla/secrets.yml"

    if not os.path.exists(secrets_path):
        logger.error(f"Secrets file not found: {secrets_path}")
        return None

    try:
        from osism.tasks.conductor.utils import load_yaml_file

        secrets = load_yaml_file(secrets_path)

        if not secrets or not isinstance(secrets, dict):
            logger.error("Empty or invalid secrets file")
            return None

        password = secrets.get("rabbitmq_password")
        if password is None:
            logger.error("rabbitmq_password not found in secrets file")
            return None

        return str(password).strip()

    except Exception as exc:
        logger.error(f"Failed to load RabbitMQ password: {exc}")
        return None


# RabbitMQ user for OpenStack
RABBITMQ_USER = "openstack"
