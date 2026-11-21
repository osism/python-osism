# SPDX-License-Identifier: Apache-2.0

"""Matching of live ports to NetBox interfaces.

The NetBox interfaces of all devices of a report are fetched in bulk and
turned into plain data right away. Each live port is then matched to at most
one NetBox interface, and the method that produced the match is recorded, so
a wrong or missing match is visible in the report.
"""

from dataclasses import dataclass, field
import re
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from osism.utils.hardware import normalize_mac

VIRTUAL_TYPES = {"virtual", "lag", "bridge"}
MAPPING_NONE = "none"

_SONIC_NAME = re.compile(r"^Ethernet\d+$")


@dataclass
class Endpoint:
    """Far end of a cable path: a device and one of its interfaces."""

    device: str
    interface: str
    device_id: Optional[int] = None
    interface_id: Optional[int] = None


@dataclass
class NetboxInterface:
    """A NetBox interface reduced to what the reports need.

    ``endpoints`` is the far end of the complete cable path, through patch
    panels. It is empty when there is no cable, and also when the path does
    not end at a device interface; ``path_incomplete`` tells the two apart.
    """

    id: int
    device_id: Optional[int]
    device: str
    name: str
    label: str = ""
    type: str = ""
    mgmt_only: bool = False
    macs: List[str] = field(default_factory=list)
    has_cable: bool = False
    endpoints: List[Endpoint] = field(default_factory=list)

    @property
    def is_virtual(self) -> bool:
        return self.type in VIRTUAL_TYPES

    @property
    def path_incomplete(self) -> bool:
        return self.has_cable and not self.endpoints


@dataclass
class Match:
    """NetBox interface a live port was matched to, and how."""

    interface: Optional[NetboxInterface] = None
    method: str = MAPPING_NONE


def interface_from_netbox(data: Dict[str, Any]) -> NetboxInterface:
    """Build a ``NetboxInterface`` from the plain data of an API record."""
    device = data.get("device") or {}
    interface_type = data.get("type")
    if isinstance(interface_type, dict):
        interface_type = interface_type.get("value")

    # mac_address is the only field before NetBox 4.2. Later releases keep
    # the addresses as objects of their own and list them in mac_addresses.
    candidates = [data.get("mac_address")]
    primary = data.get("primary_mac_address")
    if isinstance(primary, dict):
        candidates.append(primary.get("mac_address"))
    for entry in data.get("mac_addresses") or []:
        candidates.append(
            entry.get("mac_address") if isinstance(entry, dict) else entry
        )
    macs: List[str] = []
    for candidate in candidates:
        mac = normalize_mac(candidate)
        if mac and mac not in macs:
            macs.append(mac)

    endpoints: List[Endpoint] = []
    endpoint_type = data.get("connected_endpoints_type")
    if data.get("connected_endpoints_reachable") and endpoint_type in (
        None,
        "dcim.interface",
    ):
        for endpoint in data.get("connected_endpoints") or []:
            if not isinstance(endpoint, dict):
                continue
            peer = endpoint.get("device")
            if not isinstance(peer, dict) or not peer.get("name"):
                continue
            if not endpoint.get("name"):
                continue
            endpoints.append(
                Endpoint(
                    device=peer["name"],
                    interface=endpoint["name"],
                    device_id=peer.get("id"),
                    interface_id=endpoint.get("id"),
                )
            )

    return NetboxInterface(
        id=data["id"],
        device_id=device.get("id"),
        device=device.get("name") or "",
        name=data.get("name") or "",
        label=data.get("label") or "",
        type=interface_type or "",
        mgmt_only=bool(data.get("mgmt_only")),
        macs=macs,
        has_cable=bool(data.get("cable")),
        endpoints=endpoints,
    )


def fetch_interfaces(
    nb, device_ids: Iterable[int], chunk_size: int = 50
) -> Dict[int, List[NetboxInterface]]:
    """Fetch the interfaces of many devices with few requests.

    Records are converted with ``dict()``, which only reads what the list
    response contains. Reading a missing attribute from a pynetbox record
    would fetch the record again, once per interface.

    Returns:
        Interfaces per device ID; every requested ID is present
    """
    ids = sorted(set(device_ids))
    interfaces: Dict[int, List[NetboxInterface]] = {device_id: [] for device_id in ids}
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        for record in nb.dcim.interfaces.filter(device_id=chunk):
            interface = interface_from_netbox(dict(record))
            if interface.device_id is not None:
                interfaces.setdefault(interface.device_id, []).append(interface)
    return interfaces


