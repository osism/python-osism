# SPDX-License-Identifier: Apache-2.0

"""Device-related helper functions for SONiC configuration."""

from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import get_nb_device_query_list_sonic
from osism.tasks.conductor.sonic.constants import DEFAULT_SONIC_ROLES


def get_device_platform(device, hwsku):
    """Get platform for device from sonic_parameters or generate from HWSKU.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name

    Returns:
        str: Platform string (e.g., 'x86_64-accton_as7326_56x-r0')
    """
    platform = None
    if (
        hasattr(device, "custom_fields")
        and "sonic_parameters" in device.custom_fields
        and device.custom_fields["sonic_parameters"]
        and "platform" in device.custom_fields["sonic_parameters"]
    ):
        platform = device.custom_fields["sonic_parameters"]["platform"]

    if not platform:
        # Generate platform from hwsku: x86_64-{hwsku_lower_with_underscores}-r0
        hwsku_formatted = hwsku.lower().replace("-", "_")
        platform = f"x86_64-{hwsku_formatted}-r0"

    return platform


def get_device_hostname(device):
    """Get hostname for device from inventory_hostname custom field or device name.

    Args:
        device: NetBox device object

    Returns:
        str: Hostname for the device
    """
    hostname = device.name
    if (
        hasattr(device, "custom_fields")
        and "inventory_hostname" in device.custom_fields
        and device.custom_fields["inventory_hostname"]
    ):
        hostname = device.custom_fields["inventory_hostname"]

    return hostname


def get_device_mac_address(device):
    """Get MAC address from device's management interface.

    Args:
        device: NetBox device object

    Returns:
        str: MAC address or default '00:00:00:00:00:00'
    """
    mac_address = "00:00:00:00:00:00"  # Default MAC
    try:
        # Get all interfaces for the device
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)
        for interface in interfaces:
            # Check if interface is marked as management only
            if interface.mgmt_only:
                if interface.mac_address:
                    mac_address = interface.mac_address
                    logger.debug(
                        f"Using MAC address {mac_address} from management interface {interface.name}"
                    )
                    break
    except Exception as e:
        logger.warning(f"Could not get MAC address for device {device.name}: {e}")

    return mac_address


def get_devices(self, device_name=None):
    try:
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
                        return 1
                else:
                    logger.error(f"Device {device_name} not found in NetBox")
                    return 1
            except Exception as e:
                logger.error(f"Error fetching device {device_name}: {e}")
                return 1
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

    except Exception as e:
        logger.error(f"Error retrieving SONiC devices from NetBox: {e}")
        return None

    return devices
