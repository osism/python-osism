# SPDX-License-Identifier: Apache-2.0

"""Helpers shared by the live hardware reports (``osism report ...``)."""

import re
from typing import Any, Dict, List, Optional

_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)")
_SFF_DATE = re.compile(r"^(\d{2})(\d{2})(\d{2})(?:\s*\S{1,2})?$")


def normalize_mac(value: Any) -> Optional[str]:
    """Return a MAC address as lower-case, colon-separated string.

    Accepts the usual spellings (``AA:BB:..``, ``aa-bb-..``, ``aabb.ccdd..``).
    Returns ``None`` for anything that is not a MAC address and for the
    all-zero address, which drivers report when they have no permanent one.
    """
    if not value:
        return None
    digits = re.sub(r"[:.\-]", "", str(value).strip().lower())
    if not _MAC_DIGITS.match(digits) or digits == "0" * 12:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def natural_key(text: Any) -> List[Any]:
    """Sort key ordering embedded numbers by value (Ethernet2 < Ethernet10)."""
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", str(text or ""))
        if part != ""
    ]


def normalize_date_code(value: Any) -> Optional[str]:
    """Return the manufacturing date of a module as ``YYYY-MM-DD``.

    The EEPROM of a module holds the date as ``YYMMDD``, optionally followed
    by a lot code of two characters, and ``ethtool -m`` prints it like that.
    SONiC decodes it: Enterprise SONiC writes ``2022-09-07T00:00:00+00:00``,
    community SONiC ``2022-09-07`` followed by the lot code. A value in
    another format is returned as it is.
    """
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    match = _ISO_DATE.match(text)
    if match:
        return "-".join(match.groups())
    match = _SFF_DATE.match(text)
    if match and 1 <= int(match.group(2)) <= 12 and 1 <= int(match.group(3)) <= 31:
        return "20{}-{}-{}".format(*match.groups())
    return text


TRANSCEIVER_FIELDS = [
    "form_factor",
    "connector",
    "vendor",
    "vendor_oui",
    "part_number",
    "serial",
    "revision",
    "date_code",
    "firmware_active",
    "firmware_inactive",
    "compliance",
    "cable_length",
    "wavelength",
]


def transceiver_record(
    present: Optional[bool], error: Optional[str] = None
) -> Dict[str, Any]:
    """Return a transceiver record with every identity field unset.

    Args:
        present: True for a plugged-in module, False for a port without a
            module, None when the port has no module of its own or when it
            is unknown whether a module is plugged in
        error: Why it is unknown whether a module is plugged in. Set only
            with ``present = None``; a port without a module of its own,
            such as a virtual function, has none.
    """
    record: Dict[str, Any] = {"present": present, "error": error}
    record.update({name: None for name in TRANSCEIVER_FIELDS})
    return record


_CABLE_CONNECTORS = {"no separable connector", "copper pigtail"}
_CABLE_COMPLIANCE = re.compile(r"\b(?:passive|active)\b(?:\s+\w+)?\s+cable\b", re.I)


def is_cable_assembly(connector: Optional[str], compliance: Optional[str]) -> bool:
    """Tell whether a module is one end of a cable assembly (DAC or AOC).

    The length fields of a separable optic hold the reach it is rated for
    on a type of fibre, not the length of a cable. Only a cable assembly
    has a cable length. It has no separable connector, or a copper
    pigtail, or its compliance codes name a passive or active cable.
    """
    if (connector or "").strip().lower() in _CABLE_CONNECTORS:
        return True
    return bool(_CABLE_COMPLIANCE.search(compliance or ""))
