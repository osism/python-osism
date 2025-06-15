# SPDX-License-Identifier: Apache-2.0

from loguru import logger
import yaml

from osism import settings, utils
from osism.tasks import netbox


def get_nb_device_query_list():
    try:
        supported_nb_device_filters = [
            "site",
            "region",
            "site_group",
            "location",
            "rack",
            "tag",
            "state",
        ]
        nb_device_query_list = yaml.safe_load(settings.NETBOX_FILTER_CONDUCTOR)
        if type(nb_device_query_list) is not list:
            raise TypeError
        for nb_device_query in nb_device_query_list:
            if type(nb_device_query) is not dict:
                raise TypeError
            for key in list(nb_device_query.keys()):
                if key not in supported_nb_device_filters:
                    raise ValueError
                # NOTE: Only "location_id" and "rack_id" are supported by NetBox
                if key in ["location", "rack"]:
                    value_name = nb_device_query.pop(key, "")
                    if key == "location":
                        value_id = netbox.get_location_id(value_name)
                    elif key == "rack":
                        value_id = netbox.get_rack_id(value_name)
                    if value_id:
                        nb_device_query.update({key + "_id": value_id})
                    else:
                        raise ValueError(f"Invalid name {value_name} for {key}")
    except (yaml.YAMLError, TypeError):
        logger.error(
            f"Setting NETBOX_FILTER_CONDUCTOR needs to be an array of mappings containing supported NetBox device filters: {supported_nb_device_filters}"
        )
        nb_device_query_list = []
    except ValueError as exc:
        logger.error(f"Unknown value in NETBOX_FILTER_CONDUCTOR: {exc}")
        nb_device_query_list = []

    return nb_device_query_list


def get_device_oob_ip(device):
    """Get out-of-band IP address for device management interface.

    Args:
        device: NetBox device object

    Returns:
        tuple: (IP address, prefix length) for management interface or None
               Example: ('192.168.1.10', 24)
    """
    import ipaddress

    try:
        oob_ip_with_prefix = None

        # First check if device has oob_ip field set
        if hasattr(device, "oob_ip") and device.oob_ip:
            oob_ip_with_prefix = device.oob_ip
        else:
            # Fall back to management interfaces
            interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)

            for interface in interfaces:
                if interface.mgmt_only:
                    # Get IP addresses assigned to this interface
                    ip_addresses = utils.nb.ipam.ip_addresses.filter(
                        assigned_object_type="dcim.interface",
                        assigned_object_id=interface.id,
                    )
                    for ip_addr in ip_addresses:
                        if ip_addr.address:
                            oob_ip_with_prefix = ip_addr.address
                            break
                    if oob_ip_with_prefix:
                        break

        if oob_ip_with_prefix:
            # Parse the IP address with prefix (e.g., "192.168.1.10/24")
            ip_interface = ipaddress.ip_interface(oob_ip_with_prefix)
            ip_address = str(ip_interface.ip)
            prefix_length = ip_interface.network.prefixlen

            logger.debug(
                f"Found OOB IP for device {device.name}: {ip_address}/{prefix_length}"
            )

            # Return tuple of (IP address, prefix length)
            return (ip_address, prefix_length)

    except Exception as e:
        logger.warning(f"Could not get OOB IP for device {device.name}: {e}")

    return None
