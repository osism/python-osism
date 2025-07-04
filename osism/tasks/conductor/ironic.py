# SPDX-License-Identifier: Apache-2.0

import json

import jinja2

from osism import utils as osism_utils
from osism.tasks import netbox, openstack
from osism.tasks.conductor.netbox import (
    get_device_oob_ip,
    get_nb_device_query_list_ironic,
)
from osism.tasks.conductor.utils import (
    deep_compare,
    deep_decrypt,
    deep_merge,
    get_vault,
)


driver_params = {
    "ipmi": {
        "address": "ipmi_address",
        "port": "ipmi_port",
        "password": "ipmi_password",
        "username": "ipmi_username",
    },
    "redfish": {
        "address": "redfish_address",
        "password": "redfish_password",
        "username": "redfish_username",
    },
}


def _prepare_node_attributes(device, get_ironic_parameters):
    node_attributes = get_ironic_parameters()
    if (
        "ironic_parameters" in device.custom_fields
        and device.custom_fields["ironic_parameters"]
    ):
        deep_merge(node_attributes, device.custom_fields["ironic_parameters"])

    vault = get_vault()
    deep_decrypt(node_attributes, vault)

    node_secrets = device.custom_fields.get("secrets", {})
    if node_secrets is None:
        node_secrets = {}
    deep_decrypt(node_secrets, vault)

    if (
        "driver" in node_attributes
        and node_attributes["driver"] in driver_params.keys()
    ):
        if "driver_info" in node_attributes:
            unused_drivers = [
                driver
                for driver in driver_params.keys()
                if driver != node_attributes["driver"]
            ]
            for key in list(node_attributes["driver_info"].keys()):
                for driver in unused_drivers:
                    if key.startswith(driver + "_"):
                        node_attributes["driver_info"].pop(key, None)

            username_key = driver_params[node_attributes["driver"]]["username"]
            if username_key in node_attributes["driver_info"]:
                node_attributes["driver_info"][username_key] = (
                    jinja2.Environment(loader=jinja2.BaseLoader())
                    .from_string(node_attributes["driver_info"][username_key])
                    .render(
                        remote_board_username=str(
                            node_secrets.get("remote_board_username", "admin")
                        )
                    )
                )

            password_key = driver_params[node_attributes["driver"]]["password"]
            if password_key in node_attributes["driver_info"]:
                node_attributes["driver_info"][password_key] = (
                    jinja2.Environment(loader=jinja2.BaseLoader())
                    .from_string(node_attributes["driver_info"][password_key])
                    .render(
                        remote_board_password=str(
                            node_secrets.get("remote_board_password", "password")
                        )
                    )
                )

            address_key = driver_params[node_attributes["driver"]]["address"]
            if address_key in node_attributes["driver_info"]:
                oob_ip_result = get_device_oob_ip(device)
                if oob_ip_result:
                    oob_ip, _ = oob_ip_result
                    node_attributes["driver_info"][address_key] = (
                        jinja2.Environment(loader=jinja2.BaseLoader())
                        .from_string(node_attributes["driver_info"][address_key])
                        .render(remote_board_address=oob_ip)
                    )
    node_attributes.update({"resource_class": device.name})
    if "extra" not in node_attributes:
        node_attributes["extra"] = {}
    if "instance_info" in node_attributes and node_attributes["instance_info"]:
        node_attributes["extra"].update(
            {"instance_info": json.dumps(node_attributes["instance_info"])}
        )
    if (
        "netplan_parameters" in device.custom_fields
        and device.custom_fields["netplan_parameters"]
    ):
        node_attributes["extra"].update(
            {
                "netplan_parameters": json.dumps(
                    device.custom_fields["netplan_parameters"]
                )
            }
        )
    if (
        "frr_parameters" in device.custom_fields
        and device.custom_fields["frr_parameters"]
    ):
        node_attributes["extra"].update(
            {"frr_parameters": json.dumps(device.custom_fields["frr_parameters"])}
        )

    return node_attributes