def physical_interfaces(
    interfaces: Iterable[NetboxInterface], include_mgmt: bool = True
) -> List[NetboxInterface]:
    """Drop virtual and LAG interfaces, and management ones on request."""
    return [
        interface
        for interface in interfaces
        if not interface.is_virtual and (include_mgmt or not interface.mgmt_only)
    ]


def sonic_name_index(
    device_id: Optional[int],
    device_name: str,
    hwsku: Optional[str],
    interfaces: Sequence[NetboxInterface],
) -> Dict[str, NetboxInterface]:
    """Index the NetBox interfaces of a switch by their SONiC port name.

    The translation is the one the SONiC config generator uses
    (``convert_netbox_interface_to_sonic``), so it needs the HWSKU of the
    device and the matching ``port_config`` file. Without them the index is
    empty and the mapping falls back to alias and name.

    Args:
        interfaces: All interfaces of the device, including virtual ones;
            the translation looks at them to detect breakout ports
    """
    if not hwsku or device_id is None:
        return {}

    # Imported here: the conductor package is expensive to import.
    from osism.tasks.conductor.sonic.cache import get_interface_cache
    from osism.tasks.conductor.sonic.interface import (
        convert_netbox_interface_to_sonic,
        get_port_config,
    )

    if not get_port_config(hwsku):
        return {}

    # The translation reads the interfaces of the device from this cache and
    # would otherwise fetch them again, with one request per switch.
    get_interface_cache().set_device_interfaces(device_id, list(interfaces))
    device = SimpleNamespace(
        id=device_id,
        name=device_name,
        custom_fields={"sonic_parameters": {"hwsku": hwsku}},
    )

    index: Dict[str, NetboxInterface] = {}
    for interface in interfaces:
        if interface.is_virtual or interface.mgmt_only:
            continue
        if interface.name.startswith("Ethernet"):
            continue
        try:
            sonic_name = convert_netbox_interface_to_sonic(interface.name, device)
        except Exception:
            continue
        # The function returns its input when it cannot translate it.
        if _SONIC_NAME.match(sonic_name or ""):
            index.setdefault(sonic_name, interface)
    return index


class _Matcher:
    """Keeps a NetBox interface from being matched to two ports."""

    def __init__(self, interfaces: Sequence[NetboxInterface]):
        self.interfaces = list(interfaces)
        self.matches: Dict[str, Match] = {}
        self.used: set = set()

    def assign(
        self, port: Dict[str, Any], interface: Optional[NetboxInterface], method: str
    ):
        if interface is None or port["name"] in self.matches:
            return
        if interface.id in self.used:
            return
        self.matches[port["name"]] = Match(interface, method)
        self.used.add(interface.id)

    def free(self) -> List[NetboxInterface]:
        return [i for i in self.interfaces if i.id not in self.used]

    def result(
        self, ports: Sequence[Dict[str, Any]]
    ) -> Tuple[Dict[str, Match], List[NetboxInterface]]:
        for port in ports:
            self.matches.setdefault(port["name"], Match())
        return self.matches, self.free()


def _unique(interfaces: Iterable[NetboxInterface], key) -> Dict[str, NetboxInterface]:
    index: Dict[str, NetboxInterface] = {}
    for interface in interfaces:
        value = key(interface)
        if value:
            index.setdefault(value, interface)
    return index


