# Copyright OSISM GmbH, 2022-2023
# LICENSE: CC BY-NC 4.0

import glob
import os

from loguru import logger
from pottery import Redlock
import pynetbox
import yaml

from osism import utils
from osism.actions import generate_configuration, deploy_configuration


def load_data_from_filesystem(collection=None, device=None, state=None):
    """Loads all known data for a given device or an entire collection
    from the file system (/netbox) in a given state.
    """

    if not state or state in ["0", "None"]:
        state = "a"

    data = {}
    if not device:
        logger.info(f"Loading collection {collection}")

        if os.path.isfile("/netbox/{CONF.collection}/{CONF.state}.yaml"):
            with open(f"/netbox/{collection}/{state}.yaml") as fp:
                data = yaml.load(fp, Loader=yaml.SafeLoader)

        for directory in glob.glob(f"/netbox/{collection}/*/"):
            with open(f"{directory}{state}.yaml") as fp:
                data_a = yaml.load(fp, Loader=yaml.SafeLoader)
            # data = data | data_a
            data = {**data_a, **data}

    elif device and collection:
        if not os.path.isfile(
            "/netbox/{CONF.collection}/{CONF.device}/{CONF.state}.yaml"
        ):
            logger.error(
                f"State {state} for device {device} in collection {collection} is not available"
            )
            return data

        logger.info(f"Loading device {device} from collection {collection}")

        with open(f"/netbox/{collection}/{device}/{state}.yaml") as fp:
            data = yaml.load(fp, Loader=yaml.SafeLoader)

    elif device:
        # Try to find the collection of the specified device
        # A device can be in exactly one collection
        result = [x[0] for x in os.walk("/netbox") if device in x[0]]
        if result:
            logger.info(f"Loading device {device}")

            try:
                with open(f"{result[0]}/{state}.yaml") as fp:
                    data = yaml.load(fp, Loader=yaml.SafeLoader)
            except:  # noqa
                logger.error(f"State {state} for device {device} is not available")
                return data
        else:
            logger.error(f"Device {device} is not defined in any collection")

    else:
        logger.error("Specify at least a collection or a device")

    return data


def get_state(device):
    """Gets the state (device_state) stored in the Netbox for a  device."""

    result = None
    device_a = utils.nb.dcim.devices.get(name=device)
    result = device_a.custom_fields["device_state"]

    return result


def get_states(devices):
    """Gets the state (device_state) stored in the Netbox for a list of devices."""

    result = {}
    for device in devices:
        device_a = utils.nb.dcim.devices.get(name=device)
        result[device] = device_a.custom_fields["device_state"]

    return result


def get_transitions(devices):
    """Gets the transition (device_transition) stored in the Netbox for a list of devices."""

    result = {}
    for device in devices:
        device_a = utils.nb.dcim.devices.get(name=device)
        result[device] = device_a.custom_fields["device_transition"]

    return result


def get_lag_interfaces(data):
    """Returns all defined LAGs."""

    result = {}
    for device in data:
        result[device] = []
        for interface in data[device]:
            if data[device][interface]["type"] == "port-channel":
                for interface in data[device][interface]["interfaces"]:
                    if interface not in result[device]:
                        result[device].append(interface)

    return result


