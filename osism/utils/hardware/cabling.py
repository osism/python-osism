# SPDX-License-Identifier: Apache-2.0

"""Comparison of live LLDP neighbours with the cabling documented in NetBox.

Everything in here works on plain data: the ports and neighbours collected
from the devices, and NetBox interfaces with the far end of their cable
path. There is no SSH and no pynetbox, so the whole result matrix can be
tested without either.

The check runs in three steps. Every port of a queried device first gets a
result of its own. Ports that look fine are then checked from the other
side, when the peer was queried as well. Finally the mismatches are searched
for cables that were exchanged with each other.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from osism.utils.hardware import normalize_mac
from osism.utils.hardware.mapping import (
    Endpoint,
    Match,
    NetboxInterface,
    neighbour_is_endpoint,
    neighbour_port_names,
    same_system,
)
from osism.utils.hardware.parse_lldp import Neighbours

RESULT_OK = "ok"
RESULT_MISSING = "missing"
RESULT_NO_LLDP = "no-lldp"
RESULT_WRONG_PORT = "wrong-port"
RESULT_WRONG_DEVICE = "wrong-device"
RESULT_SWAPPED = "swapped"
RESULT_UNEXPECTED = "unexpected"
RESULT_ONE_SIDED = "one-sided"
RESULT_UNMAPPED = "unmapped"
RESULT_STALE = "stale"

RESULTS = [
    RESULT_OK,
    RESULT_MISSING,
    RESULT_NO_LLDP,
    RESULT_WRONG_PORT,
    RESULT_WRONG_DEVICE,
    RESULT_SWAPPED,
    RESULT_UNEXPECTED,
    RESULT_ONE_SIDED,
    RESULT_UNMAPPED,
    RESULT_STALE,
]


@dataclass
class NetboxDevice:
    """A NetBox device reduced to what identifies it to its neighbours."""

    id: Optional[int]
    name: str
    hostname: str = ""
    addresses: List[str] = field(default_factory=list)


@dataclass
class LiveDevice:
    """What was collected from one queried device.

    Attributes:
        name: Device name as used in the report
        kind: ``node`` or ``switch``
        hostname: Inventory hostname, when it differs from the name
        device_id: NetBox device ID, ``None`` without NetBox
        ports: Live ports that are subject to the check
        neighbours: LLDP neighbours per live port name
        matches: NetBox interface per live port name
        unmatched: Documented interfaces without a live port
    """

    name: str
    kind: str
    hostname: str = ""
    device_id: Optional[int] = None
    ports: List[Dict[str, Any]] = field(default_factory=list)
    neighbours: Neighbours = field(default_factory=dict)
    matches: Dict[str, Match] = field(default_factory=dict)
    unmatched: List[NetboxInterface] = field(default_factory=list)


@dataclass
class Seen:
    """An LLDP neighbour, resolved to NetBox as far as possible.

    ``device`` and ``interface`` hold the NetBox names when the neighbour
    was resolved, and what the neighbour announced otherwise.
    """

    device: str
    interface: str
    neighbour: Dict[str, Any]
    device_id: Optional[int] = None
    netbox_interface: Optional[NetboxInterface] = None


def netbox_device(data: Dict[str, Any]) -> NetboxDevice:
    """Build a ``NetboxDevice`` from the plain data of an API record."""
    addresses = []
    for key in ("primary_ip4", "primary_ip6", "oob_ip"):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("address")
        if value:
            addresses.append(str(value).split("/")[0])
    custom_fields = data.get("custom_fields") or {}
    return NetboxDevice(
        id=data.get("id"),
        name=data.get("name") or "",
        hostname=custom_fields.get("inventory_hostname") or "",
        addresses=addresses,
    )


def find_live_port(
    device: LiveDevice, neighbour: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Find the live port of a queried device a neighbour record points at.

    The port ID or the port description has to equal the name, an altname
    or the alias of the port, or the port ID has to be its MAC address.
    """
    for value in neighbour_port_names(neighbour):
        for port in device.ports:
            if value == port["name"] or value == port.get("alias"):
                return port
            if value in (port.get("altnames") or []):
                return port
    mac = normalize_mac(neighbour.get("port_id"))
    if mac:
        for port in device.ports:
            if mac in (port.get("permanent_mac"), port.get("mac")):
                return port
    return None


