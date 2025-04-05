# SPDX-License-Identifier: Apache-2.0

from celery import Celery
import tempfile

from osism import utils
from osism.tasks import Config, run_command

app = Celery("openstack")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.openstack.image_get")
def image_get(self, image_name):
    conn = utils.get_openstack_connection()
    result = conn.image.find_image(image_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.network_get")
def network_get(self, network_name):
    conn = utils.get_openstack_connection()
    result = conn.network.find_network(network_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_create")
def baremetal_node_create(self, node_name, attributes=None):
    if attributes is None:
        attributes = {}
    attributes.update({"name": node_name})
    conn = utils.get_openstack_connection()
    result = conn.baremetal.create_node(**attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_delete")
def baremetal_node_delete(self, node_or_id):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.delete_node(node_or_id)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_update")
def baremetal_node_update(self, node_id_or_name, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.update_node(node_id_or_name, **attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_show")
def baremetal_node_show(self, node_id_or_name, ignore_missing=False):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.find_node(node_id_or_name, ignore_missing)
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


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_validate")
def baremetal_node_validate(self, node_id_or_name):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.validate_node(node_id_or_name, required=())
    return result


@app.task(
    bind=True,
    name="osism.tasks.openstack.baremetal_node_wait_for_nodes_provision_state",
)
def baremetal_node_wait_for_nodes_provision_state(self, node_id_or_name, state):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.wait_for_nodes_provision_state([node_id_or_name], state)
    if len(result) > 0:
        return result[0]
    else:
        return None


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_set_provision_state")
def baremetal_node_set_provision_state(self, node, state):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.set_node_provision_state(node, state)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_list")
def baremetal_port_list(self, details=False, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.ports(details=details, **attributes)
    return list(result)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_create")
def baremetal_port_create(self, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.create_port(**attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_delete")
def baremetal_port_delete(self, port_or_id):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.delete_port(port_or_id)
    return result


@app.task(bind=True, name="osism.tasks.openstack.compute_flavor_get")
def compute_flavor_get(self, name_or_id):
    conn = utils.get_openstack_connection()
    result = conn.compute.find_flavor(
        name_or_id, ignore_missing=True, get_extra_specs=True
    )
    return result


@app.task(bind=True, name="osism.tasks.openstack.compute_flavor_create")
def compute_flavor_create(self, name, attributes=None):
    if attributes is None:
        attributes = {}
    attributes.update({"name": name})
    extra_specs = attributes.pop("extra_specs", None)
    conn = utils.get_openstack_connection()
    flavor = conn.compute.create_flavor(**attributes)
    if extra_specs:
        flavor = conn.compute.create_flavor_extra_specs(flavor, extra_specs)
    return flavor


@app.task(bind=True, name="osism.tasks.openstack.compute_flavor_delete")
def compute_flavor_delete(self, flavor):
    conn = utils.get_openstack_connection()
    conn.compute.delete_flavor(flavor, ignore_missing=True)


@app.task(bind=True, name="osism.tasks.openstack.compute_flavor_update_extra_specs")
def compute_flavor_update_extra_specs(self, flavor, extra_specs={}):
    conn = utils.get_openstack_connection()
    for key, value in extra_specs.items():
        conn.compute.update_flavor_extra_specs_property(flavor, key, value)


@app.task(bind=True, name="osism.tasks.openstack.compute_flavor_delete_extra_specs")
def compute_flavor_delete_extra_specs_property(self, flavor, prop):
    conn = utils.get_openstack_connection()
    conn.compute.delete_flavor_extra_specs_property(flavor, prop)


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