def manage_interfaces(device, data):
    """Manage interfaces."""
    primary_address = None
    lag_interfaces = get_lag_interfaces(data)

    for interface in data[device]:

        if data[device][interface]["type"] in ["virtual", "port-channel", "mlag"]:
            continue

        device_a = utils.nb.dcim.devices.get(name=device)
        device_target = data[device][interface]["device"]
        device_b = utils.nb.dcim.devices.get(name=device_target)

        interface_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
        interface_b = utils.nb.dcim.interfaces.get(
            name=data[device][interface]["interface"],
            device=data[device][interface]["device"],
        )

        if not interface_a:
            logger.error(f"{device} # {interface} --> not found")

        if not interface_b:
            logger.error(
                f"{data[device][interface]['device']} # {data[device][interface]['interface']} --> not found"
            )

        # Ignore interfaces without an mac address
        try:
            if "mac_address" in data[device][interface]:
                interface_a.mac_address = data[device][interface]["mac_address"]
                interface_a.save()
            elif interface_a.mac_address:
                interface_a.mac_address = None
                interface_a.save()
        except:  # noqa E722
            pass

        if interface_a and "data" in data[device][interface]:
            interface_a.update(data[device][interface]["data"])

            if "enabled" in data[device][interface]["data"] and interface_b:
                interface_b.enabled = bool(data[device][interface]["data"]["enabled"])

        # Add all addresses to the interface
        if "addresses" in data[device][interface]:
            for address in data[device][interface]["addresses"]:
                address_a = utils.nb.ipam.ip_addresses.get(address=address)
                if type(address) == str:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    logger.info(f"Address {address} -> {interface}")
                    if not address_a:
                        utils.nb.ipam.ip_addresses.create(
                            address=address,
                            assigned_object_type="dcim.interface",
                            assigned_object_id=interface_a.id,
                        )
                else:
                    address_a = utils.nb.ipam.ip_addresses.get(
                        address=address["address"]
                    )
                    logger.info(f"Address {address['address']} -> {interface}")
                    if not address_a:
                        address_a = utils.nb.ipam.ip_addresses.create(
                            assigned_object_type="dcim.interface",
                            assigned_object_id=interface_a.id,
                            **address,
                        )
                    if "primary" in address and bool(address["primary"]):
                        primary_address = address_a.id
                        device_a.primary_ip4 = address_a.id
                        device_a.save()

        # Remove addresses from the interface that have been removed
        for address in utils.nb.ipam.ip_addresses.filter(
            device=device, interface=interface
        ):
            delete = True
            if "addresses" in data[device][interface]:
                for address_a in data[device][interface]["addresses"]:
                    if type(address_a) == str and address_a == str(address):
                        delete = False
                    elif "address" in address_a and address_a["address"] == str(
                        address
                    ):
                        delete = False

            if delete:
                address.delete()

        logger.info(f"{interface_a} -> {device_target} # {interface_b}")

        if interface_a.label:
            port_a = interface_a.label
        # EthernetXX/Y
        elif "Ethernet" in interface_a.name and "/" in interface_a.name:
            port_a = interface_a.name[8:].split("/")[0]
        # EthernetXX
        elif "Ethernet" in interface_a.name:
            port_a = interface_a.name[8:]
        # etherXX
        elif "ether" in interface_a.name:
            port_a = interface_a.name[5:]
        # ethXX
        elif "eth" in interface_a.name:
            port_a = interface_a.name[3:]
        # sfp-sfpplusXX
        elif "sfp-sfpplus" in interface_a.name:
            port_a = interface_a.name[11:]
        # qsfp-qsfpplusXX
        elif "qsfp-qsfpplus" in interface_a.name:
            port_a = interface_a.name[13:]
        # qsfpplusXX
        elif "qsfpplus" in interface_a.name:
            port_a = interface_a.name[8:]
        else:
            port_a = interface_a.name

        if interface_b.label:
            port_b = interface_b.label
        # EthernetXX/Y
        elif "Ethernet" in interface_b.name and "/" in interface_b.name:
            port_b = interface_b.name[8:].split("/")[0]
        # EthernetXX
        elif "Ethernet" in interface_b.name:
            port_b = interface_b.name[8:]
        # etherXX
        elif "ether" in interface_b.name:
            port_b = interface_b.name[5:]
        # ethXX
        elif "eth" in interface_b.name:
            port_b = interface_b.name[3:]
        # sfp-sfpplusXX
        elif "sfp-sfpplus" in interface_b.name:
            port_b = interface_b.name[11:]
        # qsfp-qsfpplusXX
        elif "qsfp-qsfpplus" in interface_b.name:
            port_b = interface_b.name[13:]
        # qsfpplusXX
        elif "qsfpplus" in interface_b.name:
            port_b = interface_b.name[8:]
        else:
            port_b = interface_b.name

        try:
            position_a = int(device_a.position)
        except:
            # NOTE: dirty workaround so that it works for the moment also for nodes without
            #       a position in housings
            position_a = 999

        try:
            position_b = int(device_b.position)
        except:
            # NOTE: dirty workaround so that it works for the moment also for nodes without
            #       a position in housings
            position_b = 999

        near_end_a = f"{position_a}:{port_a}"
        if device_a.rack.name == device_b.rack.name:
            far_end_a = f"{position_b}:{port_b}"
        else:
            far_end_a = f"{device_b.rack.name}-{position_b}:{port_b}"
        label_a = f"{near_end_a} / {far_end_a}"

        near_end_b = f"{position_b}:{port_b}"
        if device_b.rack.name == device_a.rack.name:
            far_end_b = f"{position_a}:{port_a}"
        else:
            far_end_b = f"{device_a.rack.name}-{position_a}:{port_a}"
        label_b = f"{near_end_b} / {far_end_b}"

        interface_a.update({"description": label_a})
        interface_b.update({"description": label_b})

        termination_a = {"object_type": "dcim.interface", "object_id": interface_a.id}
        termination_b = {"object_type": "dcim.interface", "object_id": interface_b.id}

        try:
            connection = utils.nb.dcim.cables.create(
                a_terminations=[termination_a],
                b_terminations=[termination_b],
                type=data[device][interface]["type"],
            )
        except pynetbox.core.query.RequestError as e:
            # The "Duplicate termination found" error can be ignored
            if "Duplicate termination found" not in e.error:
                logger.error(f"ERROR --> {e.error}")
            pass

        # ensure that all interfaces are enabled that should be enabled
        if not interface_a.enabled:

            if "enabled" in data[device][interface]["data"]:
                interface_a.enabled = bool(data[device][interface]["data"]["enabled"])
            else:
                interface_a.enabled = True

            if interface_a.enabled:
                logger.info(f"{device_a} # {interface_a} --> enabled")
            else:
                logger.info(f"{device_a} # {interface_a} --> disabled")

            interface_a.save()

        if not interface_b.enabled:
            if (
                "data" in data[device][interface]
                and "enabled" in data[device][interface]["data"]
            ):
                interface_b.enabled = bool(data[device][interface]["data"]["enabled"])
            else:
                interface_b.enabled = True

            if interface_b.enabled:
                logger.info(f"{device_b} # {interface_b} --> enabled")
            else:
                logger.info(f"{device_b} # {interface_b} --> disabled")

            interface_b.save()

        if "vlans" in data[device][interface]:
            tagged = False
            interface_a.untagged_vlan = None
            interface_a.tagged_vlans = []
            for vlan in data[device][interface]["vlans"]:
                vlan_a = utils.nb.ipam.vlans.get(vid=vlan)
                if not vlan_a:
                    try:
                        vlan_a = utils.nb.ipam.vlans.create(
                            name=f"VLAN {vlan}", vid=vlan
                        )
                    except pynetbox.core.query.RequestError as e:
                        logger.error(f"ERROR --> {e}")
                        pass

                if data[device][interface]["vlans"][vlan] == "untagged":
                    logger.info(f"Untagged VLAN {vlan_a.vid} -> {interface_a.name}")
                    interface_a.untagged_vlan = vlan_a.id

                    if interface_a.name not in lag_interfaces[device]:
                        logger.info(f"Tagged VLAN {vlan_a.vid} -> {interface_b.name}")
                        interface_b.untagged_vlan = vlan_a.id

                elif vlan_a.id not in interface_a.tagged_vlans:
                    logger.info(f"Tagged VLAN {vlan_a.vid} -> {interface_a.name}")
                    interface_a.tagged_vlans.append(vlan_a.id)

                    if interface_a.name not in lag_interfaces[device]:
                        logger.info(f"Tagged VLAN {vlan_a.vid} -> {interface_b.name}")
                        interface_b.tagged_vlans.append(vlan_a.id)

                    tagged = True

            if tagged:
                interface_a.mode = "tagged"

                if interface_a.name not in lag_interfaces[device]:
                    interface_b.mode = "tagged"
            else:
                interface_a.mode = "access"

                if interface_a.name not in lag_interfaces[device]:
                    interface_b.mode = "access"

            interface_a.save()

            if interface_a.name not in lag_interfaces[device]:
                interface_b.save()

    # Remove the primary IP address if it is no longer set
    if not primary_address:
        device_a.primary_ip4 = None
        device_a.save()


