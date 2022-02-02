# Copyright OSISM GmbH, 2022
# LICENSE: CC BY-NC 4.0

import glob
import os
import sys

import pynetbox
import yaml

from osism import utils


def load_data_from_filesystem(collection=None, device=None, state=None):
    data = {}
    if not device:
        # logging.info(f"Loading collection {collection}")

        if os.path.isfile("/netbox/{CONF.collection}/{CONF.state}.yaml"):
            with open(f"/netbox/{collection}/{state}.yaml") as fp:
                data = yaml.load(fp, Loader=yaml.SafeLoader)

        for directory in glob.glob(f"/netbox/{collection}/*/"):
            with open(f"{directory}{state}.yaml") as fp:
                data_a = yaml.load(fp, Loader=yaml.SafeLoader)
            # data = data | data_a
            data = {**data_a, **data}

    elif device and collection:
        if not os.path.isfile("/netbox/{CONF.collection}/{CONF.device}/{CONF.state}.yaml"):
            # logging.error(f"State {state} for device {device} in collection {collection} is not available")
            return data

        # logging.info(f"Loading device {device} from collection {collection}")

        with open(f"/netbox/{collection}/{device}/{state}.yaml") as fp:
            data = yaml.load(fp, Loader=yaml.SafeLoader)

    elif device:
        # Try to find the collection of the specified device
        # A device can be in exactly one collection
        result = [x[0] for x in os.walk("/netbox") if device in x[0]]
        if result:
            # logging.info(f"Loading device {device}")

            try:
                with open(f"{result[0]}/{state}.yaml") as fp:
                    data = yaml.load(fp, Loader=yaml.SafeLoader)
            except:  # noqa
                # logging.error(f"State {state} for device {device} is not available")
                sys.exit(1)
        # else:
        #     logging.error(f"Device {device} is not defined in any collection")

    # else:
    #     logging.error("Specify at least a collection or a device")

    return data


def get_current_state(data):
    result = {}
    for device in data:
        device_a = utils.nb.dcim.devices.get(name=device)
        result[device] = device_a.custom_fields["device_state"]

    return result


def get_lag_interfaces(data):
    result = {}
    for device in data:
        result[device] = []
        for interface in data[device]:
            if data[device][interface]["type"] == "port-channel":
                for interface in data[device][interface]["interfaces"]:
                    if interface not in result[device]:
                        result[device].append(interface)

    return result


