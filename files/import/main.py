#!/usr/bin/env python3

from collections import Counter
from datetime import datetime
import argparse
import glob
import os

import pynetbox
import yaml

from osism import settings


counter = Counter(added=0, updated=0, manufacturer=0)


def slugFormat(name):
    return name.lower().replace(" ", "_")


YAML_EXTENSIONS = ["yml", "yaml"]


def getFiles(vendors=None):
    files = []
    discoveredVendors = []
    base_path = settings.BASE_PATH
    if vendors:
        for r, d, f in os.walk(base_path):
            for folder in d:
                for vendor in vendors:
                    if vendor.lower() == folder.lower():
                        discoveredVendors.append(
                            {"name": folder, "slug": slugFormat(folder)}
                        )
                        for extension in YAML_EXTENSIONS:
                            files.extend(
                                glob.glob(base_path + folder + f"/*.{extension}")
                            )
    else:
        for r, d, f in os.walk(base_path):
            for folder in d:
                if folder.lower() != "Testing":
                    discoveredVendors.append(
                        {"name": folder, "slug": slugFormat(folder)}
                    )
        for extension in YAML_EXTENSIONS:
            files.extend(glob.glob(base_path + f"[!Testing]*/*.{extension}"))
    return files, discoveredVendors


def readYAMl(files):
    deviceTypes = []
    manufacturers = []
    for file in files:
        with open(file, "r") as stream:
            try:
                data = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)
                continue
            manufacturer = data["manufacturer"]
            data["manufacturer"] = {}
            data["manufacturer"]["name"] = manufacturer
            data["manufacturer"]["slug"] = slugFormat(manufacturer)
        deviceTypes.append(data)
        manufacturers.append(manufacturer)
    return deviceTypes


