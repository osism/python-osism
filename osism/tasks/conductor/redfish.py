# SPDX-License-Identifier: Apache-2.0

import json
from loguru import logger
from osism.tasks.conductor.utils import get_redfish_connection


def _normalize_redfish_data(data):
    """
    Convert Redfish data values to strings and clean up None values.

    Args:
        data (dict): Dictionary with Redfish resource data

    Returns:
        dict: Dictionary with normalized string values, None values removed
    """
    normalized_data = {}

    for key, value in data.items():
        if value is not None:
            if isinstance(value, (dict, list)):
                # Convert complex objects to JSON strings
                normalized_data[key] = json.dumps(value)
            elif isinstance(value, bool):
                # Convert booleans to lowercase strings
                normalized_data[key] = str(value).lower()
            elif not isinstance(value, str):
                # Convert numbers and other types to strings
                normalized_data[key] = str(value)
            else:
                # Keep strings as-is
                normalized_data[key] = value

    return normalized_data


def get_resources(hostname, resource_type):
    """
    Get Redfish resources for a specific hostname and resource type.

    Args:
        hostname (str): The hostname of the target system
        resource_type (str): The type of resource to retrieve (e.g., EthernetInterfaces)

    Returns:
        list: Retrieved Redfish resources or empty list if failed
    """
    logger.info(
        f"Getting Redfish resources for hostname: {hostname}, resource_type: {resource_type}"
    )

    if resource_type == "EthernetInterfaces":
        return _get_ethernet_interfaces(hostname)
    elif resource_type == "NetworkAdapters":
        return _get_network_adapters(hostname)

    logger.warning(f"Resource type {resource_type} not supported yet")
    return []


def _get_ethernet_interfaces(hostname):
    """
    Get all EthernetInterfaces from a Redfish-enabled system.

    Args:
        hostname (str): The hostname of the target system

    Returns:
        list: List of EthernetInterface dictionaries
    """
    try:
        # Get Redfish connection using the utility function
        redfish_conn = get_redfish_connection(hostname, ignore_ssl_errors=True)

        if not redfish_conn:
            logger.error(f"Could not establish Redfish connection to {hostname}")
            return []

        ethernet_interfaces = []

        # Navigate through the Redfish service to find EthernetInterfaces
        # Structure: /redfish/v1/Systems/{system_id}/EthernetInterfaces
        for system in redfish_conn.get_system_collection().get_members():
            logger.debug(f"Processing system: {system.identity}")

            # Check if the system has EthernetInterfaces
            if hasattr(system, "ethernet_interfaces") and system.ethernet_interfaces:
                for interface in system.ethernet_interfaces.get_members():
                    try:
                        status = getattr(interface, "status", None)
                        # Extract relevant information from each EthernetInterface
                        interface_data = {
                            "id": interface.identity,
                            "name": getattr(interface, "name", None),
                            "description": getattr(interface, "description", None),
                            "mac_address": getattr(interface, "mac_address", None),
                            "permanent_mac_address": getattr(
                                interface, "permanent_mac_address", None
                            ),
                            "speed_mbps": getattr(interface, "speed_mbps", None),
                            "mtu_size": getattr(interface, "mtu_size", None),
                            "link_status": getattr(interface, "link_status", None),
                            "interface_enabled": getattr(
                                interface, "interface_enabled", None
                            ),
                        }

                        # Normalize data values to strings and clean up None values
                        interface_data = _normalize_redfish_data(interface_data)

                        ethernet_interfaces.append(interface_data)
                        logger.debug(
                            f"Found EthernetInterface: {interface_data.get('name', interface_data.get('id'))}"
                        )

                    except Exception as exc:
                        logger.warning(
                            f"Error processing EthernetInterface {interface.identity}: {exc}"
                        )
                        continue

        logger.info(
            f"Retrieved {len(ethernet_interfaces)} EthernetInterfaces from {hostname}"
        )
        return ethernet_interfaces

    except Exception as exc:
        logger.error(f"Error retrieving EthernetInterfaces from {hostname}: {exc}")
        return []


def _get_network_adapters(hostname):
    """
    Get all NetworkAdapters from a Redfish-enabled system.

    Args:
        hostname (str): The hostname of the target system

    Returns:
        list: List of NetworkAdapter dictionaries
    """
    try:
        # Get Redfish connection using the utility function
        redfish_conn = get_redfish_connection(hostname, ignore_ssl_errors=True)

        if not redfish_conn:
            logger.error(f"Could not establish Redfish connection to {hostname}")
            return []

        network_adapters = []

        # Navigate through the Redfish service to find NetworkAdapters
        # Structure: /redfish/v1/Chassis/{chassis_id}/NetworkAdapters
        for chassis in redfish_conn.get_chassis_collection().get_members():
            logger.debug(f"Processing chassis: {chassis.identity}")

            # Check if the chassis has NetworkAdapters
            if hasattr(chassis, "network_adapters") and chassis.network_adapters:
                for adapter in chassis.network_adapters.get_members():
                    try:
                        # Extract relevant information from each NetworkAdapter
                        adapter_data = {
                            "id": adapter.identity,
                            "name": getattr(adapter, "name", None),
                            "description": getattr(adapter, "description", None),
                            "manufacturer": getattr(adapter, "manufacturer", None),
                            "model": getattr(adapter, "model", None),
                            "part_number": getattr(adapter, "part_number", None),
                            "serial_number": getattr(adapter, "serial_number", None),
                            "firmware_version": getattr(
                                adapter, "firmware_version", None
                            ),
                            "status": getattr(adapter, "status", None),
                        }

                        # Normalize data values to strings and clean up None values
                        adapter_data = _normalize_redfish_data(adapter_data)

                        network_adapters.append(adapter_data)
                        logger.debug(
                            f"Found NetworkAdapter: {adapter_data.get('name', adapter_data.get('id'))}"
                        )

                    except Exception as exc:
                        logger.warning(
                            f"Error processing NetworkAdapter {adapter.identity}: {exc}"
                        )
                        continue

        logger.info(
            f"Retrieved {len(network_adapters)} NetworkAdapters from {hostname}"
        )
        return network_adapters

    except Exception as exc:
        logger.error(f"Error retrieving NetworkAdapters from {hostname}: {exc}")
        return []
