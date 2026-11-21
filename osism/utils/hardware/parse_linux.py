# SPDX-License-Identifier: Apache-2.0

"""Parsers for the raw document of the Linux collector (``remote_linux``)."""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from osism.utils.hardware import (
    natural_key,
    normalize_date_code,
    normalize_mac,
    transceiver_record,
)

_PERMANENT_ADDRESS = re.compile(r"Permanent address:\s*(\S+)")
# The domain has four digits, or more behind a bridge such as Intel VMD
_PCI_ADDRESS = re.compile(r"^[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$", re.I)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_DBM = re.compile(r"(-?\d+(?:\.\d+)?)\s*dBm")
_CHANNEL = re.compile(r"\(Channel\s*(\d+)\)", re.IGNORECASE)
_PCI_NAME = re.compile(r"^(.*?)\s*\[([0-9a-fA-F]{4})\]$")
_IB_RATE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*Gb/sec")


def command_output(result: Any) -> Optional[str]:
    """Return the stdout of a collected command, or None when it failed."""
    if not isinstance(result, dict) or result.get("rc") != 0:
        return None
    return result.get("out") or ""


def parse_ip_link(result: Any) -> Dict[str, Dict[str, Any]]:
    """Index the output of ``ip -j -d link show`` by interface name."""
    output = command_output(result)
    if not output:
        return {}
    try:
        links = json.loads(output)
    except ValueError:
        return {}
    if not isinstance(links, list):
        return {}
    return {
        link["ifname"]: link
        for link in links
        if isinstance(link, dict) and link.get("ifname")
    }


def parse_permanent_address(result: Any) -> Optional[str]:
    """Return the MAC address printed by ``ethtool -P``."""
    match = _PERMANENT_ADDRESS.search(command_output(result) or "")
    return normalize_mac(match.group(1)) if match else None


def oper_status(operstate: Optional[str], carrier: Optional[str]) -> Optional[str]:
    """Reduce operstate and carrier to ``up``, ``down`` or None (unknown)."""
    state = (operstate or "").lower()
    if state == "up":
        return "up"
    if state in ("down", "lowerlayerdown", "notpresent", "dormant"):
        return "down"
    if carrier == "1":
        return "up"
    if carrier == "0":
        return "down"
    return None


