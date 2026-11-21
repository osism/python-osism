# SPDX-License-Identifier: Apache-2.0

"""Normalisation of LLDP neighbour data into one record format.

A neighbour record is a dict with the keys ``system_name``, ``chassis_id``,
``chassis_id_type``, ``port_id``, ``port_id_type``, ``port_description``,
``management_addresses`` and ``age``. A port can have several neighbours,
for example behind a hypervisor bridge, so neighbours are kept as a list per
local interface.
"""

import json
import re
from typing import Any, Dict, List, Optional

from osism.utils.hardware.parse_sonic import table

Neighbours = Dict[str, List[Dict[str, Any]]]

# LLDP-MIB subtypes as stored in LLDP_ENTRY_TABLE, named as lldpctl does
CHASSIS_ID_SUBTYPES = {
    "1": "chassis-component",
    "2": "ifalias",
    "3": "port-component",
    "4": "mac",
    "5": "ip",
    "6": "ifname",
    "7": "local",
}
PORT_ID_SUBTYPES = {
    "1": "ifalias",
    "2": "port-component",
    "3": "mac",
    "4": "ip",
    "5": "ifname",
    "6": "agent-circuit-id",
    "7": "local",
}


# Key of an LLDP_ENTRY_TABLE entry that names the neighbour after the port
_ENTRY_KEY = re.compile(r"^(.+):((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})$")


class LldpError(Exception):
    """LLDP data is not available on a device."""