def sync_ironic(request_id, get_ironic_parameters, force_update=False):
    osism_utils.push_task_output(
        request_id,
        "Starting NetBox device synchronisation with ironic\n",
    )
    devices = set()
    nb_device_query_list = get_nb_device_query_list_ironic()
    for nb_device_query in nb_device_query_list:
        devices |= set(netbox.get_devices(**nb_device_query))

    # NOTE: Find nodes in Ironic which are no longer present in NetBox and remove them
    device_names = {dev.name for dev in devices}
    nodes = openstack.baremetal_node_list()
    for node in nodes:
        osism_utils.push_task_output(
            request_id, f"Looking for {node['Name']} in NetBox\n"
        )
        if node["Name"] not in device_names:
            if (
                not node["Instance UUID"]
                and node["Provisioning State"] in ["enroll", "manageable", "available"]
                and node["Power State"] in ["power off", None]
            ):
                osism_utils.push_task_output(
                    request_id,
                    f"Cleaning up baremetal node not found in NetBox: {node['Name']}\n",
                )
                for port in openstack.baremetal_port_list(
                    details=False, attributes=dict(node_uuid=node["UUID"])
                ):
                    openstack.baremetal_port_delete(port.id)
                openstack.baremetal_node_delete(node["UUID"])
            else:
                osism_utils.push_task_output(
                    f"Cannot remove baremetal node because it is still provisioned or running: {node}"
                )

    # NOTE: Find nodes in NetBox which are not present in Ironic and add them
    for device in devices:
        osism_utils.push_task_output(
            request_id, f"Looking for {device.name} in ironic\n"
        )

        node_interfaces = list(netbox.get_interfaces_by_device(device.name))

        node_attributes = _prepare_node_attributes(device, get_ironic_parameters)
        ports_attributes = [
            dict(address=interface.mac_address)
            for interface in node_interfaces
            if interface.enabled and not interface.mgmt_only and interface.mac_address
        ]

        lock = osism_utils.create_redlock(
            key=f"lock_osism_tasks_conductor_sync_ironic-{device.name}",
            auto_release_time=600,
        )
        if lock.acquire(timeout=120):
            try:
                osism_utils.push_task_output(
                    request_id, f"Processing device {device.name}\n"
                )
                node = openstack.baremetal_node_show(device.name, ignore_missing=True)
                if not node:
                    osism_utils.push_task_output(
                        request_id, f"Creating baremetal node for {device.name}\n"
                    )
                    node = openstack.baremetal_node_create(device.name, node_attributes)
                else:
                    # NOTE: The listener service only reacts to changes in the baremetal node. Explicitly sync provision and power state in case updates were missed by the listener.
                    if (
                        device.custom_fields["provision_state"]
                        != node["provision_state"]
                    ):
                        netbox.set_provision_state(device.name, node["provision_state"])
                    if device.custom_fields["power_state"] != node["power_state"]:
                        netbox.set_power_state(device.name, node["power_state"])
                    # NOTE: Check whether the baremetal node needs to be updated
                    node_updates = {}
                    deep_compare(node_attributes, node, node_updates)
                    if "driver_info" in node_updates:
                        # NOTE: The password is not returned by ironic, so we cannot make a comparision and it would always be updated. Therefore we pop it from the dictionary
                        password_key = driver_params[node_attributes["driver"]][
                            "password"
                        ]
                        if password_key in node_updates["driver_info"]:
                            node_updates["driver_info"].pop(password_key, None)
                            if not node_updates["driver_info"]:
                                node_updates.pop("driver_info", None)
                    if node_updates or force_update:
                        osism_utils.push_task_output(
                            request_id,
                            f"Updating baremetal node for {device.name} with {node_updates}\n",
                        )
                        # NOTE: Do the actual updates with all values in node_attributes. Otherwise nested dicts like e.g. driver_info will be overwritten as a whole and contain only changed values
                        node = openstack.baremetal_node_update(
                            node["uuid"], node_attributes
                        )

                node_ports = openstack.baremetal_port_list(
                    details=False, attributes=dict(node_uuid=node["uuid"])
                )
                # NOTE: Baremetal ports are only required for (i)pxe boot
                for port_attributes in ports_attributes:
                    port_attributes.update({"node_id": node["uuid"]})
                    port = [
                        port
                        for port in node_ports
                        if port_attributes["address"].upper() == port["address"].upper()
                    ]
                    if not port:
                        osism_utils.push_task_output(
                            request_id,
                            f"Creating baremetal port with MAC address {port_attributes['address']} for {device.name}\n",
                        )
                        openstack.baremetal_port_create(port_attributes)
                    else:
                        node_ports.remove(port[0])
                for node_port in node_ports:
                    # NOTE: Delete remaining ports not found in NetBox
                    osism_utils.push_task_output(
                        request_id,
                        f"Deleting baremetal port with MAC address {node_port['address']} for {device.name}\n",
                    )
                    openstack.baremetal_port_delete(node_port["id"])

                node_validation = openstack.baremetal_node_validate(node["uuid"])
                if node_validation["management"].result:
                    osism_utils.push_task_output(
                        request_id,
                        f"Validation of management interface successful for baremetal node for {device.name}\n",
                    )
                    if node["provision_state"] == "enroll":
                        osism_utils.push_task_output(
                            request_id,
                            f"Transitioning baremetal node to manageable state for {device.name}\n",
                        )
                        node = openstack.baremetal_node_set_provision_state(
                            node["uuid"], "manage"
                        )
                        node = openstack.baremetal_node_wait_for_nodes_provision_state(
                            node["uuid"], "manageable"
                        )
                        osism_utils.push_task_output(
                            request_id,
                            f"Baremetal node for {device.name} is manageable\n",
                        )
                    if node_validation["boot"].result:
                        osism_utils.push_task_output(
                            request_id,
                            f"Validation of boot interface successful for baremetal node for {device.name}\n",
                        )
                        if node["provision_state"] == "manageable":
                            osism_utils.push_task_output(
                                request_id,
                                f"Transitioning baremetal node to available state for {device.name}\n",
                            )
                            node = openstack.baremetal_node_set_provision_state(
                                node["uuid"], "provide"
                            )
                            node = (
                                openstack.baremetal_node_wait_for_nodes_provision_state(
                                    node["uuid"], "available"
                                )
                            )
                            osism_utils.push_task_output(
                                request_id,
                                f"Baremetal node for {device.name} is available\n",
                            )
                    else:
                        osism_utils.push_task_output(
                            request_id,
                            f"Validation of boot interface failed for baremetal node for {device.name}\nReason: {node_validation['boot'].reason}\n",
                        )
                        if node["provision_state"] == "available":
                            # NOTE: Demote node to manageable
                            osism_utils.push_task_output(
                                request_id,
                                f"Transitioning baremetal node to manageable state for {device.name}\n",
                            )
                            node = openstack.baremetal_node_set_provision_state(
                                node["uuid"], "manage"
                            )
                            node = (
                                openstack.baremetal_node_wait_for_nodes_provision_state(
                                    node["uuid"], "manageable"
                                )
                            )
                            osism_utils.push_task_output(
                                request_id,
                                f"Baremetal node for {device.name} is manageable\n",
                            )
                else:
                    osism_utils.push_task_output(
                        request_id,
                        f"Validation of management interface failed for baremetal node for {device.name}\nReason: {node_validation['management'].reason}\n",
                    )
            except Exception as exc:
                osism_utils.push_task_output(
                    request_id,
                    f"Could not fully synchronize device {device.name} with ironic: {exc}\n",
                )
            finally:
                lock.release()

        else:
            osism_utils.push_task_output(
                "Could not acquire lock for node {device.name}"
            )

    osism_utils.finish_task_output(request_id, rc=0)
