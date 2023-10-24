# SPDX-License-Identifier: CC-BY-NC-4.0
# Copyright OSISM GmbH, 2022-2023

from osism import utils


def update_network_interface_name(mac_address, network_interface_name):
    """Sets the network interface name from a performed
    introspection for an interface with a given MAC address."""

    interface_a = utils.nb.dcim.interfaces.get(mac_address=mac_address)
    interface_a.custom_fields = {"network_interface_name": network_interface_name}
    interface_a.save()
