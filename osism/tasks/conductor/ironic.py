# SPDX-License-Identifier: Apache-2.0

import ipaddress
import json
import re
import textwrap

import jinja2
import yaml
from loguru import logger

from osism import settings

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
    mask_secrets,
)


SUPPORTED_IPA_TYPES = {
    "yrzn001": {
        "osism-ipa-as": "frr_local_as",
        "osism-ipa-ipv4": "frr_loopback_v4",
        "osism-ipa-ipv6": "frr_loopback_v6",
        "osism-ipa-metalbox": None,  # resolved via metalbox lookup
    },
}


def _derive_as_from_hostname_yrzn(hostname):
    """Derive the AS number from the hostname (yrzn scheme).

    Hostname schema: {type}-{role}-{dc}-{server}-{rack}-{x}
    AS schema: 42DDDTCCSS
      - 42  = fixed prefix
      - DDD = DC number (hardcoded to 001 for now)
      - T   = type (4=default, 5=Storage)
      - CC  = rack number (2 digits)
      - SS  = server number (2 digits)

    Example: stor-nw-22-60-59-6 -> 4200155960

    >>> _derive_as_from_hostname_yrzn("stor-nw-22-60-59-6")
    '4200155960'
    """
    parts = hostname.split("-")
    if len(parts) < 5:
        return None

    t = "5" if parts[0] == "stor" else "4"

    server = parts[3].zfill(2)
    rack = parts[4].zfill(2)

    return f"42001{t}{rack}{server}"


def _get_metalbox_primary_ip4_fallback():
    """Fallback: find a metalbox using NETBOX_FILTER_CONDUCTOR_IRONIC filters.

    Takes the NETBOX_FILTER_CONDUCTOR_IRONIC filter, removes the tag filter,
    and searches for devices with role=metalbox instead.

    Returns:
        str: The metalbox's primary IPv4 address (without prefix), or None
    """
    from osism import utils

    try:
        nb_device_query_list = yaml.safe_load(settings.NETBOX_FILTER_CONDUCTOR_IRONIC)
        if type(nb_device_query_list) is not list:
            return None
    except yaml.YAMLError:
        return None

    for nb_device_query in nb_device_query_list:
        if type(nb_device_query) is not dict:
            continue
        query = {k: v for k, v in nb_device_query.items() if k != "tag"}
        query["role"] = "metalbox"
        metalboxes = utils.nb.dcim.devices.filter(**query)
        for metalbox in metalboxes:
            if metalbox.primary_ip4:
                return str(metalbox.primary_ip4).split("/")[0]

    logger.warning("No metalbox found via fallback filter either")
    return None


def _get_metalbox_primary_ip4(device):
    """Get the primary IPv4 address of the metalbox managing this device.

    Finds the metalbox whose interface shares the same subnet as the
    device's OOB IP address, then returns that metalbox's primary_ip4.

    If no metalbox is found via subnet matching, falls back to searching
    for a metalbox using the NETBOX_FILTER_CONDUCTOR_IRONIC filters
    (without the tag filter and with role set to metalbox).

    Args:
        device: NetBox device object

    Returns:
        str: The metalbox's primary IPv4 address (without prefix), or None
    """
    from osism import utils

    oob_ip_result = get_device_oob_ip(device)
    if not oob_ip_result:
        return None

    oob_ip, _ = oob_ip_result
    oob_addr = ipaddress.ip_address(oob_ip)

    metalboxes = utils.nb.dcim.devices.filter(role="metalbox")
    for metalbox in metalboxes:
        interfaces = utils.nb.dcim.interfaces.filter(device_id=metalbox.id)
        for interface in interfaces:
            ip_addresses = utils.nb.ipam.ip_addresses.filter(
                assigned_object_id=interface.id,
            )
            for ip_addr in ip_addresses:
                if ip_addr.address:
                    network = ipaddress.ip_network(ip_addr.address, strict=False)
                    if oob_addr in network:
                        if metalbox.primary_ip4:
                            return str(metalbox.primary_ip4).split("/")[0]
                        return None

    logger.debug(
        f"No metalbox found via subnet matching for device {device.name}, "
        "trying fallback via NETBOX_FILTER_CONDUCTOR_IRONIC"
    )
    return _get_metalbox_primary_ip4_fallback()


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


