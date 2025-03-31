# SPDX-License-Identifier: Apache-2.0

import copy
import ipaddress

from celery import Celery
import jinja2
from openstack.exceptions import ConflictException, ResourceNotFound, ResourceFailure
from pottery import Redlock
import tempfile

from osism import utils
from osism.tasks import Config, conductor, netbox, run_command

app = Celery("openstack")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.openstack.image_get")
def image_get(self, image_name):
    conn = utils.get_openstack_connection()
    result = conn.image.find_image(image_name)
    return result.id


@app.task(bind=True, name="osism.tasks.openstack.network_get")
def network_get(self, network_name):
    conn = utils.get_openstack_connection()
    result = conn.network.find_network(network_name)
    return result.id


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_show")
def baremetal_node_show(self, node_id_or_name):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.find_node(node_id_or_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_list")
def baremetal_node_list(self):
    conn = utils.get_openstack_connection()
    nodes = conn.baremetal.nodes()
    result = []

    # Simulate the output of the OpenStack CLI with -f json and without --long
    for node in nodes:
        result.append(
            {
                "UUID": node.id,
                "Name": node.name,
                "Instance UUID": node.instance_id,
                "Power State": node.power_state,
                "Provisioning State": node.provision_state,
                "Maintenance": node.is_maintenance,
            }
        )

    return result


@app.task(
    bind=True, name="osism.tasks.openstack.baremetal_introspection_interface_list"
)
def baremetal_introspection_interface_list(self, node_id_or_name):
    pass


@app.task(bind=True, name="osism.tasks.openstack.baremetal_introspection_status")
def baremetal_introspection_status(self, node_id_or_name):
    result = None
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_get_network_interface_name")
def baremetal_get_network_interface_name(self, node_name, mac_address):
    conn = utils.get_openstack_connection()

    introspection = conn.baremetal_introspection.get_introspection(node_name)

    # Wait up to 5 minutes for the completion of a running introspection
    conn.baremetal_introspection.wait_for_introspection(introspection, timeout=30)

    introspection_data = conn.baremetal_introspection.get_introspection_data(
        introspection
    )
    interfaces = introspection_data["inventory"]["interfaces"]

    result = None
    for interface in interfaces:
        if interface["mac_address"].lower() == mac_address.lower():
            result = interface["name"]

    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_set_node_provision_state")
def baremetal_set_node_provision_state(self, node, state):
    conn = utils.get_openstack_connection()
    conn.baremetal.set_node_provision_state(node, state)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_create_allocations")
def baremetal_create_allocations(self, nodes):
    conn = utils.get_openstack_connection()

    for node in nodes:
        try:
            allocation_a = conn.baremetal.get_allocation(allocation=node)
        except ResourceNotFound:
            allocation_a = None

        if not allocation_a:
            # Get Ironic parameters from the conductor
            task = conductor.get_ironic_parameters.delay()
            task.wait(timeout=None, interval=0.5)
            ironic_parameters = task.get()

            allocation_a = conn.baremetal.create_allocation(
                name=node,
                candidate_nodes=[node],
                resource_class=ironic_parameters["resource_class"],
            )
            conn.baremetal.wait_for_allocation(allocation=node, timeout=30)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_create_nodes")
def baremetal_create_nodes(self, nodes, ironic_parameters):
    conn = utils.get_openstack_connection()

    for node in nodes:
        # TODO: Filter on mgmt_only
        address_a = utils.nb.ipam.ip_addresses.get(device=node, interface="Ethernet0")

        node_parameters = copy.deepcopy(ironic_parameters)

        if node_parameters["driver"] == "redfish":
            remote_board_address = str(ipaddress.ip_interface(address_a["address"]).ip)
            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(
                node_parameters["driver_info"]["redfish_address"]
            )
            node_parameters["driver_info"]["redfish_address"] = t.render(
                remote_board_address=remote_board_address
            )

        elif node_parameters["driver"] == "ipmi":
            remote_board_address = str(ipaddress.ip_interface(address_a["address"]).ip)
            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(
                node_parameters["driver_info"]["ipmi_address"]
            )
            node_parameters["driver_info"]["ipmi_address"] = t.render(
                remote_board_address=remote_board_address
            )

        try:
            device_a = utils.nb.dcim.devices.get(name=node)
            tags = [str(tag) for tag in device_a.tags]

            # NOTE: Internally used nodes are identified by their unique name via the resource class.
            #       The actual resource class is explicitly overwritten.
            if "Managed by Ironic" in tags and "Managed by OSISM" in tags:
                node_parameters["resource_class"] = f"osism-{node}"
                baremetal_create_internal_flavor(node)

            conn.baremetal.create_node(
                name=node, provision_state="manageable", **node_parameters
            )
            conn.baremetal.wait_for_nodes_provision_state([node], "manageable")

            if "Managed by Ironic" in tags and "Managed by OSISM" not in tags:
                conn.baremetal.set_node_traits(node, ["CUSTOM_GENERAL_USE"])
            elif "Managed by Ironic" in tags and "Managed by OSISM" in tags:
                conn.baremetal.set_node_traits(node, ["CUSTOM_OSISM_USE"])

            conn.baremetal.set_node_provision_state(node, "inspect")

            # TODO: Check if the system has been registered correctly
            device_a.custom_fields = {
                "ironic_state": "registered",
            }
            device_a.save()

        except ResourceFailure:
            # TODO: Do something useful here
            pass
        except ConflictException:
            # The node already exists and has a wronge state in the Netbox
            device_a = utils.nb.dcim.devices.get(name=node)
            device_a.custom_fields = {
                "ironic_state": "registered",
            }
            device_a.save()


@app.task(bind=True, name="osism.tasks.openstack.baremetal_check_allocations")
def baremetal_check_allocations(self):
    lock = Redlock(
        key="lock_osism_tasks_openstack_baremetal_check_allocations",
        masters={utils.redis},
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        netbox.get_devices_that_should_have_an_allocation_in_ironic.apply_async(
            (), link=baremetal_create_allocations.s()
        )
        lock.release()


@app.task(bind=True, name="osism.tasks.openstack.baremetal_create_internal_flavor")
def baremetal_create_internal_flavor(self, node):
    conn = utils.get_openstack_connection()

    flavor_a = conn.compute.create_flavor(
        name=f"osism-{node}", ram=1, vcpus=1, disk=1, is_public=False
    )
    specs = {
        f"resources:CUSTOM_RESOURCE_CLASS_OSISM_{node.upper()}": 1,
        "resources:VCPU": 0,
        "resources:MEMORY_MB": 0,
        "resources:DISK_GB": 0,
        "trait:CUSTOM_OSISM_USE": "required",
    }
    conn.compute.create_flavor_extra_specs(flavor_a, specs)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_delete_internal_flavor")
def baremetal_delete_internal_flavor(self, node):
    conn = utils.get_openstack_connection()

    flavor = conn.compute.get_flavor(f"osism-{node}")
    conn.compute.delete_flavor(flavor)


@app.task(bind=True, name="osism.tasks.openstack.image_manager")
def image_manager(
    self, *arguments, configs=None, publish=True, locking=False, auto_release_time=3600
):
    command = "/usr/local/bin/openstack-image-manager"
    if configs:
        with tempfile.TemporaryDirectory() as temp_dir:
            for config in configs:
                with tempfile.NamedTemporaryFile(
                    mode="w+", suffix=".yml", dir=temp_dir, delete=False
                ) as temp_file:
                    temp_file.write(config)

            sanitized_args = [
                arg for arg in arguments if not arg.startswith("--images=")
            ]

            try:
                images_index = sanitized_args.index("--images")
                sanitized_args.pop(images_index)
                sanitized_args.pop(images_index)
            except ValueError:
                pass
            sanitized_args.extend(["--images", temp_dir])
            rc = run_command(
                self.request.id,
                command,
                {},
                *sanitized_args,
                publish=publish,
                locking=locking,
                auto_release_time=auto_release_time,
            )
        return rc
    else:
        return run_command(
            self.request.id,
            command,
            {},
            *arguments,
            publish=publish,
            locking=locking,
            auto_release_time=auto_release_time,
        )


@app.task(bind=True, name="osism.tasks.openstack.flavor_manager")
def flavor_manager(
    self, *arguments, publish=True, locking=False, auto_release_time=3600
):
    command = "/usr/local/bin/openstack-flavor-manager"
    return run_command(
        self.request.id,
        command,
        {},
        *arguments,
        publish=publish,
        locking=locking,
        auto_release_time=auto_release_time,
    )