class Directory:
    """Resolves LLDP identities to NetBox devices and interfaces.

    Args:
        devices: NetBox devices a neighbour may turn out to be
        interfaces: NetBox interfaces per device ID
        live: The queried devices
        sonic_names: Per device ID, NetBox interface by SONiC port name
        sonic_aliases: Per device ID, SONiC port name by vendor alias
    """

    def __init__(
        self,
        devices: Iterable[NetboxDevice] = (),
        interfaces: Optional[Dict[int, List[NetboxInterface]]] = None,
        live: Iterable[LiveDevice] = (),
        sonic_names: Optional[Dict[int, Dict[str, NetboxInterface]]] = None,
        sonic_aliases: Optional[Dict[int, Dict[str, str]]] = None,
    ):
        self.interfaces = interfaces or {}
        self.sonic_names = sonic_names or {}
        self.sonic_aliases = sonic_aliases or {}
        live = list(live)
        self.live_by_id = {d.device_id: d for d in live if d.device_id is not None}
        self.live_by_name = {d.name: d for d in live}

        self._exact: Dict[str, NetboxDevice] = {}
        self._short: Dict[str, NetboxDevice] = {}
        self._by_address: Dict[str, NetboxDevice] = {}
        self._by_id: Dict[int, NetboxDevice] = {}
        for device in devices:
            if device.id is not None:
                self._by_id[device.id] = device
            for name in (device.name, device.hostname):
                if name:
                    self._exact.setdefault(name.lower(), device)
                    self._short.setdefault(name.lower().split(".")[0], device)
            for address in device.addresses:
                self._by_address.setdefault(address, device)

        owners: Dict[str, Dict[int, NetboxDevice]] = {}
        for device_id, device_interfaces in self.interfaces.items():
            owner = self._by_id.get(device_id)
            if owner is None:
                continue
            for interface in device_interfaces:
                for mac in interface.macs:
                    owners.setdefault(mac, {})[device_id] = owner
        # A MAC address documented on several devices identifies none of
        # them. The USB host interface of a BMC is one: it has the same
        # address on every node of a model.
        self._by_mac: Dict[str, NetboxDevice] = {
            mac: next(iter(found.values()))
            for mac, found in owners.items()
            if len(found) == 1
        }

    def resolve_device(self, neighbour: Dict[str, Any]) -> Optional[NetboxDevice]:
        """Find the NetBox device a neighbour announces itself as.

        The system name is compared case-insensitively, as given and with
        the domain stripped, against device names and inventory hostnames.

        The name does not always lead to the device: a node can have a host
        name that differs from its device name, or still have the default
        one of its image, and the LLDP agent of a NIC announces the name of
        the NIC instead of the host. The fallbacks are, in this order,
        the port ID when it is a MAC address, the management addresses and
        the chassis ID. ``lldpd`` announces the MAC address of the port as
        port ID, which names exactly one interface. Its chassis ID is the
        MAC address of some interface of the node, and its management
        addresses include the one of ``docker0``; neither is unique among
        the nodes.
        """
        name = (neighbour.get("system_name") or "").lower()
        if name:
            device = self._exact.get(name) or self._short.get(name.split(".")[0])
            if device is not None:
                return device
        mac = normalize_mac(neighbour.get("port_id"))
        if mac and mac in self._by_mac:
            return self._by_mac[mac]
        for address in neighbour.get("management_addresses") or []:
            if address in self._by_address:
                return self._by_address[address]
        mac = normalize_mac(neighbour.get("chassis_id"))
        if mac:
            return self._by_mac.get(mac)
        return None

    def resolve_port(
        self, device: NetboxDevice, neighbour: Dict[str, Any]
    ) -> Optional[NetboxInterface]:
        """Find the NetBox interface of a device a neighbour record names.

        First match wins: the port ID or description is the name or label
        of an interface; it is a SONiC port name or vendor alias that the
        HWSKU port config translates; the port ID is the MAC address of an
        interface; or the device was queried and one of its live ports
        carries that name, alias or MAC.
        """
        if device.id is None:
            return None
        interfaces = self.interfaces.get(device.id) or []
        values = neighbour_port_names(neighbour)

        for value in values:
            for interface in interfaces:
                if value == interface.name or (
                    interface.label and value == interface.label
                ):
                    return interface

        index = self.sonic_names.get(device.id) or {}
        aliases = self.sonic_aliases.get(device.id) or {}
        for value in values:
            sonic_name = value if value in index else aliases.get(value)
            if sonic_name in index:
                return index[sonic_name]

        mac = normalize_mac(neighbour.get("port_id"))
        if mac:
            for interface in interfaces:
                if mac in interface.macs:
                    return interface

        live = self.live_by_id.get(device.id)
        if live is not None:
            port = find_live_port(live, neighbour)
            if port is not None:
                match = live.matches.get(port["name"])
                if match is not None and match.interface is not None:
                    return match.interface
        return None

    def resolve(self, neighbour: Dict[str, Any]) -> Seen:
        """Resolve a neighbour record as far as NetBox knows it."""
        announced_device = (
            neighbour.get("system_name") or neighbour.get("chassis_id") or "?"
        )
        announced_port = (
            neighbour.get("port_id") or neighbour.get("port_description") or "?"
        )
        device = self.resolve_device(neighbour)
        if device is None:
            return Seen(announced_device, announced_port, neighbour)
        interface = self.resolve_port(device, neighbour)
        return Seen(
            device=device.name,
            interface=interface.name if interface else announced_port,
            neighbour=neighbour,
            device_id=device.id,
            netbox_interface=interface,
        )

    def live_device(self, endpoint: Endpoint) -> Optional[LiveDevice]:
        """Return the queried device an endpoint belongs to, if it was queried."""
        if endpoint.device_id is not None:
            return self.live_by_id.get(endpoint.device_id)
        return self.live_by_name.get(endpoint.device)