def _render_templates(obj, template_vars):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and "{{" in value:
                obj[key] = (
                    jinja2.Environment(loader=jinja2.BaseLoader())
                    .from_string(value)
                    .render(**template_vars)
                )
            elif isinstance(value, (dict, list)):
                _render_templates(value, template_vars)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and "{{" in item:
                obj[i] = (
                    jinja2.Environment(loader=jinja2.BaseLoader())
                    .from_string(item)
                    .render(**template_vars)
                )
            elif isinstance(item, (dict, list)):
                _render_templates(item, template_vars)


def _prepare_node_attributes(
    device, get_ironic_parameters, skip_kernel_params=None, extra_kernel_params=None
):
    # Get base node attributes (no decryption needed)
    node_attributes = get_ironic_parameters()

    # Create vault instance for Custom Field decryption
    vault = get_vault()

    # Decrypt and merge ironic_parameters from Config Context if present
    if (
        hasattr(device, "config_context")
        and device.config_context
        and "ironic_parameters" in device.config_context
    ):
        config_context_ironic = device.config_context["ironic_parameters"]
        deep_decrypt(config_context_ironic, vault)
        deep_merge(node_attributes, config_context_ironic)

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

    # Build template variables for Jinja2 rendering
    template_vars = {}

    template_vars["remote_board_username"] = str(
        node_secrets.get("remote_board_username", "admin")
    ).strip()
    template_vars["remote_board_password"] = str(
        node_secrets.get("remote_board_password", "password")
    ).strip()

    oob_ip_result = get_device_oob_ip(device)
    if oob_ip_result:
        oob_ip, _ = oob_ip_result
        template_vars["remote_board_address"] = oob_ip

    for key, value in node_secrets.items():
        if key.startswith("ironic_osism_"):
            template_vars[key] = str(value).strip()

    # Render Jinja2 templates in all string values
    _render_templates(node_attributes, template_vars)

    node_attributes.update({"resource_class": device.name})
    if "extra" not in node_attributes:
        node_attributes["extra"] = {}
    if "instance_info" in node_attributes and node_attributes["instance_info"]:
        kap = node_attributes["instance_info"].get("kernel_append_params", "")
        if kap:
            match = re.search(r"osism-ipa-type=(\S+)", kap)
            if match and match.group(1) in SUPPORTED_IPA_TYPES:
                ipa_type = match.group(1)
                frr = device.custom_fields.get("frr_parameters") or {}
                deep_decrypt(frr, vault)
                derived_as = (
                    _derive_as_from_hostname_yrzn(device.name)
                    if ipa_type == "yrzn001"
                    else None
                )
                for kap_name, frr_key in SUPPORTED_IPA_TYPES[ipa_type].items():
                    if kap_name == "osism-ipa-metalbox":
                        metalbox_ip = _get_metalbox_primary_ip4(device)
                        if metalbox_ip:
                            kap += f" {kap_name}={metalbox_ip}"
                    elif frr_key and frr_key in frr:
                        kap += f" {kap_name}={frr[frr_key]}"
                    elif kap_name == "osism-ipa-as" and derived_as:
                        kap += f" {kap_name}={derived_as}"
                node_attributes["instance_info"]["kernel_append_params"] = kap

        if skip_kernel_params:
            kap = node_attributes["instance_info"].get("kernel_append_params", "")
            if kap:
                parts = kap.split()
                filtered = [
                    p for p in parts if p.split("=", 1)[0] not in skip_kernel_params
                ]
                node_attributes["instance_info"]["kernel_append_params"] = " ".join(
                    filtered
                )

        if extra_kernel_params:
            kap = node_attributes["instance_info"].get("kernel_append_params", "")
            for param in extra_kernel_params:
                kap += f" {param}" if kap else param
            node_attributes["instance_info"]["kernel_append_params"] = kap

        # NOTE: Also store kernel_append_params in driver_info so they persist
        # through undeploy. Ironic clears instance_info on undeploy but keeps
        # driver_info. Ironic's get_kernel_append_params() falls back to
        # driver_info when instance_info is empty, ensuring the params are
        # available during automated cleaning after undeploy.
        final_kap = node_attributes["instance_info"].get("kernel_append_params", "")
        if final_kap:
            if "driver_info" not in node_attributes:
                node_attributes["driver_info"] = {}
            node_attributes["driver_info"]["kernel_append_params"] = final_kap

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
        frr_params = device.custom_fields["frr_parameters"]
        deep_decrypt(frr_params, vault)
        node_attributes["extra"].update({"frr_parameters": json.dumps(frr_params)})

    return node_attributes, template_vars


