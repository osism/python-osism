# SPDX-License-Identifier: Apache-2.0

import json

import jinja2

from osism import utils as osism_utils
from osism.tasks import netbox, openstack
from osism.tasks.conductor.netbox import (
    get_device_oob_ip,
    get_nb_device_query_list_ironic,
)
from osism.tasks.netbox import _matches_netbox_filter
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
    # Get base node attributes (no decryption needed)
    node_attributes = get_ironic_parameters()

    # Create vault instance for Custom Field decryption
    vault = get_vault()

    # Decrypt and merge ironic_parameters Custom Field if present
    if (
        "ironic_parameters" in device.custom_fields
        and device.custom_fields["ironic_parameters"]
    ):
        ironic_parameters_cf = device.custom_fields["ironic_parameters"]
        deep_decrypt(ironic_parameters_cf, vault)
        deep_merge(node_attributes, ironic_parameters_cf)

    # Decrypt secrets Custom Field
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


def sync_ironic(request_id, get_ironic_parameters, node_name=None, force=False):
    if node_name:
        osism_utils.push_task_output(
            request_id,
            f"Starting NetBox device synchronisation with ironic for node {node_name}\n",
        )
    else:
        osism_utils.push_task_output(
            request_id,
            "Starting NetBox device synchronisation with ironic\n",
        )

    # Check NetBox API connectivity
    try:
        osism_utils.push_task_output(
            request_id, "Checking NetBox API connectivity...\n"
        )
        osism_utils.nb.status()
        osism_utils.push_task_output(request_id, "NetBox API is reachable\n")
    except Exception as e:
        osism_utils.push_task_output(
            request_id, f"ERROR: NetBox API is not reachable: {e}\n"
        )
        osism_utils.finish_task_output(request_id, rc=1)
        return

    # Check Ironic API connectivity
    try:
        osism_utils.push_task_output(
            request_id, "Checking Ironic API connectivity...\n"
        )
        conn = osism_utils.get_openstack_connection()
        # Try a simple API call to verify connectivity
        list(conn.baremetal.nodes(limit=1))
        osism_utils.push_task_output(request_id, "Ironic API is reachable\n")
    except Exception as e:
        osism_utils.push_task_output(
            request_id, f"ERROR: Ironic API is not reachable: {e}\n"
        )
        osism_utils.finish_task_output(request_id, rc=1)
        return

    devices = set()
    nb_device_query_list = get_nb_device_query_list_ironic()
    for nb_device_query in nb_device_query_list:
        devices |= set(netbox.get_devices(**nb_device_query))

    # Filter devices by node_name if specified
    if node_name:
        devices = {dev for dev in devices if dev.name == node_name}
        if not devices:
            osism_utils.push_task_output(
                request_id,
                f"Node {node_name} not found in NetBox\n",
            )
            osism_utils.finish_task_output(request_id, rc=1)
            return

    # NOTE: Find nodes in Ironic which are no longer present in NetBox and remove them
    device_names = {dev.name for dev in devices}
    nodes = openstack.baremetal_node_list()

    # Filter nodes by node_name if specified
    if node_name:
        nodes = [node for node in nodes if node["name"] == node_name]

    for node in nodes:
        osism_utils.push_task_output(
            request_id, f"Looking for {node['name']} in NetBox\n"
        )
        if node["name"] not in device_names:
            if (
                not node["instance_uuid"]
                and node["provision_state"]
                in ["enroll", "manageable", "available", "clean failed"]
                and node["power_state"] in ["power off", None]
            ):
                osism_utils.push_task_output(
                    request_id,
                    f"Cleaning up baremetal node not found in NetBox: {node['name']}\n",
                )
                if node["provision_state"] == "clean failed":
                    # NOTE: Move node to manageable to allow deletion
                    node = openstack.baremetal_node_set_provision_state(
                        node["uuid"], "manage"
                    )
                    node = openstack.baremetal_node_wait_for_nodes_provision_state(
                        node["uuid"], "manageable"
                    )
                for port in openstack.baremetal_port_list(
                    details=False, attributes=dict(node_uuid=node["uuid"])
                ):
                    openstack.baremetal_port_delete(port.id)
                openstack.baremetal_node_delete(node["uuid"])
            else:
                osism_utils.push_task_output(
                    request_id,
                    f"Cannot remove baremetal node because it is still provisioned or running: {node}\n",
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
                    if node_updates or force:
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
                    if node["provision_state"] in ["enroll", "clean failed"]:
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
                request_id, f"Could not acquire lock for node {device.name}\n"
            )

    osism_utils.finish_task_output(request_id, rc=0)


