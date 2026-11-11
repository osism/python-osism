# SPDX-License-Identifier: Apache-2.0

"""Helpers shared by the live hardware reports (``osism report ...``)."""

import re
from typing import Any, List, Optional

_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")


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