def _prettify_for_display(obj):
    """Parse JSON strings in 'extra' back to dicts for readable display."""
    import copy

    result = copy.deepcopy(obj)
    if (
        isinstance(result, dict)
        and "extra" in result
        and isinstance(result["extra"], dict)
    ):
        for key, value in result["extra"].items():
            if isinstance(value, str):
                try:
                    result["extra"][key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass
    return result


def _sync_ironic_device(
    request_id, device, node_attributes, ports_attributes, adopt, force
):
    osism_utils.push_task_output(request_id, f"Processing device {device.name}\n")
    node = openstack.baremetal_node_show(device.name, ignore_missing=True)
    if not node:
        osism_utils.push_task_output(
            request_id, f"Creating baremetal node for {device.name}\n"
        )
        # NOTE: Create node without automated_clean, so it can be
        # transitioned fast from managable to available later. It
        # is also safer to not clean during sync, so that nodes may
        # later be adopted with their provisioned data.
        node_attributes.update(dict(automated_clean=False))
        node = openstack.baremetal_node_create(device.name, node_attributes)
    else:
        # NOTE: Check whether the baremetal node needs to be updated
        node_updates = {}
        deep_compare(node_attributes, node, node_updates)
        if "driver_info" in node_updates:
            # NOTE: The password is not returned by ironic, so we cannot make a comparision and it would always be updated. Therefore we pop it from the dictionary
            password_key = driver_params[node_attributes["driver"]]["password"]
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
            node = openstack.baremetal_node_update(node["uuid"], node_attributes)

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

    # NOTE: Adopt nodes with provisioning state active in NetBox or if explicitly requested
    is_adoption = adopt or device.custom_fields.get("provision_state", None) == "active"

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
            node = openstack.baremetal_node_set_provision_state(node["uuid"], "manage")
            node = openstack.baremetal_node_wait_for_nodes_provision_state(
                node["uuid"], "manageable"
            )
            osism_utils.push_task_output(
                request_id,
                f"Baremetal node for {device.name} is manageable\n",
            )
            if not is_adoption and node["power_state"] != "power off":
                # NOTE: Ironic keeps the power state found during enroll. We set the node power state to off in order to have a defined state for all newly synced nodes
                osism_utils.push_task_output(
                    request_id,
                    f"Setting power state to 'power off' for {device.name}\n",
                )
                node = openstack.baremetal_node_set_power_state(
                    node["uuid"], "power off", wait=True, timeout=300
                )
                osism_utils.push_task_output(
                    request_id,
                    f"Successfully transitioned power state to 'power off' for {device.name}\n",
                )

        if node_validation["boot"].result:
            osism_utils.push_task_output(
                request_id,
                f"Validation of boot interface successful for baremetal node for {device.name}\n",
            )
            if is_adoption and node["provision_state"] == "available":
                # Note: Prepare adoption of available nodes by moving them to manageable
                osism_utils.push_task_output(
                    request_id,
                    f"Prepare adoption of available baremetal node by transitioning to manageable state for {device.name}\n",
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
            if node["provision_state"] == "manageable":
                if is_adoption:
                    osism_utils.push_task_output(
                        request_id,
                        f"Adopting baremetal node for {device.name}\n",
                    )
                    node = openstack.baremetal_node_set_provision_state(
                        node["uuid"], "adopt"
                    )
                    node = openstack.baremetal_node_wait_for_nodes_provision_state(
                        node["uuid"], "active"
                    )
                    osism_utils.push_task_output(
                        request_id,
                        f"Baremetal node for {device.name} is active\n",
                    )
                else:
                    osism_utils.push_task_output(
                        request_id,
                        f"Transitioning baremetal node to available state for {device.name}\n",
                    )
                    if node["automated_clean"]:
                        # NOTE: Skip automated cleaning on transition from managable to available. We are waiting for the transition and do not want to wait on cleaning at this point
                        node = openstack.baremetal_node_update(
                            node["uuid"], dict(automated_clean=False)
                        )
                    try:
                        openstack.baremetal_node_set_boot_device(
                            node["uuid"], "cdrom", persistent=False
                        )
                    except Exception:
                        osism_utils.push_task_output(
                            request_id,
                            f"Could not set boot device to cdrom for {device.name}, continuing\n",
                        )
                    node = openstack.baremetal_node_set_provision_state(
                        node["uuid"], "provide"
                    )
                    node = openstack.baremetal_node_wait_for_nodes_provision_state(
                        node["uuid"], "available"
                    )
                    osism_utils.push_task_output(
                        request_id,
                        f"Baremetal node for {device.name} is available\n",
                    )

                if not node["automated_clean"]:
                    # NOTE: Activate automated cleaning, so that future actions will trigger it
                    node = openstack.baremetal_node_update(
                        node["uuid"], dict(automated_clean=True)
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
                node = openstack.baremetal_node_wait_for_nodes_provision_state(
                    node["uuid"], "manageable"
                )
                osism_utils.push_task_output(
                    request_id,
                    f"Baremetal node for {device.name} is manageable\n",
                )
                if node["automated_clean"]:
                    # NOTE: Skip automated cleaning, we do not want to accidentaly clean at this point
                    node = openstack.baremetal_node_update(
                        node["uuid"], dict(automated_clean=False)
                    )
    else:
        osism_utils.push_task_output(
            request_id,
            f"Validation of management interface failed for baremetal node for {device.name}\nReason: {node_validation['management'].reason}\n",
        )


def _sync_ironic_device_dry_run(
    request_id, device, node_attributes, ports_attributes, adopt, force, template_vars
):
    # Collect actual secret values for string-level masking
    secret_values = set()
    for key, value in template_vars.items():
        if isinstance(value, str) and (
            "password" in key.lower()
            or "secret" in key.lower()
            or key.lower().startswith("ironic_osism_")
        ):
            secret_values.add(value)

    masked_attributes = _prettify_for_display(
        mask_secrets(node_attributes, secret_values=secret_values)
    )
    masked_template_vars = mask_secrets(template_vars, secret_values=secret_values)

    def _indent_json(obj):
        return textwrap.indent(json.dumps(obj, indent=2), "    ")

    osism_utils.push_task_output(request_id, f"Processing device {device.name}\n")
    node = openstack.baremetal_node_show(device.name, ignore_missing=True)
    if not node:
        osism_utils.push_task_output(
            request_id,
            f"[DRY RUN] Would CREATE baremetal node for {device.name}\n"
            f"  Computed node attributes:\n"
            f"{_indent_json(masked_attributes)}\n"
            f"  Template variables used:\n"
            f"{_indent_json(masked_template_vars)}\n",
        )
        for port_attributes in ports_attributes:
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Would CREATE port with MAC {port_attributes['address']} for {device.name}\n",
            )
        osism_utils.push_task_output(
            request_id,
            f"[DRY RUN] Would try to transition node to `manageable` for {device.name}\n",
        )
        if adopt or device.custom_fields["provision_state"] == "active":
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Would try to adopt node for {device.name}\n",
            )
        else:
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Would try to transition node to `available` for {device.name}\n",
            )
    else:
        # NOTE: Check whether the baremetal node needs to be updated
        node_updates = {}
        deep_compare(node_attributes, node, node_updates)
        if "driver_info" in node_updates:
            password_key = driver_params[node_attributes["driver"]]["password"]
            if password_key in node_updates["driver_info"]:
                node_updates["driver_info"].pop(password_key, None)
                if not node_updates["driver_info"]:
                    node_updates.pop("driver_info", None)
        if node_updates or force:
            masked_updates = _prettify_for_display(
                mask_secrets(node_updates, secret_values=secret_values)
            )
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Would UPDATE baremetal node for {device.name}\n"
                f"  Changes:\n"
                f"{_indent_json(masked_updates)}\n"
                f"  Full computed node attributes:\n"
                f"{_indent_json(masked_attributes)}\n"
                f"  Template variables used:\n"
                f"{_indent_json(masked_template_vars)}\n",
            )
        else:
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Node {device.name} exists, no update needed\n",
            )

        # Check ports
        node_ports = openstack.baremetal_port_list(
            details=False, attributes=dict(node_uuid=node["uuid"])
        )
        for port_attributes in ports_attributes:
            port = [
                port
                for port in node_ports
                if port_attributes["address"].upper() == port["address"].upper()
            ]
            if not port:
                osism_utils.push_task_output(
                    request_id,
                    f"[DRY RUN] Would CREATE port with MAC {port_attributes['address']} for {device.name}\n",
                )
            else:
                node_ports.remove(port[0])
        for node_port in node_ports:
            osism_utils.push_task_output(
                request_id,
                f"[DRY RUN] Would DELETE port with MAC {node_port['address']} for {device.name}\n",
            )

        # Report current provision state instead of doing validation/transitions
        osism_utils.push_task_output(
            request_id,
            f"[DRY RUN] Current provision_state for {device.name}: {node['provision_state']}\n",
        )


