# SPDX-License-Identifier: Apache-2.0

from loguru import logger
import yaml

from osism import settings, utils
from osism.tasks import netbox


def get_nb_device_query_list_ironic():
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
        nb_device_query_list = yaml.safe_load(settings.NETBOX_FILTER_CONDUCTOR_IRONIC)
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
            f"Setting NETBOX_FILTER_CONDUCTOR_IRONIC needs to be an array of mappings containing supported NetBox device filters: {supported_nb_device_filters}"
        )
        nb_device_query_list = []
    except ValueError as exc:
        logger.error(f"Unknown value in NETBOX_FILTER_CONDUCTOR_IRONIC: {exc}")
        nb_device_query_list = []

    return nb_device_query_list


def get_nb_device_query_list_sonic():
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
        nb_device_query_list = yaml.safe_load(settings.NETBOX_FILTER_CONDUCTOR_SONIC)
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
            f"Setting NETBOX_FILTER_CONDUCTOR_SONIC needs to be an array of mappings containing supported NetBox device filters: {supported_nb_device_filters}"
        )
        nb_device_query_list = []
    except ValueError as exc:
        logger.error(f"Unknown value in NETBOX_FILTER_CONDUCTOR_SONIC: {exc}")
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


def get_device_vlans(device):
    """Get VLANs configured on device interfaces.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary with VLAN information
              {
                  'vlans': {vid: {'name': name, 'description': desc}},
                  'vlan_members': {vid: {'port_name': 'tagging_mode'}},
                  'vlan_interfaces': {vid: {'addresses': [ip_with_prefix, ...]}}
              }
    """
    vlans = {}
    vlan_members = {}
    vlan_interfaces = {}

    try:
        # Get all interfaces for the device and convert to list for multiple iterations
        interfaces = list(utils.nb.dcim.interfaces.filter(device_id=device.id))

        for interface in interfaces:
            # Skip management interfaces and virtual interfaces
            if interface.mgmt_only or (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
            ):
                continue

            # Process untagged VLAN
            if hasattr(interface, "untagged_vlan") and interface.untagged_vlan:
                vlan = interface.untagged_vlan
                vid = vlan.vid

                # Add VLAN info if not already present
                if vid not in vlans:
                    vlans[vid] = {
                        "name": vlan.name or f"Vlan{vid}",
                        "description": vlan.description or "",
                    }

                # Add interface to VLAN members as untagged
                if vid not in vlan_members:
                    vlan_members[vid] = {}

                # Use original NetBox interface name - conversion will be done in sonic.py
                vlan_members[vid][interface.name] = "untagged"

            # Process tagged VLANs
            if hasattr(interface, "tagged_vlans") and interface.tagged_vlans:
                for vlan in interface.tagged_vlans:
                    vid = vlan.vid

                    # Add VLAN info if not already present
                    if vid not in vlans:
                        vlans[vid] = {
                            "name": vlan.name or f"Vlan{vid}",
                            "description": vlan.description or "",
                        }

                    # Add interface to VLAN members as tagged
                    if vid not in vlan_members:
                        vlan_members[vid] = {}

                    # Use original NetBox interface name - conversion will be done in sonic.py
                    vlan_members[vid][interface.name] = "tagged"

        # Get VLAN interfaces (SVIs) - virtual interfaces with VLAN assignments
        for interface in interfaces:
            # Check if interface is virtual type and has VLAN assignment
            if (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
                and interface.name.startswith("Vlan")
            ):
                try:
                    vid = int(interface.name[4:])
                    # Get IP addresses for this VLAN interface
                    ip_addresses = utils.nb.ipam.ip_addresses.filter(
                        assigned_object_id=interface.id,
                    )

                    addresses = []
                    for ip_addr in ip_addresses:
                        if ip_addr.address:
                            addresses.append(ip_addr.address)

                    if addresses:
                        if vid not in vlan_interfaces:
                            vlan_interfaces[vid] = {}
                        # Store all IP addresses for this VLAN interface
                        vlan_interfaces[vid]["addresses"] = addresses
                except (ValueError, IndexError):
                    # Skip if interface name doesn't follow Vlan<number> pattern
                    pass

    except Exception as e:
        logger.warning(f"Could not get VLANs for device {device.name}: {e}")

    return {
        "vlans": vlans,
        "vlan_members": vlan_members,
        "vlan_interfaces": vlan_interfaces,
    }


def get_device_loopbacks(device):
    """Get Loopback interfaces configured on device.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary with Loopback information
              {
                  'loopbacks': {'Loopback0': {'addresses': [ip_with_prefix, ...]}}
              }
    """
    loopbacks = {}

    try:
        # Get all interfaces for the device
        interfaces = list(utils.nb.dcim.interfaces.filter(device_id=device.id))

        for interface in interfaces:
            # Check if interface is virtual type and is a Loopback interface
            if (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
                and interface.name.startswith("Loopback")
            ):

                try:
                    # Get IP addresses for this Loopback interface
                    ip_addresses = utils.nb.ipam.ip_addresses.filter(
                        assigned_object_id=interface.id,
                    )

                    addresses = []
                    for ip_addr in ip_addresses:
                        if ip_addr.address:
                            addresses.append(ip_addr.address)

                    if addresses:
                        loopbacks[interface.name] = {"addresses": addresses}

                except Exception as e:
                    logger.debug(
                        f"Error processing Loopback interface {interface.name}: {e}"
                    )

    except Exception as e:
        logger.warning(
            f"Could not get Loopback interfaces for device {device.name}: {e}"
        )

    return {"loopbacks": loopbacks}