# Manage interfaces
def manage_interfaces(device, data):
    primary_address = None
    lag_interfaces = get_lag_interfaces(data)

    for interface in data[device]:

        if data[device][interface]["type"] in ["virtual", "port-channel", "mlag"]:
            continue

        device_a = utils.nb.dcim.devices.get(name=device)
        device_target = data[device][interface]["device"]
        device_b = utils.nb.dcim.devices.get(name=device_target)

        interface_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
        interface_b = utils.nb.dcim.interfaces.get(name=data[device][interface]["interface"], device=data[device][interface]["device"])

        if "mac_address" in data[device][interface]:
            interface_a.mac_address = data[device][interface]["mac_address"]
            interface_a.save()
        elif interface_a.mac_address:
            interface_a.mac_address = None
            interface_a.save()

        # Add all addresses to the interface
        if "addresses" in data[device][interface]:
            for address in data[device][interface]["addresses"]:
                address_a = utils.nb.ipam.ip_addresses.get(address=address)
                if type(address) == str:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    # logging.info(f"Address {address} -> {interface}")
                    if not address_a:
                        utils.nb.ipam.ip_addresses.create(
                            address=address,
                            assigned_object_type="dcim.interface",
                            assigned_object_id=interface_a.id
                        )
                else:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address["address"])
                    # logging.info(f"Address {address['address']} -> {interface}")
                    if not address_a:
                        address_a = utils.nb.ipam.ip_addresses.create(
                            assigned_object_type="dcim.interface",
                            assigned_object_id=interface_a.id,
                            **address
                        )
                    if "primary" in address and bool(address["primary"]):
                        primary_address = address_a.id
                        device_a.primary_ip4 = address_a.id
                        device_a.save()

        # Remove addresses from the interface that have been removed
        for address in utils.nb.ipam.ip_addresses.filter(device=device, interface=interface):
            delete = True
            if "addresses" in data[device][interface]:
                for address_a in data[device][interface]["addresses"]:
                    if type(address_a) == str and address_a == str(address):
                        delete = False
                    elif "address" in address_a and address_a["address"] == str(address):
                        delete = False

            if delete:
                address.delete()

        # logging.info(f"{interface_a} -> {device_target} # {interface_b}")

        # EthernetXX/Y
        if "Ethernet" in interface_a.name:
            port_a = interface_a.name[8:].split("/")[0]
        # etherXX
        elif "ether" in interface_a.name:
            port_a = interface_a.name[5:]
        else:
            port_a = interface_a.name

        # EthernetXX/Y
        if "Ethernet" in interface_b.name:
            port_b = interface_b.name[8:].split("/")[0]
        # etherXX
        elif "ether" in interface_b.name:
            port_b = interface_b.name[5:]
        else:
            port_b = interface_b.name

        near_end_a = f"{device_a.position}:{port_a}"
        if device_a.rack.name == device_b.rack.name:
            far_end_a = f"{device_b.position}:{port_b}"
        else:
            far_end_a = f"{device_b.rack.name}-{device_b.position}:{port_b}"
        label_a = f"{near_end_a} / {far_end_a}"

        near_end_b = f"{device_b.position}:{port_b}"
        if device_b.rack.name == device_a.rack.name:
            far_end_b = f"{device_a.position}:{port_a}"
        else:
            far_end_b = f"{device_a.rack.name}-{device_a.position}:{port_a}"
        label_b = f"{near_end_b} / {far_end_b}"

        interface_a.update({"label": label_a})
        interface_b.update({"label": label_b})

        connection = utils.nb.dcim.cables.get(
            termination_a_type="dcim.interface",
            termination_b_type="dcim.interface",
            termination_a_id=interface_a.id,
            termination_b_id=interface_b.id
        )

        # NOTE: also check the other direction
        if not connection:
            connection = utils.nb.dcim.cables.get(
                termination_a_type="dcim.interface",
                termination_b_type="dcim.interface",
                termination_a_id=interface_b.id,
                termination_b_id=interface_a.id
            )

        if not connection:
            try:
                connection = utils.nb.dcim.cables.create(
                    termination_a_type="dcim.interface",
                    termination_b_type="dcim.interface",
                    termination_a_id=interface_a.id,
                    termination_b_id=interface_b.id,
                    type=data[device][interface]["type"]
                )
            except pynetbox.core.query.RequestError:
                pass
                # logging.error(f"ERROR --> {e}")

        # ensure that all interfaces are enabled
        if not interface_a.enabled:
            interface_a.enabled = True
            interface_a.save()
            # logging.info(f"{device_a} # {interface_a} --> enabled")

        if not interface_b.enabled:
            interface_b.enabled = True
            interface_b.save()
            # logging.info(f"{device_b} # {interface_b} --> enabled")

        if "vlans" in data[device][interface]:
            tagged = False
            interface_a.untagged_vlan = None
            interface_a.tagged_vlans = []
            for vlan in data[device][interface]["vlans"]:
                vlan_a = utils.nb.ipam.vlans.get(vid=vlan)
                if not vlan_a:
                    try:
                        vlan_a = utils.nb.ipam.vlans.create(name=f"VLAN {vlan}", vid=vlan)
                    except pynetbox.core.query.RequestError:
                        pass
                        # logging.error(f"ERROR --> {e}")

                if data[device][interface]["vlans"][vlan] == "untagged":
                    # logging.info(f"Untagged VLAN {vlan_a.vid} -> {interface_a.name}")
                    interface_a.untagged_vlan = vlan_a.id

                    if interface_a.name not in lag_interfaces[device]:
                        # logging.info(f"Tagged VLAN {vlan_a.vid} -> {interface_b.name}")
                        interface_b.untagged_vlan = vlan_a.id

                elif vlan_a.id not in interface_a.tagged_vlans:
                    # logging.info(f"Tagged VLAN {vlan_a.vid} -> {interface_a.name}")
                    interface_a.tagged_vlans.append(vlan_a.id)

                    if interface_a.name not in lag_interfaces[device]:
                        # logging.info(f"Tagged VLAN {vlan_a.vid} -> {interface_b.name}")
                        interface_b.tagged_vlans.append(vlan_a.id)

                    tagged = True

            if tagged:
                interface_a.mode = 'tagged'

                if interface_a.name not in lag_interfaces[device]:
                    interface_b.mode = 'tagged'
            else:
                interface_a.mode = 'access'

                if interface_a.name not in lag_interfaces[device]:
                    interface_b.mode = 'access'

            interface_a.save()

            if interface_a.name not in lag_interfaces[device]:
                interface_b.save()

    # Remove the primary IP address if it is no longer set
    if not primary_address:
        device_a.primary_ip4 = None
        device_a.save()


