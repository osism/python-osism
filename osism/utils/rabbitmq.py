# SPDX-License-Identifier: Apache-2.0

import json
import os
import re
import subprocess

from loguru import logger
import yaml

from osism.tasks.conductor.utils import get_vault
from osism.utils import redis


def get_rabbitmq_node_addresses():
    """Get the internal IPv4 addresses of all RabbitMQ nodes from inventory.

    Returns:
        list: List of tuples (ip_address, hostname) for each RabbitMQ node,
              sorted by hostname, or None on error.
    """
    try:
        # Use ansible-inventory with --limit to get hosts in rabbitmq group
        result = subprocess.check_output(
            "ansible-inventory -i /ansible/inventory/hosts.yml --list --limit rabbitmq",
            shell=True,
            stderr=subprocess.DEVNULL,
        )
        inventory = json.loads(result)

        # Get hosts from _meta.hostvars (contains all hosts matching the limit)
        if "_meta" not in inventory or "hostvars" not in inventory["_meta"]:
            logger.error("Invalid inventory format: _meta.hostvars not found")
            return None

        rabbitmq_hosts = list(inventory["_meta"]["hostvars"].keys())
        if not rabbitmq_hosts:
            logger.error("No hosts found in rabbitmq group")
            return None

        # Sort for consistent ordering
        rabbitmq_hosts.sort()
        logger.debug(f"RabbitMQ hosts: {rabbitmq_hosts}")

        node_addresses = []
        for host in rabbitmq_hosts:
            # Get ansible facts from Redis cache
            facts_data = redis.get(f"ansible_facts{host}")
            if not facts_data:
                logger.error(f"No ansible facts found in cache for {host}")
                continue

            facts = json.loads(facts_data)

            # Get hostvars for this host to find internal_interface
            result = subprocess.check_output(
                f"ansible-inventory -i /ansible/inventory/hosts.yml --host {host}",
                shell=True,
                stderr=subprocess.DEVNULL,
            )
            hostvars = json.loads(result)

            internal_interface_raw = hostvars.get("internal_interface")
            if not internal_interface_raw:
                logger.error(f"internal_interface not found in hostvars for {host}")
                continue

            # Resolve Jinja2 template if present (e.g., "{{ ansible_local.testbed_network_devices.management }}")
            internal_interface = internal_interface_raw
            template_match = re.match(r"\{\{\s*(.+?)\s*\}\}", internal_interface_raw)
            if template_match:
                path = template_match.group(1).strip()
                parts = path.split(".")
                value = facts
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                if value and isinstance(value, str):
                    internal_interface = value
                else:
                    logger.error(
                        f"Could not resolve template '{internal_interface_raw}' from facts for {host}"
                    )
                    continue

            logger.debug(f"Internal interface for {host}: {internal_interface}")

            # Look for the interface in ansible facts
            # Interface names with special chars are normalized (e.g., eth0.100 -> ansible_eth0_100)
            normalized_interface = internal_interface.replace(".", "_").replace(
                "-", "_"
            )
            interface_key = f"ansible_{normalized_interface}"

            interface_facts = facts.get(interface_key)
            if not interface_facts:
                logger.error(
                    f"Interface {internal_interface} ({interface_key}) not found in ansible facts for {host}"
                )
                continue

            # Get IPv4 address
            ipv4_info = interface_facts.get("ipv4")
            if not ipv4_info:
                logger.error(
                    f"No IPv4 address found for interface {internal_interface} on {host}"
                )
                continue

            ipv4_address = ipv4_info.get("address")
            if not ipv4_address:
                logger.error(
                    f"No IPv4 address found for interface {internal_interface} on {host}"
                )
                continue

            logger.debug(f"IPv4 address for {host}: {ipv4_address}")
            node_addresses.append((ipv4_address, host))

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
        vault = get_vault()

        with open(secrets_path, "rb") as f:
            file_data = f.read()

        if vault.is_encrypted(file_data):
            decrypted_data = vault.decrypt(file_data).decode()
            logger.debug(f"Successfully decrypted secrets file: {secrets_path}")
        else:
            decrypted_data = file_data.decode()
            logger.debug(
                f"Secrets file is not encrypted (development mode): {secrets_path}"
            )

        secrets = yaml.safe_load(decrypted_data)

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
