# SPDX-License-Identifier: Apache-2.0

"""Shared NetBox-stub helpers for the interface-detection test modules.

Used by ``test_breakout_detection`` and ``test_port_channel_detection``;
the module is private (``_``-prefixed) so pytest does not collect it.
"""

from types import SimpleNamespace


def _make_sonic_device(device_id=1, name="sw1", hwsku="TEST-HWSKU"):
    """Build a NetBox device stub carrying ``custom_fields.sonic_parameters.hwsku``."""
    return SimpleNamespace(
        id=device_id,
        name=name,
        custom_fields={"sonic_parameters": {"hwsku": hwsku}},
    )


def _make_iface(name, *, speed=None, type_value=None, lag=None):
    """Build a NetBox-shaped interface stub.

    ``type_value`` becomes ``interface.type.value`` (set ``None`` for no type),
    ``speed`` mirrors ``interface.speed``, and ``lag`` is the LAG-parent stub.
    """
    return SimpleNamespace(
        name=name,
        speed=speed,
        type=SimpleNamespace(value=type_value) if type_value else None,
        lag=lag,
    )


def _make_lag(name, lag_id=99):
    """Build a LAG-typed parent interface stub (``type.value == "lag"``)."""
    return SimpleNamespace(
        name=name,
        id=lag_id,
        speed=None,
        type=SimpleNamespace(value="lag"),
        lag=None,
    )