def sync_netbox_from_ironic(request_id, node_name=None, netbox_filter=None):
    """Sync Ironic node states to NetBox

    This function synchronizes the state of Ironic baremetal nodes to NetBox.
    It updates three custom fields in NetBox:
    - provision_state: The current provision state of the node
    - power_state: The current power state of the node
    - maintenance: Whether the node is in maintenance mode

    The sync is performed for the primary NetBox instance and all configured
    secondary NetBox instances. NetBox instances can be filtered.

    Args:
        request_id: The Celery task request ID for output tracking
        node_name: Optional name of a specific node to sync. If None, all nodes are synced.
        netbox_filter: Optional filter (substring match, case-insensitive). If provided,
                      only NetBox instances matching the filter will be updated.
                      The filter matches against:
                      - NetBox name (NETBOX_NAME attribute for secondaries, 'primary' for primary)
                      - NetBox site (NETBOX_SITE attribute if configured)
                      - NetBox URL (base_url)
                      Examples: 'primary', 'site-a', 'backup', 'netbox.example.com'
    """
    filter_msg = f" (NetBox filter: {netbox_filter})" if netbox_filter else ""
    if node_name:
        osism_utils.push_task_output(
            request_id,
            f"Starting Ironic to NetBox synchronisation for node {node_name}{filter_msg}\n",
        )
    else:
        osism_utils.push_task_output(
            request_id,
            f"Starting Ironic to NetBox synchronisation{filter_msg}\n",
        )

    # Determine which NetBox instances to check based on filter
    reachable_secondaries = []

    if netbox_filter:
        # When filter is set, only check NetBox instances that match the filter
        filtered_netboxes = []

        # Check if primary matches filter
        if _matches_netbox_filter(osism_utils.nb, netbox_filter, is_primary=True):
            filtered_netboxes.append(("primary", osism_utils.nb))

        # Check which secondaries match filter
        for nb in osism_utils.secondary_nb_list:
            if _matches_netbox_filter(nb, netbox_filter, is_primary=False):
                filtered_netboxes.append(("secondary", nb))

        if not filtered_netboxes:
            osism_utils.push_task_output(
                request_id,
                f"ERROR: No NetBox instances match filter: {netbox_filter}\n",
            )
            osism_utils.finish_task_output(request_id, rc=1)
            return

        # Test connectivity for filtered instances only
        primary_reachable = False
        for nb_type, nb in filtered_netboxes:
            try:
                name = (
                    getattr(nb, "netbox_name", None) if nb_type == "secondary" else None
                )
                site = (
                    getattr(nb, "netbox_site", None) if nb_type == "secondary" else None
                )
                info_parts = []
                if name:
                    info_parts.append(f"Name: {name}")
                if site:
                    info_parts.append(f"Site: {site}")
                info = f" ({', '.join(info_parts)})" if info_parts else ""

                osism_utils.push_task_output(
                    request_id,
                    f"Checking connectivity to filtered NetBox: {nb.base_url}{info}...\n",
                )
                nb.status()

                if nb_type == "primary":
                    primary_reachable = True
                    osism_utils.push_task_output(
                        request_id,
                        f"Filtered primary NetBox is reachable: {nb.base_url}\n",
                    )
                else:
                    reachable_secondaries.append(nb)
                    osism_utils.push_task_output(
                        request_id,
                        f"Filtered secondary NetBox is reachable: {nb.base_url}{info}\n",
                    )
            except Exception as e:
                # Build error message
                if nb_type == "primary":
                    osism_utils.push_task_output(
                        request_id,
                        f"WARNING: Filtered primary NetBox not reachable: {nb.base_url}: {e}\n",
                    )
                else:
                    name = getattr(nb, "netbox_name", None)
                    site = getattr(nb, "netbox_site", None)
                    info_parts = []
                    if name:
                        info_parts.append(f"Name: {name}")
                    if site:
                        info_parts.append(f"Site: {site}")
                    info = f" ({', '.join(info_parts)})" if info_parts else ""
                    osism_utils.push_task_output(
                        request_id,
                        f"WARNING: Filtered secondary NetBox not reachable: {nb.base_url}{info}: {e}\n",
                    )

        # If no filtered instances are reachable, error out
        if not primary_reachable and not reachable_secondaries:
            osism_utils.push_task_output(
                request_id,
                f"ERROR: No NetBox instances matching filter '{netbox_filter}' are reachable\n",
            )
            osism_utils.finish_task_output(request_id, rc=1)
            return
    else:
        # Original behavior when no filter is set: check primary and all secondaries
        # Check NetBox API connectivity
        try:
            osism_utils.push_task_output(
                request_id, "Checking NetBox API connectivity...\n"
            )
            osism_utils.nb.status()
            osism_utils.push_task_output(request_id, "NetBox API is reachable\n")
        except Exception as e:
            osism_utils.push_task_output(
                request_id, f"ERROR: NetBox API is not reachable: {e}\n"
            )
            osism_utils.finish_task_output(request_id, rc=1)
            return

        # Check secondary NetBox instances connectivity
        if osism_utils.secondary_nb_list:
            osism_utils.push_task_output(
                request_id, "Checking secondary NetBox instances connectivity...\n"
            )
            for nb in osism_utils.secondary_nb_list:
                # Build info message
                name = getattr(nb, "netbox_name", None)
                site = getattr(nb, "netbox_site", None)
                info_parts = []
                if name:
                    info_parts.append(f"Name: {name}")
                if site:
                    info_parts.append(f"Site: {site}")
                info = f" ({', '.join(info_parts)})" if info_parts else ""

                try:
                    osism_utils.push_task_output(
                        request_id,
                        f"Checking connectivity to NetBox: {nb.base_url}{info}...\n",
                    )
                    nb.status()
                    reachable_secondaries.append(nb)

                    osism_utils.push_task_output(
                        request_id,
                        f"Secondary NetBox is reachable: {nb.base_url}{info}\n",
                    )
                except Exception as e:
                    osism_utils.push_task_output(
                        request_id,
                        f"WARNING: Secondary NetBox not reachable: {nb.base_url}{info}: {e}\n",
                    )

    # Check Ironic API connectivity
    try:
        osism_utils.push_task_output(
            request_id, "Checking Ironic API connectivity...\n"
        )
        conn = osism_utils.get_openstack_connection()
        # Try a simple API call to verify connectivity
        list(conn.baremetal.nodes(limit=1))
        osism_utils.push_task_output(request_id, "Ironic API is reachable\n")
    except Exception as e:
        osism_utils.push_task_output(
            request_id, f"ERROR: Ironic API is not reachable: {e}\n"
        )
        osism_utils.finish_task_output(request_id, rc=1)
        return

    # Get all Ironic nodes
    nodes = openstack.baremetal_node_list()

    # Filter by node_name if specified
    if node_name:
        nodes = [n for n in nodes if n["name"] == node_name]
        if not nodes:
            osism_utils.push_task_output(
                request_id,
                f"Node {node_name} not found in Ironic\n",
            )
            osism_utils.finish_task_output(request_id, rc=1)
            return

    # Sync each node to NetBox
    failed_devices = []
    for node in nodes:
        # Adjust message based on whether secondaries are actually being synced
        if reachable_secondaries:
            sync_msg = (
                f"Syncing state of {node['name']} to NetBox (including secondaries)\n"
            )
        else:
            sync_msg = f"Syncing state of {node['name']} to NetBox\n"

        osism_utils.push_task_output(request_id, sync_msg)

        # Track if this device failed to sync
        device_failed = False

        # Update all three states (each function handles primary + secondary NetBox instances)
        # Pass netbox_filter to only update matching NetBox instances
        # Pass reachable_secondaries to only use reachable secondary instances
        if not netbox.set_provision_state(
            node["name"],
            node["provision_state"],
            netbox_filter=netbox_filter,
            secondary_nb_list=reachable_secondaries,
        ):
            device_failed = True

        if not netbox.set_power_state(
            node["name"],
            node["power_state"],
            netbox_filter=netbox_filter,
            secondary_nb_list=reachable_secondaries,
        ):
            device_failed = True

        if not netbox.set_maintenance(
            node["name"],
            state=node["is_maintenance"],
            netbox_filter=netbox_filter,
            secondary_nb_list=reachable_secondaries,
        ):
            device_failed = True

        if device_failed:
            failed_devices.append(node["name"])

    # Report failed devices if any
    if failed_devices:
        osism_utils.push_task_output(
            request_id,
            f"WARNING: Failed to sync {len(failed_devices)} device(s) due to lock timeout: {', '.join(failed_devices)}\n",
        )

    osism_utils.finish_task_output(request_id, rc=0)