# Manage port channels (not MLAGs)
def manage_port_channels(device, data):
    for interface in data[device]:
        if data[device][interface]["type"] == "port-channel":
            # logging.info(f"Local port channel {device} # {interface} -> {data[device][interface]['interfaces']}")
            device_a = utils.nb.dcim.devices.get(name=device)

            # Create the local port channel
            port_channel_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
            if not port_channel_a:
                try:
                    port_channel_a = utils.nb.dcim.interfaces.create(name=interface, device=device_a.id, type="lag")
                except pynetbox.core.query.RequestError:
                    pass
                    # logging.error(f"ERROR --> {e}")

            # Create the remote port channels and add the local interfaces to the local port channel
            remote_port_channels = []
            for interface_x in data[device][interface]["interfaces"]:
                interface_a = utils.nb.dcim.interfaces.get(name=interface_x, device=device)

                # NOTE: The VLANs on the Ethernet interfaces on the local devices are preserved for
                #       visibility in the Netbox.
                # interface_a.untagged_vlan = None
                # interface_a.tagged_vlans = []

                interface_a.lag = port_channel_a
                interface_a.save()

                port_channel_b_name = f"Port-Channel{data[device][interface]['channel']}"
                interface_b = utils.nb.dcim.interfaces.get(name=interface_a.connected_endpoint.name, device=interface_a.connected_endpoint.device)

                interface_b.untagged_vlan = None
                interface_b.tagged_vlans = []

                # logging.info(f"Remote port channel {interface_b.device.name} # {port_channel_b_name} -> {interface_b.device.name} # {interface_b.name} ({interface_a.name})")

                port_channel_b = utils.nb.dcim.interfaces.get(name=port_channel_b_name, device=interface_b.device)
                if not port_channel_b:
                    try:
                        port_channel_b = utils.nb.dcim.interfaces.create(name=port_channel_b_name, device=interface_b.device.id, type="lag")
                    except pynetbox.core.query.RequestError:
                        pass
                        # logging.error(f"ERROR --> {e}")

                interface_b.lag = port_channel_b
                interface_b.save()

                remote_port_channels.append(port_channel_b)

            # Assign IP addresses to the local port channel
            if "addresses" in data[device][interface]:
                for address in data[device][interface]["addresses"]:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    if type(address) == str:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address)
                        # logging.info(f"Address {address} -> {interface}")
                        if not address_a:
                            utils.nb.ipam.ip_addresses.create(
                                address=address,
                                assigned_object_type="dcim.interface",
                                assigned_object_id=port_channel_a.id
                            )
                    else:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address["address"])
                        # logging.info(f"Address {address['address']} -> {interface}")
                        if not address_a:
                            address_a = utils.nb.ipam.ip_addresses.create(
                                assigned_object_type="dcim.interface",
                                assigned_object_id=port_channel_a.id,
                                **address
                            )
                        if "primary" in address and bool(address["primary"]):
                            device_a.primary_ip4 = address_a.id
                            device_a.save()

            # Remove addresses from the local port channel that have been removed
            for address in utils.nb.ipam.ip_addresses.filter(device=device, interface=interface):
                delete = True
                if "addresses" in data[device][interface]:
                    for address_a in data[device][interface]["addresses"]:
                        if type(address_a) == str and address_a == str(address):
                            delete = False
                        elif "address" in address_a and address_a["address"] == str(address):
                            delete = False

                if delete:
                    address.delete()

            # Assign VLANs to the local port channel as well as the remote port channels
            port_channel_a.untagged_vlan = None
            port_channel_a.tagged_vlans = []
            port_channel_b.untagged_vlan = None
            port_channel_b.tagged_vlans = []

            if "vlans" in data[device][interface]:
                tagged = False
                for vlan in data[device][interface]["vlans"]:
                    vlan_a = utils.nb.ipam.vlans.get(vid=vlan)
                    if not vlan_a:
                        try:
                            vlan_a = utils.nb.ipam.vlans.create(name=f"VLAN {vlan}", vid=vlan)
                        except pynetbox.core.query.RequestError:
                            pass
                            # logging.error(f"ERROR --> {e}")

                    if data[device][interface]["vlans"][vlan] == "untagged":
                        # logging.info(f"Untagged VLAN {vlan_a.vid} -> {port_channel_a.name}")
                        port_channel_a.untagged_vlan = vlan_a.id

                        for port_channel_b in remote_port_channels:
                            # logging.info(f"Untagged VLAN {vlan_a.vid} -> {port_channel_b.name}")
                            port_channel_b.untagged_vlan = vlan_a.id
                    elif vlan_a.id not in port_channel_a.tagged_vlans:
                        # logging.info(f"Tagged VLAN {vlan_a.vid} -> {port_channel_a.name}")
                        port_channel_a.tagged_vlans.append(vlan_a.id)
                        tagged = True

                        for port_channel_b in remote_port_channels:
                            # logging.info(f"Tagged VLAN {vlan_a.vid} -> {port_channel_b.name}")
                            port_channel_b.tagged_vlans.append(vlan_a.id)

                if tagged:
                    port_channel_a.mode = 'tagged'

                    for port_channel_b in remote_port_channels:
                        port_channel_b.mode = 'tagged'
                else:
                    port_channel_a.mode = 'access'

                    for port_channel_b in remote_port_channels:
                        port_channel_b.mode = 'access'

            port_channel_a.save()
            port_channel_b.save()


