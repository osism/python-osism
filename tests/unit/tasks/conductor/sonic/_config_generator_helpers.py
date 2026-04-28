# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the SONiC ``config_generator`` unit-test split.

The leading underscore keeps pytest from collecting this module as a test file.
"""

import json
from types import SimpleNamespace
from unittest.mock import mock_open

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import TOP_LEVEL_SCAFFOLD_KEYS


def make_base_config(version=None):
    """Build a base ``config_db.json`` scaffold with every top-level key the
    orchestrator (and its mocked helpers) index into directly.

    The key list is sourced from the production-side ``TOP_LEVEL_SCAFFOLD_KEYS``
    constant so the helper cannot drift when keys are added or removed.
    Optionally seeds ``VERSIONS.DATABASE.VERSION`` so the version-handling
    branch can be exercised explicitly.
    """

    cfg = {key: {} for key in TOP_LEVEL_SCAFFOLD_KEYS}
    if version is not None:
        cfg["VERSIONS"] = {"DATABASE": {"VERSION": version}}
    return cfg


def patch_base_config(mocker, *, exists=True, base_config=None, raise_on_open=None):
    """Patch ``os.path.exists`` and ``builtins.open`` for the base-config load.

    - ``exists=True`` and ``base_config`` provided → ``open`` returns that
      JSON-encoded scaffold.
    - ``exists=False`` → ``open`` is not patched (the orchestrator never
      reaches the ``with open`` path).
    - ``raise_on_open`` → ``open`` raises this exception (e.g. ``OSError``).
    """

    mocker.patch.object(config_generator.os.path, "exists", return_value=exists)
    if not exists:
        return
    if raise_on_open is not None:
        mocker.patch("builtins.open", side_effect=raise_on_open)
        return
    cfg = base_config if base_config is not None else make_base_config()
    mocker.patch("builtins.open", mock_open(read_data=json.dumps(cfg)))


def make_iface(name, *, mgmt_only=False, type_value=None, iface_id=None):
    return SimpleNamespace(
        id=iface_id if iface_id is not None else id(object()),
        name=name,
        mgmt_only=mgmt_only,
        type=SimpleNamespace(value=type_value) if type_value is not None else None,
    )


def make_ip(address):
    return SimpleNamespace(address=address)


def seed_metalbox_cache(metalbox_id=10, name="mb", *, interfaces):
    """Set ``_metalbox_devices_cache`` directly (skip ``_load`` to keep tests
    fast and independent of NetBox-shape concerns).

    ``interfaces`` is a list of ``(interface_obj, is_vlan, [ip_strings])``.
    """
    cache_entry = {
        "device": SimpleNamespace(id=metalbox_id, name=name),
        "interfaces": {},
    }
    for iface, is_vlan, addresses in interfaces:
        cache_entry["interfaces"][iface.id] = {
            "interface": iface,
            "is_vlan": is_vlan,
            "ips": [make_ip(addr) for addr in addresses],
        }
    config_generator._metalbox_devices_cache = {metalbox_id: cache_entry}
