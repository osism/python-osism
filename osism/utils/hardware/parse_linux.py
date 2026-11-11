# SPDX-License-Identifier: Apache-2.0

"""Parsers for the raw document of the Linux collector (``remote_linux``)."""

import json
import re
from typing import Any, Dict, List, Optional

from osism.utils.hardware import natural_key, normalize_mac

_PERMANENT_ADDRESS = re.compile(r"Permanent address:\s*(\S+)")
# The domain has four digits, or more behind a bridge such as Intel VMD
_PCI_ADDRESS = re.compile(r"^[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$", re.I)


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