def neighbour(
    system_name: Optional[str] = None,
    chassis_id: Optional[str] = None,
    chassis_id_type: Optional[str] = None,
    port_id: Optional[str] = None,
    port_id_type: Optional[str] = None,
    port_description: Optional[str] = None,
    management_addresses: Optional[List[str]] = None,
    age: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a neighbour record."""
    return {
        "system_name": system_name or None,
        "chassis_id": chassis_id or None,
        "chassis_id_type": chassis_id_type or None,
        "port_id": port_id or None,
        "port_id_type": port_id_type or None,
        "port_description": port_description or None,
        "management_addresses": list(management_addresses or []),
        "age": age or None,
    }


def _typed_value(data: Any) -> tuple:
    """Return ``(value, type)`` of an lldpctl ``{"type": .., "value": ..}``."""
    if isinstance(data, dict):
        return data.get("value"), data.get("type")
    return (data or None), None


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_chassis(chassis: Any) -> tuple:
    """Return ``(system name, chassis body)`` of an lldpctl chassis entry.

    lldpctl keys the chassis by its system name. A neighbour that announces
    no name has the chassis fields directly under ``chassis``.
    """
    if not isinstance(chassis, dict) or not chassis:
        return None, {}
    if isinstance(chassis.get("id"), dict) and "value" in chassis["id"]:
        return None, chassis
    name = next(iter(chassis))
    body = chassis[name]
    return name, body if isinstance(body, dict) else {}


def parse_lldpctl(data: Any) -> Neighbours:
    """Parse the output of ``lldpctl -f json``.

    Args:
        data: The JSON text, or the already decoded document

    Returns:
        Neighbour records per local interface

    Raises:
        ValueError: The text is not valid JSON
    """
    if isinstance(data, str):
        data = json.loads(data) if data.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("unexpected lldpctl document")

    interfaces = (data.get("lldp") or {}).get("interface") or {}
    # lldpctl prints a dict for a single interface and a list of
    # single-key dicts for several. Normalise to the list form.
    if isinstance(interfaces, dict):
        interfaces = [{name: entry} for name, entry in interfaces.items()]

    neighbours: Neighbours = {}
    for item in interfaces:
        if not isinstance(item, dict):
            continue
        for local_interface, entry in item.items():
            entry = entry if isinstance(entry, dict) else {}
            system_name, chassis = _parse_chassis(entry.get("chassis"))
            chassis_id, chassis_id_type = _typed_value(chassis.get("id"))
            port = entry.get("port")
            if not isinstance(port, dict):
                port = {}
            port_id, port_id_type = _typed_value(port.get("id"))
            neighbours.setdefault(local_interface, []).append(
                neighbour(
                    system_name=system_name,
                    chassis_id=chassis_id,
                    chassis_id_type=chassis_id_type,
                    port_id=port_id,
                    port_id_type=port_id_type,
                    port_description=port.get("descr"),
                    management_addresses=[
                        str(address) for address in _as_list(chassis.get("mgmt-ip"))
                    ],
                    age=entry.get("age"),
                )
            )
    return neighbours


def linux_neighbours(document: Dict[str, Any]) -> Neighbours:
    """Return the neighbours found in a Linux collector document.

    Raises:
        LldpError: ``lldpctl`` is missing, ``lldpd`` is not running, or the
            output cannot be parsed
    """
    result = document.get("lldpctl")
    if not isinstance(result, dict):
        raise LldpError("LLDP data was not collected")
    if result.get("rc") == 127:
        raise LldpError("lldpctl not found")
    if result.get("rc") != 0:
        detail = (result.get("err") or "").strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.get('rc')}"
        raise LldpError(f"lldpctl failed: {reason}")
    try:
        return parse_lldpctl(result.get("out") or "")
    except ValueError:
        raise LldpError("unparsable lldpctl output")


def entry_port(key: str) -> str:
    """Return the local port an ``LLDP_ENTRY_TABLE`` key belongs to.

    The key is the port name (``Ethernet0``). Enterprise SONiC 4.5 appends
    the source MAC address of the neighbour (``Ethernet0:aa:bb:cc:dd:ee:ff``)
    and so keeps several neighbours per port.
    """
    match = _ENTRY_KEY.match(key)
    return match.group(1) if match else key


def parse_lldp_entry_table(entries: Dict[str, Dict[str, Any]]) -> Neighbours:
    """Parse the entries of ``LLDP_ENTRY_TABLE`` (APPL_DB) of a SONiC switch.

    The records have no ``age``. ``lldp_rem_time_mark`` is not one on every
    release: Enterprise SONiC stores the uptime of ``lldpd`` at which the
    neighbour was learned, so it is large for a neighbour that just came
    up and small for one that has been there since boot.

    Args:
        entries: Fields per key without the table prefix, as
            ``parse_sonic.table`` returns them
    """
    neighbours: Neighbours = {}
    for key, fields in entries.items():
        addresses = [
            address.strip()
            for address in str(fields.get("lldp_rem_man_addr") or "").split(",")
            if address.strip()
        ]
        neighbours.setdefault(entry_port(key), []).append(
            neighbour(
                system_name=fields.get("lldp_rem_sys_name"),
                chassis_id=fields.get("lldp_rem_chassis_id"),
                chassis_id_type=CHASSIS_ID_SUBTYPES.get(
                    str(fields.get("lldp_rem_chassis_id_subtype"))
                ),
                port_id=fields.get("lldp_rem_port_id"),
                port_id_type=PORT_ID_SUBTYPES.get(
                    str(fields.get("lldp_rem_port_id_subtype"))
                ),
                port_description=fields.get("lldp_rem_port_desc"),
                management_addresses=addresses,
            )
        )
    return neighbours


def sonic_neighbours(document: Dict[str, Any]) -> Neighbours:
    """Return the neighbours found in a SONiC collector document.

    ``LLDP_ENTRY_TABLE`` is the primary source. Ports it does not list are
    filled in from ``lldpctl``, when the collector ran it.

    Raises:
        LldpError: Neither source could be read
    """
    collected = "LLDP_ENTRY_TABLE" in ((document.get("db") or {}).get("APPL_DB") or {})
    neighbours = parse_lldp_entry_table(table(document, "APPL_DB", "LLDP_ENTRY_TABLE"))

    result = document.get("lldpctl")
    if isinstance(result, dict) and result.get("rc") == 0:
        try:
            for name, found in parse_lldpctl(result.get("out") or "").items():
                neighbours.setdefault(name, found)
        except ValueError:
            if not collected:
                raise LldpError("unparsable lldpctl output")
    elif not collected:
        lines: List[str] = []
        if isinstance(result, dict):
            lines = (result.get("err") or "").strip().splitlines()
        errors = document.get("errors") or {}
        reason = (
            (lines[-1] if lines else "")
            or errors.get("APPL_DB LLDP_ENTRY_TABLE")
            or "no LLDP data"
        )
        raise LldpError(f"LLDP neighbours not readable: {reason}")

    return neighbours