def manage_port_channels(device, data):
    """Manage port channels (not MLAGs)."""

    for interface in data[device]:
        if data[device][interface]["type"] == "port-channel":
            logger.info(
                f"Local port channel {device} # {interface} -> {data[device][interface]['interfaces']}"
            )
            device_a = utils.nb.dcim.devices.get(name=device)

            # Create the local port channel
            port_channel_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
            if not port_channel_a:
                try:
                    port_channel_a = utils.nb.dcim.interfaces.create(
                        name=interface, device=device_a.id, type="lag"
                    )
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"ERROR --> {e}")
                    pass

            # Create the remote port channels and add the local interfaces to the local port channel
            remote_port_channels = []
            for interface_x in data[device][interface]["interfaces"]:
                interface_a = utils.nb.dcim.interfaces.get(
                    name=interface_x, device=device
                )

                # NOTE: The VLANs on the Ethernet interfaces on the local devices are preserved for
                #       visibility in the Netbox.
                # interface_a.untagged_vlan = None
                # interface_a.tagged_vlans = []

                interface_a.lag = port_channel_a
                interface_a.save()

                port_channel_b_name = (
                    f"Port-Channel{data[device][interface]['channel']}"
                )
                interface_b = utils.nb.dcim.interfaces.get(
                    name=interface_a.connected_endpoint.name,
                    device=interface_a.connected_endpoint.device,
                )

                interface_b.untagged_vlan = None
                interface_b.tagged_vlans = []

                logger.info(
                    f"Remote port channel {interface_b.device.name} # {port_channel_b_name} -> {interface_b.device.name} # {interface_b.name} ({interface_a.name})"
                )

                port_channel_b = utils.nb.dcim.interfaces.get(
                    name=port_channel_b_name, device=interface_b.device
                )
                if not port_channel_b:
                    try:
                        port_channel_b = utils.nb.dcim.interfaces.create(
                            name=port_channel_b_name,
                            device=interface_b.device.id,
                            type="lag",
                        )
                    except pynetbox.core.query.RequestError as e:
                        logger.error(f"ERROR --> {e}")
                        pass

                interface_b.lag = port_channel_b
                interface_b.save()

                remote_port_channels.append(port_channel_b)

            # Assign IP addresses to the local port channel
            if "addresses" in data[device][interface]:
                for address in data[device][interface]["addresses"]:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    if type(address) == str:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address)
                        logger.info(f"Address {address} -> {interface}")
                        if not address_a:
                            utils.nb.ipam.ip_addresses.create(
                                address=address,
                                assigned_object_type="dcim.interface",
                                assigned_object_id=port_channel_a.id,
                            )
                    else:
                        address_a = utils.nb.ipam.ip_addresses.get(
                            address=address["address"]
                        )
                        logger.info(f"Address {address['address']} -> {interface}")
                        if not address_a:
                            address_a = utils.nb.ipam.ip_addresses.create(
                                assigned_object_type="dcim.interface",
                                assigned_object_id=port_channel_a.id,
                                **address,
                            )
                        if "primary" in address and bool(address["primary"]):
                            device_a.primary_ip4 = address_a.id
                            device_a.save()

            # Remove addresses from the local port channel that have been removed
            for address in utils.nb.ipam.ip_addresses.filter(
                device=device, interface=interface
            ):
                delete = True
                if "addresses" in data[device][interface]:
                    for address_a in data[device][interface]["addresses"]:
                        if type(address_a) == str and address_a == str(address):
                            delete = False
                        elif "address" in address_a and address_a["address"] == str(
                            address
                        ):
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
                            vlan_a = utils.nb.ipam.vlans.create(
                                name=f"VLAN {vlan}", vid=vlan
                            )
                        except pynetbox.core.query.RequestError as e:
                            logger.error(f"ERROR --> {e}")
                            pass

                    if data[device][interface]["vlans"][vlan] == "untagged":
                        logger.info(
                            f"Untagged VLAN {vlan_a.vid} -> {port_channel_a.name}"
                        )
                        port_channel_a.untagged_vlan = vlan_a.id

                        for port_channel_b in remote_port_channels:
                            logger.info(
                                f"Untagged VLAN {vlan_a.vid} -> {port_channel_b.name}"
                            )
                            port_channel_b.untagged_vlan = vlan_a.id
                    elif vlan_a.id not in port_channel_a.tagged_vlans:
                        logger.info(
                            f"Tagged VLAN {vlan_a.vid} -> {port_channel_a.name}"
                        )
                        port_channel_a.tagged_vlans.append(vlan_a.id)
                        tagged = True

                        for port_channel_b in remote_port_channels:
                            logger.info(
                                f"Tagged VLAN {vlan_a.vid} -> {port_channel_b.name}"
                            )
                            port_channel_b.tagged_vlans.append(vlan_a.id)

                if tagged:
                    port_channel_a.mode = "tagged"

                    for port_channel_b in remote_port_channels:
                        port_channel_b.mode = "tagged"
                else:
                    port_channel_a.mode = "access"

                    for port_channel_b in remote_port_channels:
                        port_channel_b.mode = "access"

            port_channel_a.save()
            port_channel_b.save()


