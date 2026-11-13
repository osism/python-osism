# SPDX-License-Identifier: Apache-2.0

"""Parsers for the raw document of the SONiC collector (``remote_sonic``)."""

import re
from typing import Any, Dict, List, Optional

from osism.utils.hardware import natural_key, normalize_mac

MGMT_PORT = "eth0"
_FRONT_PANEL = re.compile(r"^Ethernet\d+$")


def table(
    document: Dict[str, Any], database: str, name: str
) -> Dict[str, Dict[str, Any]]:
    """Return a dumped table as ``{key without table prefix: fields}``.

    ``sonic-db-dump`` prints ``{"PORT|Ethernet0": {"type": "hash", "value":
    {...}}}``. The separator is ``|`` in CONFIG_DB and STATE_DB and ``:`` in
    APPL_DB.
    """
    raw = ((document.get("db") or {}).get(database) or {}).get(name) or {}
    entries: Dict[str, Dict[str, Any]] = {}
    for key, entry in raw.items():
        if not key.startswith(name) or len(key) <= len(name) + 1:
            continue
        fields = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(fields, dict):
            fields = entry if isinstance(entry, dict) else {}
        entries[key[len(name) + 1 :]] = fields
    return entries


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status(value: Any) -> Optional[str]:
    value = str(value or "").lower()
    return value if value in ("up", "down") else None


def device_metadata(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return the fields of ``DEVICE_METADATA|localhost``."""
    return table(document, "CONFIG_DB", "DEVICE_METADATA").get("localhost") or {}


def parse_ports(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the front-panel ports of a switch in natural name order.

    The port list and the configuration come from ``CONFIG_DB``, the
    operational state from ``APPL_DB``.
    """
    config = table(document, "CONFIG_DB", "PORT")
    state = table(document, "APPL_DB", "PORT_TABLE")

    ports: List[Dict[str, Any]] = []
    for name, fields in config.items():
        if not _FRONT_PANEL.match(name):
            continue
        live = state.get(name) or {}
        ports.append(
            {
                "name": name,
                "kind": "physical",
                "parent": None,
                "alias": fields.get("alias") or None,
                "altnames": [],
                "admin_status": _status(
                    fields.get("admin_status") or live.get("admin_status")
                )
                or "down",
                "oper_status": _status(live.get("oper_status")),
                "speed": _int(live.get("speed")) or _int(fields.get("speed")),
                "duplex": None,
                "mtu": _int(fields.get("mtu") or live.get("mtu")),
                "mac": None,
                "permanent_mac": None,
                "bond": None,
                "fec": fields.get("fec") or live.get("fec") or None,
                "description": fields.get("description")
                or live.get("description")
                or None,
                "lanes": fields.get("lanes") or None,
                "index": _int(fields.get("index")),
            }
        )
    return sorted(ports, key=lambda port: natural_key(port["name"]))


def parse_mgmt_port(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the management port ``eth0``, or None when it was not seen."""
    raw = (document.get("mgmt") or {}).get(MGMT_PORT)
    if not isinstance(raw, dict):
        return None

    state = (raw.get("operstate") or "").lower()
    if state not in ("up", "down"):
        state = {"1": "up", "0": "down"}.get(raw.get("carrier") or "", "")
    mac = normalize_mac(raw.get("address"))
    speed = _int(raw.get("speed"))
    return {
        "name": MGMT_PORT,
        "kind": "mgmt",
        "parent": None,
        "alias": None,
        "altnames": [],
        "admin_status": None,
        "oper_status": state or None,
        "speed": speed if speed and speed > 0 else None,
        "duplex": None,
        "mtu": _int(raw.get("mtu")),
        "mac": mac,
        "permanent_mac": mac,
        "bond": None,
    }
