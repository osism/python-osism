# SPDX-License-Identifier: Apache-2.0

"""Parsers for the raw document of the SONiC collector (``remote_sonic``)."""

import ast
import re
from typing import Any, Dict, List, Optional, Tuple

from osism.utils.hardware import (
    natural_key,
    normalize_date_code,
    normalize_mac,
    transceiver_record,
)

MGMT_PORT = "eth0"
_FRONT_PANEL = re.compile(r"^Ethernet\d+$")
_VERSION_LINE = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(.*?)\s*$")
_SYSEEPROM_LINE = re.compile(r"^(.+?)\s+0x[0-9A-Fa-f]{2}\s+\d+\s+(.*)$")
_OUI = re.compile(r"^[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}\1[0-9A-Fa-f]{2}$")
# "SONiC.202311.1" on community SONiC, "SONiC-OS-4.5.2" on Enterprise SONiC
_VERSION_PREFIX = re.compile(r"^SONiC(?:\.|-OS-)")

# Values SONiC writes for "no information"
_MISSING = {"", "n/a", "na", "none", "unknown", "not available"}

# Field names in TRANSCEIVER_INFO differ between community SONiC releases
# and Enterprise SONiC. Each output field has a list of candidate keys; the
# first one present with a value wins.
TRANSCEIVER_KEYS = {
    "form_factor": ["type_abbrv_name", "type", "form_factor"],
    "connector": ["connector", "connector_type"],
    "vendor": ["manufacturer", "vendor_name", "manufacturename"],
    "vendor_oui": ["vendor_oui"],
    "part_number": [
        "model",
        "vendor_pn",
        "modelname",
        "vendor_part_number",
        "part_number",
    ],
    "serial": [
        "serial",
        "vendor_sn",
        "serialnum",
        "vendor_serial_number",
        "serial_number",
    ],
    "revision": ["hardware_rev", "vendor_rev", "hardwarerev", "vendor_revision"],
    "date_code": ["vendor_date", "vendor_date_code", "date_code"],
    "firmware_active": [
        "active_firmware",
        "active_firmware_version",
        "firmware_version",
    ],
    "firmware_inactive": ["inactive_firmware", "inactive_firmware_version"],
    "compliance": ["specification_compliance", "spec_compliance", "compliance"],
    "cable_length": ["cable_length", "length_cable_assembly", "length"],
    "wavelength": ["nominal_wavelength", "wavelength"],
}

# Names of the entries in EEPROM_INFO and "show platform syseeprom"
EEPROM_NAMES = {
    "system_vendor": ["Manufacturer", "Vendor Name"],
    "system_model": ["Product Name"],
    "part_number": ["Part Number"],
    "serial": ["Serial Number"],
    "onie": ["ONIE Version"],
}


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