def remove_port_channels(device, data):
    """Remove local and remote port channels that no longer exist."""

    for interface in utils.nb.dcim.interfaces.filter(device=device, type="lag"):
        delete = True
        for interface_a in data[device]:
            if (
                data[device][interface_a]["type"] == "port-channel"
                and str(interface) == interface_a
            ):
                delete = False

        if delete and "Port-Channel" not in interface.name:
            members = utils.nb.dcim.interfaces.filter(lag_id=interface.id)
            for member in members:
                member.connected_endpoint.lag.delete()
            interface.delete()


def manage_virtual_interfaces(device, data):
    """Manage virtual interfaces."""

    for interface in data[device]:
        if data[device][interface]["type"] == "virtual":
            logger.info(f"Virtual interface {interface} for {device}")

            device_a = utils.nb.dcim.devices.get(name=device)

            interface_a = utils.nb.dcim.interfaces.get(name=interface, device=device)
            if not interface_a:
                try:
                    interface_a = utils.nb.dcim.interfaces.create(
                        name=interface,
                        device=device_a.id,
                        type="virtual",
                        **data[device][interface]["data"],
                    )
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"ERROR --> {e}")
                    pass

            if "addresses" in data[device][interface]:
                for address in data[device][interface]["addresses"]:
                    address_a = utils.nb.ipam.ip_addresses.get(address=address)
                    if type(address) == str:
                        address_a = utils.nb.ipam.ip_addresses.get(address=address)
                        logger.info(f"Address {address} -> {interface}")
                        if not address_a:
                            utils.nb.ipam.ip_addresses.create(
                                address=address,
                                assigned_object_type="dcim.interface",
                                assigned_object_id=interface_a.id,
                            )
                    else:
                        address_a = utils.nb.ipam.ip_addresses.get(
                            address=address["address"]
                        )
                        logger.info(f"Address {address['address']} -> {interface}")
                        if not address_a:
                            address_a = utils.nb.ipam.ip_addresses.create(
                                assigned_object_type="dcim.interface",
                                assigned_object_id=interface_a.id,
                                **address,
                            )
                        if "primary" in address and bool(address["primary"]):
                            device_a.primary_ip4 = address_a.id
                            device_a.save()

            # Remove addresses from the interface that have been removed
            for address in utils.nb.ipam.ip_addresses.filter(
                device=device, interface=interface
            ):
                delete = True
                if "addresses" in data[device][interface]:
                    for address_a in data[device][interface]["addresses"]:
                        if type(address_a) == str and address_a == str(address):
                            delete = False
                        elif "address" in address_a and address_a["address"] == str(
                            address
                        ):
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
                            vlan_a = utils.nb.ipam.vlans.create(
                                name=f"VLAN {vlan}", vid=vlan
                            )
                        except pynetbox.core.query.RequestError as e:
                            logger.error(f"ERROR --> {e}")
                            pass

                    if data[device][interface]["vlans"][vlan] == "untagged":
                        interface_a.untagged_vlan = vlan_a.id
                    elif vlan_a.id not in interface_a.tagged_vlans:
                        interface_a.tagged_vlans.append(vlan_a.id)
                        tagged = True

                if tagged:
                    interface_a.mode = "tagged"
                else:
                    interface_a.mode = "access"
                interface_a.save()