# Remove local and remote port channels that no longer exist
def remove_port_channels(device, data):
    for interface in utils.nb.dcim.interfaces.filter(device=device, type="lag"):
        delete = True
        for interface_a in data[device]:
            if data[device][interface_a]["type"] == "port-channel" and str(interface) == interface_a:
                delete = False

        if delete and "Port-Channel" not in interface.name:
            members = utils.nb.dcim.interfaces.filter(lag_id=interface.id)
            for member in members:
                member.connected_endpoint.lag.delete()
            interface.delete()


# Manage virtual interfaces
def manage_virtual_interfaces(device, data):
    for interface in data[device]:
        if data[device][interface]["type"] == "virtual":
            # logging.info(f"Virtual interface {interface} for {device}")

            device_a = utils.nb.dcim.devices.get(name=device)

            interface_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
            if not interface_a:
                try:
                    interface_a = utils.nb.dcim.interfaces.create(name=interface, device=device_a.id, type="virtual", **data[device][interface]["data"])
                except pynetbox.core.query.RequestError:
                    pass
                    # logging.error(f"ERROR --> {e}")

            if "addresses" in data[device][interface]:
                for address in data[device][interface]["addresses"]:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    if type(address) == str:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address)
                        # logging.info(f"Address {address} -> {interface}")
                        if not address_a:
                            utils.nb.ipam.ip_addresses.create(
                                address=address,
                                assigned_object_type="dcim.interface",
                                assigned_object_id=interface_a.id
                            )
                    else:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address["address"])
                        # logging.info(f"Address {address['address']} -> {interface}")
                        if not address_a:
                            address_a = utils.nb.ipam.ip_addresses.create(
                                assigned_object_type="dcim.interface",
                                assigned_object_id=interface_a.id,
                                **address
                            )
                        if "primary" in address and bool(address["primary"]):
                            device_a.primary_ip4 = address_a.id
                            device_a.save()

            # Remove addresses from the interface that have been removed
            for address in utils.nb.ipam.ip_addresses.filter(device=device, interface=interface):
                delete = True
                if "addresses" in data[device][interface]:
                    for address_a in data[device][interface]["addresses"]:
                        if type(address_a) == str and address_a == str(address):
                            delete = False
                        elif "address" in address_a and address_a["address"] == str(address):
                            delete = False

                if delete:
                    address.delete()

            if "vlans" in data[device][interface]:
                tagged = False
                interface_a.untagged_vlan = None
                interface_a.tagged_vlans = []
                for vlan in data[device][interface]["vlans"]:
                    vlan_a = utils.nb.ipam.vlans.get(vid=vlan)
                    if not vlan_a:
                        try:
                            vlan_a = utils.nb.ipam.vlans.create(name=f"VLAN {vlan}", vid=vlan)
                        except pynetbox.core.query.RequestError:
                            pass
                            # logging.error(f"ERROR --> {e}")

                    if data[device][interface]["vlans"][vlan] == "untagged":
                        interface_a.untagged_vlan = vlan_a.id
                    elif vlan_a.id not in interface_a.tagged_vlans:
                        interface_a.tagged_vlans.append(vlan_a.id)
                        tagged = True

                if tagged:
                    interface_a.mode = 'tagged'
                else:
                    interface_a.mode = 'access'
                interface_a.save()


