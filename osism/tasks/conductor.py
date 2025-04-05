# SPDX-License-Identifier: Apache-2.0

from celery import Celery
from celery.signals import worker_process_init
import copy
import ipaddress
import jinja2
from loguru import logger
from pottery import Redlock
import yaml

from osism import utils
from osism.tasks import Config, netbox, openstack

app = Celery("conductor")
app.config_from_object(Config)


configuration = {}


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global configuration

    with open("/etc/conductor.yml") as fp:
        configuration = yaml.load(fp, Loader=yaml.SafeLoader)

        if not configuration:
            logger.warning(
                "The conductor configuration is empty. That's probably wrong"
            )
            configuration = {}
            return

        # Resolve all IDs in the conductor.yml
        if Config.enable_ironic.lower() in ["true", "yes"]:
            if "ironic_parameters" not in configuration:
                logger.error(
                    "ironic_parameters not found in the conductor configuration"
                )
                return

            if "driver_info" in configuration["ironic_parameters"]:
                if "deploy_kernel" in configuration["ironic_parameters"]["driver_info"]:
                    result = openstack.image_get(
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_kernel"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "deploy_kernel"
                    ] = result.id

                if (
                    "deploy_ramdisk"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = openstack.image_get(
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_ramdisk"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "deploy_ramdisk"
                    ] = result.id

                if (
                    "cleaning_network"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = openstack.network_get(
                        configuration["ironic_parameters"]["driver_info"][
                            "cleaning_network"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "cleaning_network"
                    ] = result.id

                if (
                    "provisioning_network"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = openstack.network_get(
                        configuration["ironic_parameters"]["driver_info"][
                            "provisioning_network"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "provisioning_network"
                    ] = result.id


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.conductor.get_ironic_parameters")
def get_ironic_parameters(self):
    if "ironic_parameters" in configuration:
        # NOTE: Do not pass by reference, everybody gets their own copy to work with
        return copy.deepcopy(configuration["ironic_parameters"])

    return {}


@app.task(bind=True, name="osism.tasks.conductor.sync_netbox_with_ironic")
def sync_netbox_with_ironic(self, force_update=False):
    def deep_compare(a, b, updates):
        """
        Find items in a that do not exist in b or are different.
        Write required changes into updates
        """
        for key, value in a.items():
            if type(value) is not dict:
                if key not in b or b[key] != value:
                    updates[key] = value
            else:
                updates[key] = {}
                deep_compare(a[key], b[key], updates[key])
                if not updates[key]:
                    updates.pop(key)

    driver_params = {
        "ipmi": {
            "address": "ipmi_address",
            "port": "ipmi_port",
            "password": "ipmi_password",
        },
        "redfish": {
            "address": "redfish_address",
            "port": "redfish_port",
            "password": "redfish_password",
        },
    }

    devices = list(netbox.get_devices_by_tags(["managed-by-ironic"]))

    # NOTE: Find nodes in Ironic which are no longer present in netbox and remove them
    device_names = [dev.name for dev in devices]
    nodes = openstack.baremetal_node_list()
    for node in nodes:
        logger.info(f"Looking for {node['Name']} in netbox")
        if node["Name"] not in device_names:
            if (
                not node["Instance UUID"]
                and node["Provisioning State"] in ["enroll", "manageable", "available"]
                and node["Power State"] == "power off"
            ):
                logger.info(
                    f"Cleaning up baremetal node not found in netbox: {node['Name']}"
                )
                flavor_name = "osism-" + node["Name"]
                flavor = openstack.compute_flavor_get(flavor_name)
                if flavor:
                    logger.info(f"Deleting flavor {flavor_name}")
                    openstack.compute_flavor_delete(flavor)
                for port in openstack.baremetal_port_list(
                    details=False, attributes=dict(node_uuid=node["UUID"])
                ):
                    openstack.baremetal_port_delete(port.id)
                openstack.baremetal_node_delete(node["UUID"])
            else:
                logger.error(
                    f"Cannot remove baremetal node because it is still provisioned or running: {node}"
                )

    # NOTE: Find nodes in netbox which are not present in Ironic and add them
    for device in devices:
        logger.info(f"Looking for {device.name} in ironic")

        node_interfaces = list(netbox.get_interfaces_by_device(device.name))

        node_attributes = get_ironic_parameters()
        if (
            "driver" in node_attributes
            and node_attributes["driver"] in driver_params.keys()
        ):
            if "driver_info" in node_attributes:
                address_key = driver_params[node_attributes["driver"]]["address"]
                if address_key in node_attributes["driver_info"]:
                    if "oob_address" in device.custom_fields:
                        node_mgmt_address = device.custom_fields["oob_address"]
                    elif "address" in device.oob_ip:
                        node_mgmt_address = device.oob_ip["address"]
                    else:
                        node_mgmt_addresses = [
                            interface["address"]
                            for interface in node_interfaces
                            if interface.mgmt_only
                            and "address" in interface
                            and interface["address"]
                        ]
                        if len(node_mgmt_addresses) > 0:
                            node_mgmt_address = node_mgmt_addresses[0]
                        else:
                            node_mgmt_address = None
                    if node_mgmt_address:
                        node_attributes["driver_info"][address_key] = (
                            jinja2.Environment(loader=jinja2.BaseLoader())
                            .from_string(node_attributes["driver_info"][address_key])
                            .render(
                                remote_board_address=str(
                                    ipaddress.ip_interface(node_mgmt_address).ip
                                )
                            )
                        )
                    else:
                        logger.error(f"Could not find out-of-band address for {device}")
                        node_attributes["driver_info"].pop(address_key, None)
                if "oob_port" in device.custom_fields:
                    port_key = driver_params[node_attributes["driver"]]["port"]
                    node_attributes["driver_info"].update(
                        {port_key: device.custom_fields["oob_port"]}
                    )
        node_attributes.update({"resource_class": device.name})
        ports_attributes = [
            dict(address=interface.mac_address)
            for interface in node_interfaces
            if interface.enabled and not interface.mgmt_only and interface.mac_address
        ]
        flavor_attributes = {
            "ram": 1,
            "disk": 0,
            "vcpus": 1,
            "is_public": False,
            "extra_specs": {
                "resources:CUSTOM_"
                + device.name.upper().replace("-", "_").replace(".", "_"): "1",
                "resources:VCPU": "0",
                "resources:MEMORY_MB": "0",
                "resources:DISK_GB": "0",
            },
        }

        lock = Redlock(
            key=f"lock_osism_tasks_conductor_sync_netbox_with_ironic-{device.name}",
            masters={utils.redis},
            auto_release_time=60,
        )
        if lock.acquire(timeout=20):
            try:
                logger.info(f"Processing device {device.name}")
                node = openstack.baremetal_node_show(device.name, ignore_missing=True)
                if not node:
                    logger.info(f"Creating baremetal node for {device.name}")
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
                        logger.info(
                            f"Updating baremetal node for {device.name} with {node_updates}"
                        )
                        # NOTE: Do the actual updates with all values in node_attributes. Otherwise nested dicts like e.g. driver_info will be overwritten as a whole and contain only changed values
                        node = openstack.baremetal_node_update(
                            node["uuid"], node_attributes
                        )

                node_ports = openstack.baremetal_port_list(
                    details=False, attributes=dict(node_uuid=node["uuid"])
                )
                # NOTE: Baremetal ports are only required for (i)pxe boot
                if node["boot_interface"] in ["pxe", "ipxe"]:
                    for port_attributes in ports_attributes:
                        port_attributes.update({"node_id": node["uuid"]})
                        port = [
                            port
                            for port in node_ports
                            if port_attributes["address"].upper()
                            == port["address"].upper()
                        ]
                        if not port:
                            logger.info(
                                f"Creating baremetal port with MAC address {port_attributes['address']} for {device.name}"
                            )
                            openstack.baremetal_port_create(port_attributes)
                        else:
                            node_ports.remove(port[0])
                for node_port in node_ports:
                    # NOTE: Delete remaining ports not found in netbox
                    logger.info(
                        f"Deleting baremetal port with MAC address {node_port['address']} for {device.name}"
                    )
                    openstack.baremetal_port_delete(node_port["id"])

                node_validation = openstack.baremetal_node_validate(node["uuid"])
                if node_validation["management"].result:
                    logger.info(
                        f"Validation of management interface successful for baremetal node for {device.name}"
                    )
                    if node["provision_state"] == "enroll":
                        logger.info(
                            f"Transitioning baremetal node to manageable state for {device.name}"
                        )
                        node = openstack.baremetal_node_set_provision_state(
                            node["uuid"], "manage"
                        )
                        node = openstack.baremetal_node_wait_for_nodes_provision_state(
                            node["uuid"], "manageable"
                        )
                        logger.info(f"Baremetal node for {device.name} is manageable")
                    if node_validation["boot"].result:
                        logger.info(
                            f"Validation of boot interface successful for baremetal node for {device.name}"
                        )
                        if node["provision_state"] == "manageable":
                            logger.info(
                                f"Transitioning baremetal node to available state for {device.name}"
                            )
                            node = openstack.baremetal_node_set_provision_state(
                                node["uuid"], "provide"
                            )
                            node = (
                                openstack.baremetal_node_wait_for_nodes_provision_state(
                                    node["uuid"], "available"
                                )
                            )
                            logger.info(
                                f"Baremetal node for {device.name} is available"
                            )
                    else:
                        logger.info(
                            f"Validation of boot interface failed for baremetal node for {device.name}\nReason: {node_validation['boot'].reason}"
                        )
                        if node["provision_state"] == "available":
                            # NOTE: Demote node to manageable
                            logger.info(
                                f"Transitioning baremetal node to manageable state for {device.name}"
                            )
                            node = openstack.baremetal_node_set_provision_state(
                                node["uuid"], "manage"
                            )
                            node = (
                                openstack.baremetal_node_wait_for_nodes_provision_state(
                                    node["uuid"], "manageable"
                                )
                            )
                            logger.info(
                                f"Baremetal node for {device.name} is manageable"
                            )
                else:
                    logger.info(
                        f"Validation of management interface failed for baremetal node for {device.name}\nReason: {node_validation['management'].reason}"
                    )

                flavor_name = "osism-" + device.name
                flavor = openstack.compute_flavor_get(flavor_name)
                if not flavor:
                    logger.info(f"Creating flavor for {flavor_name}")
                    flavor = openstack.compute_flavor_create(
                        flavor_name, flavor_attributes
                    )
                else:
                    flavor_updates = {}
                    deep_compare(flavor_attributes, flavor, flavor_updates)
                    flavor_updates_extra_specs = flavor_updates.pop("extra_specs", None)
                    if flavor_updates:
                        logger.info(
                            f"Updating flavor for {device.name} with {flavor_updates}"
                        )
                        openstack.compute_flavor_delete(flavor)
                        flavor = openstack.compute_flavor_create(
                            flavor_name, flavor_attributes
                        )
                    elif flavor_updates_extra_specs:
                        logger.info(
                            f"Updating flavor extra_specs for {device.name} with {flavor_updates_extra_specs}"
                        )
                        openstack.compute_flavor_update_extra_specs(
                            flavor, flavor_updates_extra_specs
                        )
                        flavor = openstack.compute_flavor_get(flavor_name)
                    for extra_specs_key in flavor["extra_specs"].keys():
                        if (
                            extra_specs_key
                            not in flavor_attributes["extra_specs"].keys()
                        ):
                            logger.info(
                                f"Deleting flavor extra_specs property {extra_specs_key} for {device.name}"
                            )
                            flavor = (
                                openstack.compute_flavor_delete_extra_specs_property(
                                    flavor, extra_specs_key
                                )
                            )

            except Exception as exc:
                logger.info(
                    f"Could not fully synchronize device {device.name} with ironic: {exc}"
                )
            finally:
                lock.release()

        else:
            logger.error("Could not acquire lock for node {device.name}")
