# SPDX-License-Identifier: Apache-2.0

import ipaddress
import yaml
from loguru import logger

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
    from .sonic.cache import get_cached_device_interfaces

    vlans = {}
    vlan_members = {}
    vlan_interfaces = {}

    try:
        # Use cached interfaces instead of separate query
        interfaces = get_cached_device_interfaces(device.id)

        # Fetch ALL IP addresses for the device in ONE query
        all_ip_addresses = list(utils.nb.ipam.ip_addresses.filter(device_id=device.id))

        # Build lookup dictionary: interface_id -> list of IPs (O(1) lookups)
        interface_ips_map = {}
        for ip_addr in all_ip_addresses:
            if ip_addr.assigned_object_id:
                if ip_addr.assigned_object_id not in interface_ips_map:
                    interface_ips_map[ip_addr.assigned_object_id] = []
                interface_ips_map[ip_addr.assigned_object_id].append(ip_addr)

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
                    # Use O(1) lookup instead of N queries
                    ip_addresses = interface_ips_map.get(interface.id, [])

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
    from .sonic.cache import get_cached_device_interfaces

    loopbacks = {}

    try:
        # Use cached interfaces instead of separate query
        interfaces = get_cached_device_interfaces(device.id)

        # Fetch ALL IP addresses for the device in ONE query
        all_ip_addresses = list(utils.nb.ipam.ip_addresses.filter(device_id=device.id))

        # Build lookup dictionary: interface_id -> list of IPs (O(1) lookups)
        interface_ips_map = {}
        for ip_addr in all_ip_addresses:
            if ip_addr.assigned_object_id:
                if ip_addr.assigned_object_id not in interface_ips_map:
                    interface_ips_map[ip_addr.assigned_object_id] = []
                interface_ips_map[ip_addr.assigned_object_id].append(ip_addr)

        for interface in interfaces:
            # Check if interface is virtual type and is a Loopback interface
            if (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
                and interface.name.startswith("Loopback")
            ):

                try:
                    # Use O(1) lookup instead of N queries
                    ip_addresses = interface_ips_map.get(interface.id, [])

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


def get_device_interface_ips(device):
    """Get IPv4 addresses assigned to device interfaces.

    Args:
        device: NetBox device object

    Returns:
        dict: Dictionary mapping interface names to their IPv4 addresses
              {
                  'interface_name': 'ip_address/prefix_length',
                  ...
              }
    """
    from .sonic.cache import get_cached_device_interfaces

    interface_ips = {}

    try:
        # Use cached interfaces instead of separate query
        interfaces = get_cached_device_interfaces(device.id)

        # Fetch ALL IP addresses for the device in ONE query
        all_ip_addresses = list(utils.nb.ipam.ip_addresses.filter(device_id=device.id))

        # Build lookup dictionary: interface_id -> list of IPs (O(1) lookups)
        interface_ips_map = {}
        for ip_addr in all_ip_addresses:
            if ip_addr.assigned_object_id:
                if ip_addr.assigned_object_id not in interface_ips_map:
                    interface_ips_map[ip_addr.assigned_object_id] = []
                interface_ips_map[ip_addr.assigned_object_id].append(ip_addr)

        for interface in interfaces:
            # Skip management interfaces and virtual interfaces for now
            if interface.mgmt_only or (
                hasattr(interface, "type")
                and interface.type
                and interface.type.value == "virtual"
            ):
                continue

            # Use O(1) lookup instead of N queries
            ip_addresses = interface_ips_map.get(interface.id, [])

            for ip_addr in ip_addresses:
                if ip_addr.address:
                    # Check if it's an IPv4 address
                    try:
                        ip_obj = ipaddress.ip_interface(ip_addr.address)
                        if ip_obj.version == 4:
                            interface_ips[interface.name] = ip_addr.address
                            logger.debug(
                                f"Found IPv4 address {ip_addr.address} on interface {interface.name} of device {device.name}"
                            )
                            break  # Only use the first IPv4 address found
                    except (ValueError, ipaddress.AddressValueError):
                        # Skip invalid IP addresses
                        continue

    except Exception as e:
        logger.warning(
            f"Could not get interface IP addresses for device {device.name}: {e}"
        )

    return interface_ips