def remove_virtual_interfaces(device, data):
    """Remove virtual interfaces that no longer exist."""

    for interface in utils.nb.dcim.interfaces.filter(device=device, type="virtual"):
        delete = True
        for interface_a in data[device]:
            if (
                data[device][interface_a]["type"] == "virtual"
                and str(interface) == interface_a
            ):
                delete = False

        if delete:
            interface.delete()


def manage_mlag_devices(device, data):
    """Manage MLAG devices (not port channels)."""

    for interface in data[device]:
        if data[device][interface]["type"] == "mlag":
            data_a = data[device][interface]["data"]
            device_a = utils.nb.dcim.devices.get(name=device)

            logger.info(
                f"Local port channel {device} # Port-Channel{data_a['channel']}"
            )

            port_channel_a = utils.nb.dcim.interfaces.get(
                name=f"Port-Channel{data_a['channel']}", device=device
            )
            if not port_channel_a:
                try:
                    port_channel_a = utils.nb.dcim.interfaces.create(
                        name=f"Port-Channel{data_a['channel']}",
                        device=device_a.id,
                        type="lag",
                    )
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"ERROR --> {e}")
                    pass

            for interface_x in data[device][interface]["interfaces"]:
                interface_a = utils.nb.dcim.interfaces.get(
                    name=interface_x, device=device
                )
                interface_a.lag = port_channel_a
                interface_a.save()

            logger.info(f"Virtual interface {data_a['vlan']} for {device}")
            interface_a = utils.nb.dcim.interfaces.get(
                name=f"Vlan{data_a['vlan']}", device=device
            )
            if not interface_a:
                try:
                    interface_a = utils.nb.dcim.interfaces.create(
                        name=f"Vlan{data_a['vlan']}", device=device_a.id, type="virtual"
                    )
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"ERROR --> {e}")
                    pass

            vlan_a = utils.nb.ipam.vlans.get(vid=data_a["vlan"])
            interface_a.untagged_vlan = vlan_a
            interface_a.parent = port_channel_a
            interface_a.save()

            # logger.info(f"Address {data_a['address']} -> {interface_a.name}")
            address_a = utils.nb.ipam.ip_addresses.get(address=data_a["address"])
            if not address_a:
                utils.nb.ipam.ip_addresses.create(
                    address=data_a["address"],
                    assigned_object_type="dcim.interface",
                    assigned_object_id=interface_a.id,
                )