def pci_address(value: Any) -> Optional[str]:
    """Return a PCI address, or None for the address of another bus.

    The collector reports the bus address of the device behind a port. For
    a USB NIC, such as the host interface of a BMC, that is a USB path
    (``1-7.2:2.0``), which says nothing to ``lspci`` or NetBox.
    """
    text = str(value or "").strip()
    return text if _PCI_ADDRESS.match(text) else None


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_port(name: str, raw: Dict[str, Any], link: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise identity and link state of one port.

    Args:
        name: Kernel name of the port
        raw: Entry of the port in the collector document
        link: Entry of the port in ``ip -j -d link show``, may be empty
    """
    sysfs = raw.get("sysfs") or {}
    mac = normalize_mac(link.get("address") or sysfs.get("address"))
    # A bond member reports the MAC of the bond as its address. The address
    # burned into the NIC is what NetBox documents.
    permanent_mac = (
        parse_permanent_address(raw.get("ethtool_P"))
        or normalize_mac(link.get("permaddr"))
        or mac
    )

    admin_status = None
    if "flags" in link:
        admin_status = "up" if "UP" in (link.get("flags") or []) else "down"

    physfn = raw.get("physfn") or []
    return {
        "name": name,
        "kind": raw.get("kind") or "physical",
        "parent": physfn[0] if physfn else None,
        "alias": link.get("ifalias") or None,
        "altnames": list(link.get("altnames") or []),
        "admin_status": admin_status,
        "oper_status": oper_status(
            link.get("operstate") or sysfs.get("operstate"), sysfs.get("carrier")
        ),
        "speed": _positive_int(sysfs.get("speed")),
        "duplex": sysfs.get("duplex") or None,
        "mtu": _positive_int(link.get("mtu") or sysfs.get("mtu")),
        "mac": mac,
        "permanent_mac": permanent_mac,
        "bond": link.get("master") or None,
        "pci_address": pci_address(raw.get("pci")),
    }


def parse_ports(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the ports of a node in natural name order."""
    links = parse_ip_link(document.get("ip_link"))
    ports = [
        parse_port(name, raw or {}, links.get(name) or {})
        for name, raw in (document.get("ports") or {}).items()
    ]
    return sorted(ports, key=lambda port: natural_key(port["name"]))


def parse_key_values(text: Optional[str]) -> List[Tuple[str, str]]:
    """Split ``Key: Value`` lines as printed by ethtool.

    Only the first colon separates key and value, since values contain
    colons themselves (``Vendor OUI : 00:90:65``). A line without a colon
    continues the value of the line before it. Keys can repeat.
    """
    pairs: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if separator:
            pairs.append((key.strip(), value.strip()))
        elif pairs:
            last_key, last_value = pairs[-1]
            pairs[-1] = (last_key, f"{last_value} {line.strip()}".strip())
    return pairs


def _first(pairs: List[Tuple[str, str]], *keys: str) -> Optional[str]:
    wanted = [key.lower() for key in keys]
    for key in wanted:
        for name, value in pairs:
            if name.lower() == key and value:
                return value
    return None


def _described(value: Optional[str]) -> Optional[str]:
    """Return the text in parentheses of ``0x03 (SFP)``, else the value."""
    if not value:
        return None
    start, end = value.find("("), value.rfind(")")
    if 0 <= start < end:
        return value[start + 1 : end].strip() or None
    return value


def _number(value: Optional[str]) -> Optional[float]:
    match = _NUMBER.search(value or "")
    return float(match.group(0)) if match else None


def parse_ethtool(result: Any) -> Dict[str, Any]:
    """Parse the link settings printed by ``ethtool <interface>``."""
    pairs = parse_key_values(command_output(result))

    speed = _first(pairs, "Speed")
    speed_match = re.match(r"(\d+)Mb/s", speed or "")
    duplex = (_first(pairs, "Duplex") or "").lower()
    autoneg = (_first(pairs, "Auto-negotiation") or "").lower()
    link = (_first(pairs, "Link detected") or "").lower()
    return {
        "speed": int(speed_match.group(1)) if speed_match else None,
        "duplex": duplex if duplex in ("full", "half") else None,
        "autoneg": {"on": True, "off": False}.get(autoneg),
        "port_type": _first(pairs, "Port"),
        "link_detected": {"yes": True, "no": False}.get(link),
    }


def parse_ethtool_driver(result: Any) -> Dict[str, Any]:
    """Parse driver and firmware information printed by ``ethtool -i``."""
    pairs = parse_key_values(command_output(result))
    return {
        "driver": _first(pairs, "driver"),
        "driver_version": _first(pairs, "version"),
        "firmware_version": _first(pairs, "firmware-version"),
        "pci_address": _first(pairs, "bus-info"),
    }


def parse_ethtool_fec(result: Any) -> Optional[str]:
    """Return the active FEC encoding printed by ``ethtool --show-fec``."""
    pairs = parse_key_values(command_output(result))
    active = _first(pairs, "Active FEC encoding", "Active FEC encodings")
    return active.lower() if active else None


def _parse_dom(pairs: List[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
    """Extract the diagnostic readings of a module, or None without any."""
    lanes: Dict[int, Dict[str, Any]] = {}

    def lane(key: str) -> Dict[str, Any]:
        match = _CHANNEL.search(key)
        number = int(match.group(1)) if match else 1
        return lanes.setdefault(
            number, {"rx_power": None, "tx_power": None, "tx_bias": None}
        )

    for key, value in pairs:
        name = key.lower()
        # Threshold and alarm lines repeat the names of the readings
        if "threshold" in name or "alarm" in name or "warning" in name:
            continue
        power = _DBM.search(value)
        if "bias current" in name:
            lane(key)["tx_bias"] = _number(value)
        elif power and ("receiver signal" in name or "rcvr signal" in name):
            lane(key)["rx_power"] = float(power.group(1))
        elif power and ("laser output power" in name or "transmit avg" in name):
            lane(key)["tx_power"] = float(power.group(1))

    temperature = _number(_first(pairs, "Module temperature"))
    voltage = _number(_first(pairs, "Module voltage"))
    if temperature is None and voltage is None and not lanes:
        return None
    return {
        "temperature": temperature,
        "voltage": voltage,
        "lanes": [lanes[number] for number in sorted(lanes)],
    }


def parse_module(result: Any, dom: bool = False) -> Dict[str, Any]:
    """Parse the module EEPROM printed by ``ethtool -m``.

    ``ethtool -m`` fails for a port without a cage and for an empty cage.
    Both are reported as ``present = False``.

    Args:
        result: Collected command result
        dom: Add the diagnostic readings as ``dom``
    """
    pairs = parse_key_values(command_output(result))
    identifier = _first(pairs, "Identifier")
    if not identifier and not _first(pairs, "Vendor name", "Vendor PN"):
        return transceiver_record(False)

    record = transceiver_record(True)
    form_factor = _described(identifier)
    record["form_factor"] = form_factor.split()[0] if form_factor else None
    record["connector"] = _described(_first(pairs, "Connector"))
    record["vendor"] = _first(pairs, "Vendor name")
    record["vendor_oui"] = _first(pairs, "Vendor OUI")
    record["part_number"] = _first(pairs, "Vendor PN")
    record["serial"] = _first(pairs, "Vendor SN")
    record["revision"] = _first(pairs, "Vendor rev")
    record["date_code"] = normalize_date_code(_first(pairs, "Date code"))
    record["firmware_active"] = _first(pairs, "Active firmware version")
    record["firmware_inactive"] = _first(pairs, "Inactive firmware version")

    types = [value for key, value in pairs if key.lower() == "transceiver type"]
    record["compliance"] = "; ".join(types) or None

    for key, value in pairs:
        name = key.lower()
        if not (name.startswith("length") or name == "cable assembly length"):
            continue
        number = _number(value)
        if number:
            record["cable_length"] = value
            break

    wavelength = _first(pairs, "Laser wavelength")
    if _number(wavelength):
        record["wavelength"] = wavelength

    if dom:
        record["dom"] = _parse_dom(pairs)
    return record


def _pci_name(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split ``Mellanox Technologies [15b3]`` into name and ID."""
    if not value:
        return None, None
    match = _PCI_NAME.match(value.strip())
    if match:
        return match.group(1).strip() or None, match.group(2).lower()
    return value.strip(), None


def parse_lspci(result: Any) -> Dict[str, Any]:
    """Parse one device of ``lspci -D -vmm -nn``."""
    pairs = parse_key_values(command_output(result))
    vendor, vendor_id = _pci_name(_first(pairs, "Vendor"))
    model, model_id = _pci_name(_first(pairs, "Device"))
    subsystem_vendor, _ = _pci_name(_first(pairs, "SVendor"))
    subsystem_model, _ = _pci_name(_first(pairs, "SDevice"))
    return {
        "vendor": vendor,
        "vendor_id": vendor_id,
        "model": model,
        "model_id": model_id,
        "subsystem_vendor": subsystem_vendor,
        "subsystem_model": subsystem_model,
        "revision": _first(pairs, "Rev"),
    }


def parse_devlink(result: Any) -> Dict[str, Any]:
    """Parse ``devlink -j dev info`` of one PCI function.

    What devlink reports depends on the driver. Missing values stay None.
    """
    empty: Dict[str, Any] = {"serial": None, "board_id": None, "firmware": None}
    output = command_output(result)
    if not output:
        return empty
    try:
        info = json.loads(output).get("info") or {}
    except (ValueError, AttributeError):
        return empty
    if not isinstance(info, dict) or not info:
        return empty

    device = next(iter(info.values()))
    if not isinstance(device, dict):
        return empty
    versions = device.get("versions") or {}
    fixed = versions.get("fixed") or {}
    firmware = {
        kind: versions[kind]
        for kind in ("running", "stored")
        if isinstance(versions.get(kind), dict) and versions[kind]
    }
    return {
        # bnxt_en reports the serial number of the board next to the one of
        # the PCI device, which is derived from the MAC address.
        "serial": device.get("board.serial_number") or device.get("serial_number"),
        "board_id": fixed.get("board.id") or fixed.get("fw.psid"),
        "firmware": firmware or None,
    }


def parse_infiniband(raw: Any) -> Dict[str, Any]:
    """Parse state and rate of an InfiniBand port from sysfs.

    The state reads ``4: ACTIVE``, the rate ``100 Gb/sec (4X EDR)``.
    """
    if not isinstance(raw, dict):
        return {"oper_status": None, "speed": None}
    state = (raw.get("state") or "").upper()
    rate = _IB_RATE.match(raw.get("rate") or "")
    status = None
    if state:
        status = "up" if "ACTIVE" in state else "down"
    return {
        "oper_status": status,
        "speed": int(float(rate.group(1)) * 1000) if rate else None,
    }


def parse_system(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return vendor, model and serial number of the node from DMI."""
    dmi = document.get("dmi") or {}
    return {
        "system_vendor": dmi.get("sys_vendor") or None,
        "system_model": dmi.get("product_name") or None,
        "serial": dmi.get("product_serial") or None,
    }


def parse_inventory(
    document: Dict[str, Any], dom: bool = False
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return the hardware view of a node.

    Returns:
        ``(system, interfaces)``: the node itself, and one record per port
        holding the port fields plus ``nic`` and ``transceiver``
    """
    interfaces = []
    for port in parse_ports(document):
        raw = (document.get("ports") or {}).get(port["name"]) or {}
        settings = parse_ethtool(raw.get("ethtool"))
        driver = parse_ethtool_driver(raw.get("ethtool_i"))
        pci = parse_lspci(raw.get("lspci"))
        devlink = parse_devlink(raw.get("devlink"))

        port["speed"] = settings["speed"] or port["speed"]
        port["duplex"] = settings["duplex"] or (port["duplex"] or "").lower() or None
        port["autoneg"] = settings["autoneg"]
        port["port_type"] = settings["port_type"]
        port["fec"] = parse_ethtool_fec(raw.get("ethtool_fec"))

        if port["kind"] == "infiniband":
            link = parse_infiniband(raw.get("infiniband"))
            port["oper_status"] = link["oper_status"] or port["oper_status"]
            port["speed"] = link["speed"] or port["speed"]

        port["nic"] = {
            # bus-info of a USB NIC is a USB path (usb-0000:00:14.0-7.2)
            "pci_address": pci_address(driver["pci_address"])
            or port.get("pci_address"),
            "vendor": pci["vendor"],
            "model": pci["model"],
            "subsystem_vendor": pci["subsystem_vendor"],
            "subsystem_model": pci["subsystem_model"],
            "revision": pci["revision"],
            "serial": devlink["serial"],
            "board_id": devlink["board_id"],
            "driver": driver["driver"],
            "driver_version": driver["driver_version"],
            "firmware_version": driver["firmware_version"],
            "firmware": devlink["firmware"],
        }
        # The module sits in the cage of the physical function. A virtual
        # function has none of its own.
        if port["kind"] == "vf":
            port["transceiver"] = transceiver_record(None)
        else:
            port["transceiver"] = parse_module(raw.get("ethtool_m"), dom)
        interfaces.append(port)

    return parse_system(document), interfaces