def map_switch_ports(
    ports: Sequence[Dict[str, Any]],
    interfaces: Sequence[NetboxInterface],
    sonic_index: Optional[Dict[str, NetboxInterface]] = None,
) -> Tuple[Dict[str, Match], List[NetboxInterface]]:
    """Match the ports of a SONiC switch to its NetBox interfaces.

    Front-panel ports are matched by ``port-config`` (translation through
    the HWSKU port config), then ``alias`` (the live alias is the NetBox
    name), then ``name`` (the NetBox interface is called ``EthernetN``).

    The management port (kind ``mgmt``) is matched against the ``mgmt_only``
    interfaces by ``mac``, then ``name``, and finally as the only
    ``mgmt_only`` interface of the device (``mgmt-only``).

    Returns:
        ``(matches, unmatched)``: a ``Match`` per port name, and the NetBox
        interfaces no port was matched to
    """
    matcher = _Matcher(interfaces)
    allowed = {interface.id for interface in interfaces}
    front = [i for i in interfaces if not i.mgmt_only]
    mgmt = [i for i in interfaces if i.mgmt_only]
    front_ports = [port for port in ports if port.get("kind") != "mgmt"]
    mgmt_ports = [port for port in ports if port.get("kind") == "mgmt"]

    for port in front_ports:
        candidate = (sonic_index or {}).get(port["name"])
        if candidate is not None and candidate.id in allowed:
            matcher.assign(port, candidate, "port-config")

    by_name = _unique(front, lambda interface: interface.name)
    for port in front_ports:
        matcher.assign(port, by_name.get(port.get("alias") or ""), "alias")
    for port in front_ports:
        matcher.assign(port, by_name.get(port["name"]), "name")

    for port in mgmt_ports:
        mac = port.get("permanent_mac") or port.get("mac")
        for interface in mgmt:
            if mac and mac in interface.macs:
                matcher.assign(port, interface, "mac")
    mgmt_by_name = _unique(mgmt, lambda interface: interface.name)
    for port in mgmt_ports:
        matcher.assign(port, mgmt_by_name.get(port["name"]), "name")
    if len(mgmt) == 1 and len(mgmt_ports) == 1:
        matcher.assign(mgmt_ports[0], mgmt[0], "mgmt-only")

    return matcher.result(ports)


def same_system(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two system names case-insensitively, with and without domain."""
    if not left or not right:
        return False
    left, right = left.lower(), right.lower()
    return left == right or left.split(".")[0] == right.split(".")[0]


def neighbour_port_names(neighbour: Dict[str, Any]) -> List[str]:
    """Return the names an LLDP neighbour gives its port, best first.

    These are the port ID and the port description. RouterOS announces a
    port that is member of a bridge as ``<bridge>/<port>`` (``bridge/ether9``)
    with the subtype ``ifname``; the name of the port alone is added for it.
    A number after the slash is not a name: ``Ethernet1/12`` stays whole.
    """
    port_id = neighbour.get("port_id")
    names = [value for value in (port_id, neighbour.get("port_description")) if value]
    if port_id and neighbour.get("port_id_type") == "ifname" and "/" in port_id:
        member = port_id.rsplit("/", 1)[1]
        if member and not member.isdigit() and member not in names:
            names.append(member)
    return names


def neighbour_is_endpoint(neighbour: Dict[str, Any], endpoint: Endpoint) -> bool:
    """Return True when an LLDP neighbour announces itself as an endpoint."""
    if not same_system(neighbour.get("system_name"), endpoint.device):
        return False
    return endpoint.interface in neighbour_port_names(neighbour)


def map_node_ports(
    ports: Sequence[Dict[str, Any]],
    interfaces: Sequence[NetboxInterface],
    neighbours: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[Dict[str, Match], List[NetboxInterface]]:
    """Match the ports of a Linux node to its NetBox interfaces.

    The order is ``mac`` (permanent MAC of the port is a MAC of the NetBox
    interface), ``name`` (kernel name or an altname is the NetBox name),
    ``label`` (kernel name is the NetBox label), and ``lldp`` (the LLDP
    neighbour of the port is the cable peer of exactly one NetBox interface
    that is still unmatched).

    Returns:
        ``(matches, unmatched)``: a ``Match`` per port name, and the NetBox
        interfaces no port was matched to
    """
    matcher = _Matcher(interfaces)

    by_mac: Dict[str, NetboxInterface] = {}
    for interface in interfaces:
        for mac in interface.macs:
            by_mac.setdefault(mac, interface)
    for port in ports:
        matcher.assign(port, by_mac.get(port.get("permanent_mac") or ""), "mac")

    by_name = _unique(interfaces, lambda interface: interface.name)
    for port in ports:
        for name in [port["name"], *(port.get("altnames") or [])]:
            matcher.assign(port, by_name.get(name), "name")

    by_label = _unique(interfaces, lambda interface: interface.label)
    for port in ports:
        matcher.assign(port, by_label.get(port["name"]), "label")

    for port in ports:
        seen = (neighbours or {}).get(port["name"]) or []
        if not seen or port["name"] in matcher.matches:
            continue
        candidates = [
            interface
            for interface in matcher.free()
            if any(
                neighbour_is_endpoint(neighbour, endpoint)
                for neighbour in seen
                for endpoint in interface.endpoints
            )
        ]
        if len(candidates) == 1:
            matcher.assign(port, candidates[0], "lldp")

    return matcher.result(ports)