# Remove virtual interfaces that no longer exist
def remove_virtual_interfaces(device, data):
    for interface in utils.nb.dcim.interfaces.filter(device=device, type="virtual"):
        delete = True
        for interface_a in data[device]:
            if data[device][interface_a]["type"] == "virtual" and str(interface) == interface_a:
                delete = False

        if delete:
            interface.delete()


# Manage MLAG devices (not port channels)
def manage_mlag_devices(device, data):
    for interface in data[device]:
        if data[device][interface]["type"] == "mlag":
            data_a = data[device][interface]["data"]
            device_a = utils.nb.dcim.devices.get(name=device)

            # logging.info(f"Local port channel {device} # Port-Channel{data_a['channel']}")

            port_channel_a = utils.nb.dcim.interfaces.get(name=f"Port-Channel{data_a['channel']}", device=device)
            if not port_channel_a:
                try:
                    port_channel_a = utils.nb.dcim.interfaces.create(name=f"Port-Channel{data_a['channel']}", device=device_a.id, type="lag")
                except pynetbox.core.query.RequestError:
                    # logging.error(f"ERROR --> {e}")
                    pass

            for interface_x in data[device][interface]["interfaces"]:
                interface_a = utils.nb.dcim.interfaces.get(name=interface_x, device=device)
                interface_a.lag = port_channel_a
                interface_a.save()

            # logging.info(f"Virtual interface {data_a['vlan']} for {device}")
            interface_a = utils.nb.dcim.interfaces.get(name=f"Vlan{data_a['vlan']}", device=device)
            if not interface_a:
                try:
                    interface_a = utils.nb.dcim.interfaces.create(name=f"Vlan{data_a['vlan']}", device=device_a.id, type="virtual")
                except pynetbox.core.query.RequestError:
                    pass
                    # logging.error(f"ERROR --> {e}")

            vlan_a = utils.nb.ipam.vlans.get(vid=data_a['vlan'])
            interface_a.untagged_vlan = vlan_a
            interface_a.parent = port_channel_a
            interface_a.save()

            # logging.info(f"Address {data_a['address']} -> {interface_a.name}")
            address_a = utils.nb.ipam.ip_addresses.get(address=data_a["address"])
            if not address_a:
                utils.nb.ipam.ip_addresses.create(
                    address=data_a["address"],
                    assigned_object_type="dcim.interface",
                    assigned_object_id=interface_a.id
                )


def set_device_state(device, state):
    # logging.info(f"Set state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {
        "device_state": state
    }
    device_a.save()


def set_device_transition(device, transition):
    # logging.info(f"Set transition of device {device} = {transition}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {
        "device_transition": transition
    }
    device_a.save()