def createManufacturers(vendors, nb):
    all_manufacturers = {str(item): item for item in nb.dcim.manufacturers.all()}
    need_manufacturers = []
    for vendor in vendors:
        try:
            manGet = all_manufacturers[vendor["name"]]
            print(f"Manufacturer Exists: {manGet.name} - {manGet.id}")
        except KeyError:
            need_manufacturers.append(vendor)

    if not need_manufacturers:
        return

    try:
        manSuccess = nb.dcim.manufacturers.create(need_manufacturers)
        for man in manSuccess:
            print(f"Manufacturer Created: {man.name} - " + f"{man.id}")
            counter.update({"manufacturer": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createInterfaces(interfaces, deviceType, nb):
    all_interfaces = {
        str(item): item
        for item in nb.dcim.interface_templates.filter(devicetype_id=deviceType)
    }
    need_interfaces = []
    for interface in interfaces:
        try:
            ifGet = all_interfaces[interface["name"]]
            print(
                f"Interface Template Exists: {ifGet.name} - {ifGet.type}"
                + f" - {ifGet.device_type.id} - {ifGet.id}"
            )
        except KeyError:
            interface["device_type"] = deviceType
            need_interfaces.append(interface)

    if not need_interfaces:
        return

    try:
        ifSuccess = nb.dcim.interface_templates.create(need_interfaces)
        for intf in ifSuccess:
            print(
                f"Interface Template Created: {intf.name} - "
                + f"{intf.type} - {intf.device_type.id} - "
                + f"{intf.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createConsolePorts(consoleports, deviceType, nb):
    all_consoleports = {
        str(item): item
        for item in nb.dcim.console_port_templates.filter(devicetype_id=deviceType)
    }
    need_consoleports = []
    for consoleport in consoleports:
        try:
            cpGet = all_consoleports[consoleport["name"]]
            print(
                f"Console Port Template Exists: {cpGet.name} - "
                + f"{cpGet.type} - {cpGet.device_type.id} - {cpGet.id}"
            )
        except KeyError:
            consoleport["device_type"] = deviceType
            need_consoleports.append(consoleport)

    if not need_consoleports:
        return

    try:
        cpSuccess = nb.dcim.console_port_templates.create(need_consoleports)
        for port in cpSuccess:
            print(
                f"Console Port Created: {port.name} - "
                + f"{port.type} - {port.device_type.id} - "
                + f"{port.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createPowerPorts(powerports, deviceType, nb):
    all_power_ports = {
        str(item): item
        for item in nb.dcim.power_port_templates.filter(devicetype_id=deviceType)
    }
    need_power_ports = []
    for powerport in powerports:
        try:
            ppGet = all_power_ports[powerport["name"]]
            print(
                f"Power Port Template Exists: {ppGet.name} - "
                + f"{ppGet.type} - {ppGet.device_type.id} - {ppGet.id}"
            )
        except KeyError:
            powerport["device_type"] = deviceType
            need_power_ports.append(powerport)

    if not need_power_ports:
        return

    try:
        ppSuccess = nb.dcim.power_port_templates.create(need_power_ports)
        for pp in ppSuccess:
            print(
                f"Interface Template Created: {pp.name} - "
                + f"{pp.type} - {pp.device_type.id} - "
                + f"{pp.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createConsoleServerPorts(consoleserverports, deviceType, nb):
    all_consoleserverports = {
        str(item): item
        for item in nb.dcim.console_server_port_templates.filter(
            devicetype_id=deviceType
        )
    }
    need_consoleserverports = []
    for csport in consoleserverports:
        try:
            cspGet = all_consoleserverports[csport["name"]]
            print(
                f"Console Server Port Template Exists: {cspGet.name} - "
                + f"{cspGet.type} - {cspGet.device_type.id} - "
                + f"{cspGet.id}"
            )
        except KeyError:
            csport["device_type"] = deviceType
            need_consoleserverports.append(csport)

    if not need_consoleserverports:
        return

    try:
        cspSuccess = nb.dcim.console_server_port_templates.create(
            need_consoleserverports
        )
        for csp in cspSuccess:
            print(
                f"Console Server Port Created: {csp.name} - "
                + f"{csp.type} - {csp.device_type.id} - "
                + f"{csp.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createFrontPorts(frontports, deviceType, nb):
    all_frontports = {
        str(item): item
        for item in nb.dcim.front_port_templates.filter(devicetype_id=deviceType)
    }
    need_frontports = []
    for frontport in frontports:
        try:
            fpGet = all_frontports[frontport["name"]]
            print(
                f"Front Port Template Exists: {fpGet.name} - "
                + f"{fpGet.type} - {fpGet.device_type.id} - {fpGet.id}"
            )
        except KeyError:
            frontport["device_type"] = deviceType
            need_frontports.append(frontport)

    if not need_frontports:
        return

    all_rearports = {
        str(item): item
        for item in nb.dcim.rear_port_templates.filter(devicetype_id=deviceType)
    }
    for port in need_frontports:
        try:
            rpGet = all_rearports[port["rear_port"]]
            port["rear_port"] = rpGet.id
        except KeyError:
            print(
                f'Could not find Rear Port for Front Port: {port["name"]} - '
                + f'{port["type"]} - {deviceType}'
            )

    try:
        fpSuccess = nb.dcim.front_port_templates.create(need_frontports)
        for fp in fpSuccess:
            print(
                f"Front Port Created: {fp.name} - "
                + f"{fp.type} - {fp.device_type.id} - "
                + f"{fp.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createRearPorts(rearports, deviceType, nb):
    all_rearports = {
        str(item): item
        for item in nb.dcim.rear_port_templates.filter(devicetype_id=deviceType)
    }
    need_rearports = []
    for rearport in rearports:
        try:
            rpGet = all_rearports[rearport["name"]]
            print(
                f"Rear Port Template Exists: {rpGet.name} - {rpGet.type}"
                + f" - {rpGet.device_type.id} - {rpGet.id}"
            )
        except KeyError:
            rearport["device_type"] = deviceType
            need_rearports.append(rearport)

    if not need_rearports:
        return

    try:
        rpSuccess = nb.dcim.rear_port_templates.create(need_rearports)
        for rp in rpSuccess:
            print(
                f"Rear Port Created: {rp.name} - {rp.type}"
                + f" - {rp.device_type.id} - {rp.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createDeviceBays(devicebays, deviceType, nb):
    all_devicebays = {
        str(item): item
        for item in nb.dcim.device_bay_templates.filter(devicetype_id=deviceType)
    }
    need_devicebays = []
    for devicebay in devicebays:
        try:
            dbGet = all_devicebays[devicebay["name"]]
            print(
                f"Device Bay Template Exists: {dbGet.name} - "
                + f"{dbGet.device_type.id} - {dbGet.id}"
            )
        except KeyError:
            devicebay["device_type"] = deviceType
            need_devicebays.append(devicebay)

    if not need_devicebays:
        return

    try:
        dbSuccess = nb.dcim.device_bay_templates.create(need_devicebays)
        for db in dbSuccess:
            print(
                f"Device Bay Created: {db.name} - " + f"{db.device_type.id} - {db.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createPowerOutlets(poweroutlets, deviceType, nb):
    all_poweroutlets = {
        str(item): item
        for item in nb.dcim.power_outlet_templates.filter(devicetype_id=deviceType)
    }
    need_poweroutlets = []
    for poweroutlet in poweroutlets:
        try:
            poGet = all_poweroutlets[poweroutlet["name"]]
            print(
                f"Power Outlet Template Exists: {poGet.name} - "
                + f"{poGet.type} - {poGet.device_type.id} - {poGet.id}"
            )
        except KeyError:
            poweroutlet["device_type"] = deviceType
            need_poweroutlets.append(poweroutlet)

    if not need_poweroutlets:
        return

    all_power_ports = {
        str(item): item
        for item in nb.dcim.power_port_templates.filter(devicetype_id=deviceType)
    }
    for outlet in need_poweroutlets:
        try:
            ppGet = all_power_ports[outlet["power_port"]]
            outlet["power_port"] = ppGet.id
        except KeyError:
            pass

    try:
        poSuccess = nb.dcim.power_outlet_templates.create(need_poweroutlets)
        for po in poSuccess:
            print(
                f"Power Outlet Created: {po.name} - "
                + f"{po.type} - {po.device_type.id} - "
                + f"{po.id}"
            )
            counter.update({"updated": 1})
    except pynetbox.RequestError as e:
        print(e.error)


def createDeviceTypes(deviceTypes, nb):
    all_device_types = {str(item): item for item in nb.dcim.device_types.all()}
    for deviceType in deviceTypes:
        try:
            dt = all_device_types[deviceType["model"]]
            print(
                f"Device Type Exists: {dt.manufacturer.name} - "
                + f"{dt.model} - {dt.id}"
            )
        except KeyError:
            try:
                dt = nb.dcim.device_types.create(deviceType)
                counter.update({"added": 1})
                print(
                    f"Device Type Created: {dt.manufacturer.name} - "
                    + f"{dt.model} - {dt.id}"
                )
            except pynetbox.RequestError as e:
                print(e.error)

        if "interfaces" in deviceType:
            createInterfaces(deviceType["interfaces"], dt.id, nb)
        if "power-ports" in deviceType:
            createPowerPorts(deviceType["power-ports"], dt.id, nb)
        if "power-port" in deviceType:
            createPowerPorts(deviceType["power-port"], dt.id, nb)
        if "console-ports" in deviceType:
            createConsolePorts(deviceType["console-ports"], dt.id, nb)
        if "power-outlets" in deviceType:
            createPowerOutlets(deviceType["power-outlets"], dt.id, nb)
        if "console-server-ports" in deviceType:
            createConsoleServerPorts(deviceType["console-server-ports"], dt.id, nb)
        if "rear-ports" in deviceType:
            createRearPorts(deviceType["rear-ports"], dt.id, nb)
        if "front-ports" in deviceType:
            createFrontPorts(deviceType["front-ports"], dt.id, nb)
        if "device-bays" in deviceType:
            createDeviceBays(deviceType["device-bays"], dt.id, nb)


def main():

    cwd = os.getcwd()
    startTime = datetime.now()

    nbUrl = settings.NETBOX_URL
    nbToken = settings.NETBOX_TOKEN
    nb = pynetbox.api(nbUrl, token=nbToken)

    if settings.IGNORE_SSL_ERRORS:
        import requests

        requests.packages.urllib3.disable_warnings()
        session = requests.Session()
        session.verify = False
        nb.http_session = session

    VENDORS = settings.VENDORS

    parser = argparse.ArgumentParser(description="Import Netbox Device Types")
    parser.add_argument(
        "--vendors",
        nargs="+",
        default=VENDORS,
        help="List of vendors to import eg. apc cisco",
    )
    args = parser.parse_args()

    if not args.vendors:
        print("No Vendors Specified, Gathering All Device-Types")
        files, vendors = getFiles()
    else:
        print("Vendor Specified, Gathering All Matching Device-Types")
        files, vendors = getFiles(args.vendors)

    print(str(len(vendors)) + " Vendors Found")
    print(str(len(files)) + " Device-Types Found")
    deviceTypes = readYAMl(files)
    createManufacturers(vendors, nb)
    createDeviceTypes(deviceTypes, nb)

    print("---")
    print("Script took {} to run".format(datetime.now() - startTime))
    print("{} devices created".format(counter["added"]))
    print("{} interfaces/ports updated".format(counter["updated"]))
    print("{} manufacturers created".format(counter["manufacturer"]))


if __name__ == "__main__":
    main()
