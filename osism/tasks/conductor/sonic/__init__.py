# SPDX-License-Identifier: Apache-2.0

"""SONiC configuration management package."""

from .config_generator import generate_sonic_config
from .exporter import save_config_to_netbox, export_config_to_file
from .sync import sync_sonic
from .bfd import add_bfd_configurations, should_interface_have_bfd
from .connections import (
    get_connected_interfaces,
    get_connected_device_for_sonic_interface,
    get_connected_device_via_interface,
    find_interconnected_devices,
    get_device_bgp_neighbors_via_loopback,
)

__all__ = [
    "generate_sonic_config",
    "save_config_to_netbox",
    "export_config_to_file",
    "sync_sonic",
    "add_bfd_configurations",
    "should_interface_have_bfd",
    "get_connected_interfaces",
    "get_connected_device_for_sonic_interface",
    "get_connected_device_via_interface",
    "find_interconnected_devices",
    "get_device_bgp_neighbors_via_loopback",
]