def _clean(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return None if text.lower() in _MISSING else text


def _pick(fields: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    for key in candidates:
        value = _clean(fields.get(key))
        if value is not None:
            return value
    return None


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compliance(value: Optional[str]) -> Optional[str]:
    """Return the compliance codes of a module as one line.

    SONiC stores them as the text of a Python dict, one entry per class of
    codes: ``{'10/40G Ethernet Compliance Code': '100GBASE-CR4'}``. Only
    the codes are kept. Anything else is returned as it is.
    """
    if not value or not value.startswith("{"):
        return value
    try:
        codes = ast.literal_eval(value)
    except (ValueError, SyntaxError, RecursionError, MemoryError):
        return value
    if not isinstance(codes, dict):
        return value
    found = [text for text in (_clean(code) for code in codes.values()) if text]
    return "; ".join(found) or None


def _vendor_oui(value: Optional[str]) -> Optional[str]:
    """Return an OUI as ``ethtool`` prints it: ``64-9D-99`` is ``64:9d:99``."""
    if value and _OUI.match(value):
        return value.replace("-", ":").lower()
    return value


def _quantity(value: Optional[str], unit: str) -> Optional[str]:
    """Return a number with its unit, as ``ethtool`` prints it.

    SONiC writes ``2.0`` for a cable of 2 m and ``850.00000000`` for 850 nm.
    Zero stands for "not applicable": an optical module has no cable length.
    A value that is not a number is returned as it is.
    """
    number = _float(value)
    if number is None:
        return value
    if number == 0:
        return None
    return f"{number:g}{unit}"


def _cable_length(fields: Dict[str, Any], value: Optional[str]) -> Optional[str]:
    # The unit is part of the name of the EEPROM field the length was read
    # from: "Length Cable Assembly(m)", but also "Length OM3(2m)".
    unit = _clean(fields.get("cable_type"))
    if unit and not unit.endswith("(m)") and _float(value):
        return f"{value} ({unit})"
    return _quantity(value, "m")


def parse_transceivers(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return the transceiver record of every port that has a module.

    A port without an entry in ``TRANSCEIVER_INFO`` has no module plugged
    in and is not part of the result. Values are written the way the Linux
    parser writes them, so both ends of a cable read alike.
    """
    info = table(document, "STATE_DB", "TRANSCEIVER_INFO")
    firmware = table(document, "STATE_DB", "TRANSCEIVER_FIRMWARE_INFO")

    transceivers = {}
    for name, fields in info.items():
        # The table also holds markers such as XcvrInitDone
        if not _FRONT_PANEL.match(name):
            continue
        merged = dict(firmware.get(name) or {})
        merged.update({k: v for k, v in fields.items() if _clean(v) is not None})
        record = transceiver_record(True)
        for output, candidates in TRANSCEIVER_KEYS.items():
            record[output] = _pick(merged, candidates)
        record["vendor_oui"] = _vendor_oui(record["vendor_oui"])
        record["date_code"] = normalize_date_code(record["date_code"])
        record["compliance"] = _compliance(record["compliance"])
        record["cable_length"] = _cable_length(merged, record["cable_length"])
        record["wavelength"] = _quantity(record["wavelength"], "nm")
        transceivers[name] = record
    return transceivers


def parse_dom(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return the diagnostic readings per port from TRANSCEIVER_DOM_SENSOR.

    Lanes are numbered from 1 (``rx1power``, ``tx1bias``, ``tx1power``). A
    lane is listed when the module reports at least one value for it. A
    module without diagnostics, such as a passive copper cable, has an
    entry with ``N/A`` for every value and is not part of the result.
    """
    readings = {}
    for name, fields in table(document, "STATE_DB", "TRANSCEIVER_DOM_SENSOR").items():
        lanes = []
        for number in range(1, 9):
            lane = {
                "rx_power": _float(_clean(fields.get(f"rx{number}power"))),
                "tx_power": _float(_clean(fields.get(f"tx{number}power"))),
                "tx_bias": _float(_clean(fields.get(f"tx{number}bias"))),
            }
            if any(value is not None for value in lane.values()):
                lanes.append(lane)
        temperature = _float(_clean(fields.get("temperature")))
        voltage = _float(_clean(fields.get("voltage")))
        if temperature is None and voltage is None and not lanes:
            continue
        readings[name] = {
            "temperature": temperature,
            "voltage": voltage,
            "lanes": lanes,
        }
    return readings


def parse_version_file(text: Optional[str]) -> Dict[str, str]:
    """Parse ``/etc/sonic/sonic_version.yml``, a flat ``key: 'value'`` file."""
    values = {}
    for line in (text or "").splitlines():
        match = _VERSION_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip("'\"")
    return values


def parse_show_version(text: Optional[str]) -> Dict[str, Optional[str]]:
    """Parse the ``Key: Value`` lines of ``show version``."""
    values = {}
    for line in (text or "").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip().lower()] = value.strip()
    version = values.get("sonic software version") or ""
    return {
        "os_version": _VERSION_PREFIX.sub("", version) or None,
        "asic": values.get("asic") or None,
        "platform": values.get("platform") or None,
        "hwsku": values.get("hwsku") or None,
        "serial": values.get("serial number") or None,
    }


def parse_syseeprom(document: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Return the chassis identity from the system EEPROM.

    ``EEPROM_INFO`` in STATE_DB is preferred. Its entries are keyed by TLV
    code and carry ``Name`` and ``Value``. ``show platform syseeprom`` prints
    the same as a table and is the fallback.
    """
    names: Dict[str, str] = {}
    for fields in table(document, "STATE_DB", "EEPROM_INFO").values():
        name, value = _clean(fields.get("Name")), _clean(fields.get("Value"))
        if name and value:
            names[name.lower()] = value

    if not names:
        output = _command(document, "show platform syseeprom")
        for line in (output or "").splitlines():
            match = _SYSEEPROM_LINE.match(line)
            if match and _clean(match.group(2)):
                names[match.group(1).strip().lower()] = match.group(2).strip()

    return {
        output: next(
            (names[name.lower()] for name in candidates if name.lower() in names),
            None,
        )
        for output, candidates in EEPROM_NAMES.items()
    }


def parse_firmware_status(text: Optional[str]) -> Dict[str, str]:
    """Parse the table of ``show platform firmware status``.

    The table is column-aligned with a line of dashes below the header.
    Cells are cut at the positions of the dash groups, because values such
    as the description contain spaces.

    Returns:
        Version per component name, e.g. ``{"BIOS": "3.42", "CPLD1": "7"}``
    """
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if index and line.strip() and set(line.strip()) <= {"-", " "}:
            break
    else:
        return {}

    spans = [match.span() for match in re.finditer(r"-+", line)]
    header = [lines[index - 1][start:end].strip().lower() for start, end in spans]
    if "component" not in header or "version" not in header:
        return {}
    component, version = header.index("component"), header.index("version")

    def cut(row: str, column: int) -> str:
        start = spans[column][0]
        # The last column is not padded and can be longer than its dashes
        end = spans[column + 1][0] if column + 1 < len(spans) else len(row)
        return row[start:end].strip()

    versions = {}
    for row in lines[index + 1 :]:
        name, value = cut(row, component), _clean(cut(row, version))
        if name and value:
            versions[name] = value
    return versions


def _command(document: Dict[str, Any], name: str) -> Optional[str]:
    result = (document.get("commands") or {}).get(name)
    if not isinstance(result, dict) or result.get("rc") != 0:
        return None
    return result.get("out") or ""


def parse_system(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return platform, software and chassis identity of a switch."""
    metadata = device_metadata(document)
    version = parse_version_file((document.get("files") or {}).get("sonic_version"))
    shown = parse_show_version(_command(document, "show version"))
    eeprom = parse_syseeprom(document)

    components = parse_firmware_status(
        _command(document, "show platform firmware status")
    )
    cpld = {
        name: value
        for name, value in components.items()
        if name.upper().startswith("CPLD")
    }
    if len(cpld) == 1:
        cpld_text: Optional[str] = next(iter(cpld.values()))
    else:
        cpld_text = ", ".join(f"{name} {value}" for name, value in cpld.items()) or None
    bios = next(
        (value for name, value in components.items() if name.upper() == "BIOS"), None
    )
    onie = next(
        (value for name, value in components.items() if name.upper() == "ONIE"), None
    )

    return {
        "hwsku": _clean(metadata.get("hwsku")) or shown["hwsku"],
        "platform": _clean(metadata.get("platform")) or shown["platform"],
        "asic": version.get("asic_type") or shown["asic"],
        "os_version": version.get("build_version") or shown["os_version"],
        "firmware": {"bios": bios, "cpld": cpld_text, "onie": onie or eeprom["onie"]},
        "system_vendor": eeprom["system_vendor"],
        "system_model": eeprom["system_model"],
        "part_number": eeprom["part_number"],
        "serial": eeprom["serial"] or shown["serial"],
        "base_mac": normalize_mac(metadata.get("mac")),
    }


def parse_inventory(
    document: Dict[str, Any], dom: bool = False
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return the hardware view of a switch.

    Only front-panel ports are part of it; the management port has no cage.

    Returns:
        ``(system, interfaces)``: the switch itself, and one record per port
        holding the port fields plus ``transceiver``
    """
    transceivers = parse_transceivers(document)
    readings = parse_dom(document) if dom else {}

    interfaces = []
    for port in parse_ports(document):
        port["autoneg"] = None
        port["port_type"] = None
        port["nic"] = None
        record = transceivers.get(port["name"]) or transceiver_record(False)
        if dom:
            record["dom"] = readings.get(port["name"]) if record["present"] else None
        port["transceiver"] = record
        interfaces.append(port)

    return parse_system(document), interfaces
