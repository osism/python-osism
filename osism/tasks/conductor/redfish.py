# SPDX-License-Identifier: Apache-2.0

from loguru import logger
from osism.tasks.conductor.utils import get_redfish_connection


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
                            "full_duplex": getattr(interface, "full_duplex", None),
                            "mtu_size": getattr(interface, "mtu_size", None),
                            "status": getattr(interface, "status", None),
                            "link_status": getattr(interface, "link_status", None),
                            "interface_enabled": getattr(
                                interface, "interface_enabled", None
                            ),
                            "auto_neg": getattr(interface, "auto_neg", None),
                            "vlan": getattr(interface, "vlan", None),
                            "vlans": getattr(interface, "vlans", None),
                        }

                        # Clean up None values
                        interface_data = {
                            k: v for k, v in interface_data.items() if v is not None
                        }

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