def set_maintenance(device, state):
    """Set the maintenance state for a device in the Netbox."""

    logger.info(f"Set maintenance state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"maintenance": state}
    device_a.save()


def set_state(device, state, state_type):
    """Set the state for a device in the Netbox."""

    lock = Redlock(key=f"lock_state_{device}", masters={utils.redis})
    lock.acquire()

    if state_type == "power":
        set_power_state(device, state)
    elif state_type == "provision":
        set_provision_state(device, state)
    elif state_type == "introspection":
        set_introspection_state(device, state)
    elif state_type == "ironic":
        set_ironic_state(device, state)
    elif state_type == "deployment":
        set_deployment_state(device, state)
    else:
        set_device_state(device, state)

    lock.release()


def set_provision_state(device, state):
    """Set the provision state (provision_state) for a device in the Netbox."""

    logger.info(f"Set provision state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"provision_state": state}
    device_a.save()


def set_ironic_state(device, state):
    """Set the ironic state (ironic_state) for a device in the Netbox."""

    logger.info(f"Set ironic state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"ironic_state": state}
    device_a.save()


def set_introspection_state(device, state):
    """Set the introspection state (introspection_state) for a device in the Netbox."""

    logger.info(f"Set introspection state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"introspection_state": state}
    device_a.save()


def set_deployment_state(device, state):
    """Set the deployment state (deployment_state) for a device in the Netbox."""

    logger.info(f"Set deployment state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"deployment_state": state}
    device_a.save()


def set_power_state(device, state):
    """Set the power state (power_state) for a device in the Netbox."""

    logger.info(f"Set power state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"power_state": state}
    device_a.save()


def set_device_state(device, state):
    """Set the state (device_state) for a device in the Netbox."""

    logger.info(f"Set state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"device_state": state}
    device_a.save()


def set_device_transition(device, transition):
    """Set the transition (device_transition) for a device in the Netbox."""

    logger.info(f"Set transition of device {device} = {transition}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"device_transition": transition}
    device_a.save()


def get_device_state(device, states):
    """Get the state (device_state) for a device in the Netbox."""

    return states[device]


def get_device_transition(device, transitions):
    """Get the transition (device_transition) for a device in the Netbox."""

    return transitions[device]


def get_connected_devices(device, data):
    """Get all devices that are connected to a device in a certain state."""

    result = []

    if device not in data:
        return result

    for interface in data[device]:
        if "device" in data[device][interface]:
            result.append(data[device][interface]["device"])

    return result


def run(device, state=None, data={}, enforce=False):
    """Transition a device to a specific state."""

    # If no state is specified use the state that is stored in the Netbox
    if not state or state in ["0", "None"]:
        state = get_state(device)

        # If the state in the Netbox is 0/None then set the state to a
        if state in ["0", "None"]:
            state = "a"

    if not data:
        data = load_data_from_filesystem(None, device, state)

    states = get_states(data.keys())
    current_state = get_device_state(device, states)

    # Device is already in the target state, no transition necessary
    if not enforce and current_state == state:
        logger.info(f"Device {device} is already in state {state}")
        return

    transitions = get_transitions(data.keys())
    current_transition = get_device_transition(device, transitions)

    if current_state and current_state not in ["0", "None"]:
        current_data = load_data_from_filesystem(None, device, current_state)
    else:
        current_data = {}

    # One transition is already running, no second transition possible
    if not enforce and current_transition and current_transition != "0":
        logger.info(f"{device} is already in transit")
        return

    # Get connected devices in source and target state
    connected_devices = set(
        get_connected_devices(device, current_data)
        + get_connected_devices(device, data)
    )
    logger.info(connected_devices)

    # Allow only one active transition per device
    lock = Redlock(key=f"lock_{device}", masters={utils.redis}, auto_release_time=120)
    lock.acquire()

    # transition: from-to, phase 1 (modifications in the Netbox)
    transition = f"from_{states[device]}-to_{state}-phase_1"
    set_device_transition(device, transition)

    manage_interfaces(device, data)
    manage_port_channels(device, data)
    remove_port_channels(device, data)
    manage_virtual_interfaces(device, data)
    remove_virtual_interfaces(device, data)
    manage_mlag_devices(device, data)

    set_device_state(device, f"{state}-phase_1")

    # transition: from-to, phase 2 (generate the new configuration)
    transition = f"from_{states[device]}-to_{state}-phase_2"
    set_device_transition(device, transition)

    for connected_device in [x for x in connected_devices if x]:
        generate_configuration.for_device(connected_device)

    set_device_state(device, f"{state}-phase_2")

    # transition: from-to, phase 3 (deploy the new configuration)
    transition = f"from_{states[device]}-to_{state}-phase_3"

    for connected_device in [x for x in connected_devices if x]:
        deploy_configuration.for_device(connected_device)

    set_device_transition(device, transition)
    set_device_state(device, f"{state}-phase_3")

    # transition: from-to, phase 4 (validate the deployed configuration)
    transition = f"from_{states[device]}-to_{state}-phase_4"
    set_device_transition(device, transition)

    # for connected_device in connected_devices:
    #     validate_configuration.for_device(connected_device)

    set_device_state(device, f"{state}-phase_4")

    # target state reached
    transition = ""
    set_device_transition(device, transition)
    set_device_state(device, f"{state}")

    lock.release()