def _row(
    device: LiveDevice,
    interface: str,
    oper_status: Optional[str] = None,
    match: Optional[Match] = None,
    seen: Sequence[Seen] = (),
    result: str = "",
    hint: str = "",
) -> Dict[str, Any]:
    netbox = match.interface if match else None
    return {
        "device": device.name,
        "kind": device.kind,
        "interface": interface,
        "netbox_name": netbox.name if netbox else None,
        "mapping": match.method if match else None,
        "oper_status": oper_status,
        "expected": [
            {"device": endpoint.device, "interface": endpoint.interface}
            for endpoint in (netbox.endpoints if netbox else [])
        ],
        "seen": [
            {"device": item.device, "interface": item.interface, **item.neighbour}
            for item in seen
        ],
        "result": result,
        "hint": hint,
        # Working data of the later passes, dropped by public()
        "_device": device,
        "_interface": netbox,
        "_seen": list(seen),
    }


def public(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a row without the working data of the comparison."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _is_endpoint(seen: Seen, endpoint: Endpoint) -> bool:
    """Return True when a neighbour is the documented far end."""
    if seen.device_id is None:
        return neighbour_is_endpoint(seen.neighbour, endpoint)
    if not _same_device(seen, endpoint):
        return False
    if seen.netbox_interface is not None:
        return seen.netbox_interface.name == endpoint.interface
    return endpoint.interface in neighbour_port_names(seen.neighbour)


def _same_device(seen: Seen, endpoint: Endpoint) -> bool:
    if seen.device_id is not None and endpoint.device_id is not None:
        return seen.device_id == endpoint.device_id
    return same_system(seen.device, endpoint.device)


def _documented_at(seen: Seen) -> str:
    """Say where NetBox documents the cable that was seen."""
    if seen.device_id is None:
        return "neighbour unknown to NetBox"
    if seen.netbox_interface is None:
        return "neighbour port not found in NetBox"
    endpoints = seen.netbox_interface.endpoints
    if not endpoints:
        return "seen port has no cable in NetBox"
    places = ", ".join(f"{e.device}:{e.interface}" for e in endpoints)
    return f"documented at {places}"


def _check_port(
    device: LiveDevice, port: Dict[str, Any], directory: Directory
) -> Dict[str, Any]:
    """Give one live port its result, before the cross-device passes."""
    name = port["name"]
    link = port.get("oper_status")
    match = device.matches.get(name) or Match()
    seen = [directory.resolve(n) for n in device.neighbours.get(name) or []]

    def row(result: str = "", hint: str = "") -> Dict[str, Any]:
        return _row(device, name, link, match, seen, result, hint)

    if seen and link == "down":
        return row(RESULT_STALE, "link down, neighbour not aged out")

    interface = match.interface
    if interface is None:
        if seen:
            return row(RESULT_UNMAPPED, "port not found in NetBox")
        # A port NetBox does not know and that has no neighbour says nothing
        # about the cabling: the USB NIC of a BMC is one of these.
        return row(hint="port not found in NetBox")

    expected = interface.endpoints
    if expected:
        if not seen:
            if link == "down":
                return row(RESULT_MISSING, "link down")
            return row(RESULT_NO_LLDP, "link up, no neighbour")
        if any(_is_endpoint(s, e) for s in seen for e in expected):
            return row(RESULT_OK)
        on_expected_device = [
            s for s in seen if any(_same_device(s, e) for e in expected)
        ]
        if on_expected_device:
            return row(RESULT_WRONG_PORT, _documented_at(on_expected_device[0]))
        return row(RESULT_WRONG_DEVICE, _documented_at(seen[0]))

    reason = (
        "incomplete cable path in NetBox"
        if interface.path_incomplete
        else "no cable in NetBox"
    )
    if seen:
        return row(RESULT_UNEXPECTED, reason)
    if link == "up" and not interface.path_incomplete:
        return row(RESULT_UNEXPECTED, "link up, no neighbour, no cable in NetBox")
    return row(hint=reason if interface.path_incomplete else "")


def _disagrees(seen_by_peer: Sequence[Seen], back: Endpoint) -> bool:
    """Return True when what a peer port sees rules out the other side.

    A neighbour on the right device whose port cannot be identified is not
    a disagreement: it shows that the two are connected, just not where.
    """
    for seen in seen_by_peer:
        if _is_endpoint(seen, back):
            return False
        if _same_device(seen, back) and seen.netbox_interface is None:
            return False
    return True


def _mark_one_sided(rows: Sequence[Dict[str, Any]], directory: Directory) -> None:
    """Turn ``ok`` into ``one-sided`` when a queried peer disagrees.

    This side sees the documented peer. When the peer was queried too, its
    port has to see this side in return.
    """
    for row in rows:
        if row["result"] != RESULT_OK:
            continue
        device: LiveDevice = row["_device"]
        interface: NetboxInterface = row["_interface"]
        for endpoint in interface.endpoints:
            if not any(_is_endpoint(seen, endpoint) for seen in row["_seen"]):
                continue
            peer = directory.live_device(endpoint)
            if peer is None:
                continue
            peer_port = next(
                (
                    name
                    for name, match in peer.matches.items()
                    if match.interface is not None
                    and match.interface.name == endpoint.interface
                ),
                None,
            )
            if peer_port is None:
                continue
            back = Endpoint(
                device=device.name, interface=interface.name, device_id=device.device_id
            )
            seen_by_peer = [
                directory.resolve(n) for n in peer.neighbours.get(peer_port) or []
            ]
            if _disagrees(seen_by_peer, back):
                row["result"] = RESULT_ONE_SIDED
                row["hint"] = (
                    f"{endpoint.device}:{endpoint.interface} does not see this port"
                )
                break


def _label(row: Dict[str, Any], other: Dict[str, Any]) -> str:
    """Name another port from the point of view of a row."""
    if other["device"] == row["device"]:
        return other["interface"]
    return f"{other['device']}:{other['interface']}"


def _mark_swapped(rows: Sequence[Dict[str, Any]], directory: Directory) -> None:
    """Turn mismatches into ``swapped`` when cables were exchanged.

    A mismatching interface I sees an endpoint N. NetBox documents N for
    some interface J. When J in turn sees the endpoint documented for I,
    the two cables are swapped. Following the same step from J finds
    longer rotations: the chain is a swap when it leads back to I.
    """
    candidates = {
        (row["device"], row["netbox_name"]): row
        for row in rows
        if row["result"] in (RESULT_WRONG_PORT, RESULT_WRONG_DEVICE)
        and row["_interface"] is not None
    }

    def owner(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the mismatching port that owns the cable this one sees."""
        for seen in row["_seen"]:
            if seen.netbox_interface is None:
                continue
            for endpoint in seen.netbox_interface.endpoints:
                other = candidates.get((endpoint.device, endpoint.interface))
                if other is not None and other is not row:
                    return other
        return None

    done: set = set()
    for start in candidates.values():
        if id(start) in done:
            continue
        chain = [start]
        current = owner(start)
        while current is not None and all(current is not item for item in chain):
            chain.append(current)
            current = owner(current)
        if current is not start or len(chain) < 2:
            continue
        for position, row in enumerate(chain):
            # Named in the order of the chain: the first partner is the port
            # where this port's own cable is documented to be seen
            others = chain[position + 1 :] + chain[:position]
            partners = [_label(row, other) for other in others]
            row["result"] = RESULT_SWAPPED
            row["hint"] = f"swapped with {', '.join(partners)}"
            done.add(id(row))


def compare(
    devices: Sequence[LiveDevice], directory: Directory, include_idle: bool = False
) -> List[Dict[str, Any]]:
    """Compare the neighbours of all queried devices with NetBox.

    Args:
        devices: The queried devices
        directory: Resolver for LLDP identities, holding the NetBox data
        include_idle: Also return ports with nothing to report: no cable in
            NetBox, no neighbour and no link

    Returns:
        One row per port, with ``result`` and ``hint``. Rows of idle ports
        have an empty result.
    """
    rows: List[Dict[str, Any]] = []
    for device in devices:
        for port in device.ports:
            rows.append(_check_port(device, port, directory))
        for interface in device.unmatched:
            # A management interface without a live counterpart is the BMC
            # port of a node. Its cable is checked from the switch side.
            if interface.mgmt_only:
                continue
            if interface.endpoints or interface.path_incomplete:
                rows.append(
                    _row(
                        device,
                        interface.name,
                        match=Match(interface, "none"),
                        result=RESULT_UNMAPPED,
                        hint="no live port for this NetBox interface",
                    )
                )

    _mark_one_sided(rows, directory)
    _mark_swapped(rows, directory)

    return [public(row) for row in rows if include_idle or row["result"]]


def neighbour_listing(devices: Sequence[LiveDevice]) -> List[Dict[str, Any]]:
    """List the neighbours of all queried devices without NetBox cabling.

    Two checks need no source of truth and stay active: a port with link
    but without neighbour is ``no-lldp``, and a neighbour that was queried
    as well and does not see this port in return makes it ``one-sided``.

    Returns:
        One row per neighbour, plus one per ``no-lldp`` port. Rows without
        a finding have an empty result.
    """
    by_name: Dict[str, LiveDevice] = {}
    for device in devices:
        for name in (device.name, device.hostname):
            if name:
                by_name.setdefault(name.lower(), device)
                by_name.setdefault(name.lower().split(".")[0], device)

    def peer_of(neighbour: Dict[str, Any]) -> Optional[LiveDevice]:
        name = (neighbour.get("system_name") or "").lower()
        if not name:
            return None
        return by_name.get(name) or by_name.get(name.split(".")[0])

    def sees(peer: LiveDevice, peer_port: str, device: LiveDevice, port: str) -> bool:
        for neighbour in peer.neighbours.get(peer_port) or []:
            if peer_of(neighbour) is not device:
                continue
            found = find_live_port(device, neighbour)
            # A port that cannot be identified is not a disagreement
            if found is None or found["name"] == port:
                return True
        return False

    rows: List[Dict[str, Any]] = []
    for device in devices:
        ports = {port["name"]: port for port in device.ports}
        # lldpd also reports neighbours on interfaces that are not physical
        # ports of their own, such as a bridge. They are listed as well.
        names = list(ports) + [n for n in device.neighbours if n not in ports]
        for name in names:
            link = (ports.get(name) or {}).get("oper_status")
            neighbours = device.neighbours.get(name) or []
            if not neighbours:
                if link == "up":
                    rows.append(
                        _row(
                            device,
                            name,
                            link,
                            result=RESULT_NO_LLDP,
                            hint="link up, no neighbour",
                        )
                    )
                continue
            for neighbour in neighbours:
                seen = Seen(
                    neighbour.get("system_name") or neighbour.get("chassis_id") or "",
                    neighbour.get("port_id") or "",
                    neighbour,
                )
                row = _row(device, name, link, seen=[seen])
                peer = peer_of(neighbour)
                if peer is not None and peer is not device:
                    peer_port = find_live_port(peer, neighbour)
                    if peer_port is not None and not sees(
                        peer, peer_port["name"], device, name
                    ):
                        row["result"] = RESULT_ONE_SIDED
                        row["hint"] = (
                            f"{peer.name}:{peer_port['name']} does not see this port"
                        )
                rows.append(row)

    return [public(row) for row in rows]


def summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count the rows per result, in the order of ``RESULTS``."""
    counts: Dict[str, int] = {}
    for row in rows:
        if row["result"]:
            counts[row["result"]] = counts.get(row["result"], 0) + 1
    return {result: counts[result] for result in RESULTS if result in counts}