def sync_ironic(
    request_id,
    get_ironic_parameters,
    node_name=None,
    adopt=False,
    force=False,
    dry_run=False,
    skip_kernel_params=None,
    extra_kernel_params=None,
):
    if skip_kernel_params is None:
        skip_kernel_params = []
    if extra_kernel_params is None:
        extra_kernel_params = []

    prefix = "[DRY RUN] " if dry_run else ""

    if node_name:
        osism_utils.push_task_output(
            request_id,
            f"{prefix}Starting NetBox device synchronisation with ironic for node {node_name}\n",
        )
    else:
        osism_utils.push_task_output(
            request_id,
            f"{prefix}Starting NetBox device synchronisation with ironic\n",
        )

    if skip_kernel_params:
        osism_utils.push_task_output(
            request_id,
            f"{prefix}Skipping kernel append parameters: {', '.join(skip_kernel_params)}\n",
        )

    if extra_kernel_params:
        osism_utils.push_task_output(
            request_id,
            f"{prefix}Adding extra kernel append parameters: {', '.join(extra_kernel_params)}\n",
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
                if dry_run:
                    osism_utils.push_task_output(
                        request_id,
                        f"[DRY RUN] Would delete stale baremetal node: {node['name']}\n",
                    )
                else:
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

        node_attributes, template_vars = _prepare_node_attributes(
            device,
            get_ironic_parameters,
            skip_kernel_params=skip_kernel_params,
            extra_kernel_params=extra_kernel_params,
        )
        ports_attributes = [
            dict(address=interface.mac_address)
            for interface in node_interfaces
            if interface.enabled and not interface.mgmt_only and interface.mac_address
        ]

        if dry_run:
            # In dry-run mode, skip locking entirely
            _sync_ironic_device_dry_run(
                request_id,
                device,
                node_attributes,
                ports_attributes,
                adopt,
                force,
                template_vars,
            )
        else:
            lock = osism_utils.create_redlock(
                key=f"lock_osism_tasks_conductor_sync_ironic-{device.name}",
                auto_release_time=600,
            )
            if lock.acquire(timeout=120):
                try:
                    _sync_ironic_device(
                        request_id,
                        device,
                        node_attributes,
                        ports_attributes,
                        adopt,
                        force,
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
