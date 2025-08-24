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
    result = conn.baremetal.nodes()
    return list(result)


def get_baremetal_nodes():
    """Get all baremetal nodes with their details.

    This is a generalized function that can be used by both
    CLI commands and API endpoints to retrieve baremetal node information.

    Returns:
        list: List of dictionaries containing node information
    """
    conn = utils.get_openstack_connection()
    nodes = conn.baremetal.nodes(details=True)

    # Convert generator to list and extract relevant fields
    node_list = []
    for node in nodes:
        # OpenStack SDK returns Resource objects, not dicts - use attribute access
        node_info = {
            "uuid": getattr(node, "uuid", None) or getattr(node, "id", None),
            "name": getattr(node, "name", None),
            "power_state": getattr(node, "power_state", None),
            "provision_state": getattr(node, "provision_state", None),
            "maintenance": getattr(node, "maintenance", None),
            "instance_uuid": getattr(node, "instance_uuid", None),
            "driver": getattr(node, "driver", None),
            "resource_class": getattr(node, "resource_class", None),
            "properties": getattr(node, "properties", {}),
            "extra": getattr(node, "extra", {}),
            "last_error": getattr(node, "last_error", None),
            "created_at": getattr(node, "created_at", None),
            "updated_at": getattr(node, "updated_at", None),
        }
        node_list.append(node_info)

    return node_list


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


@app.task(bind=True, name="osism.tasks.openstack.image_manager")
def image_manager(
    self,
    *arguments,
    configs=None,
    publish=True,
    locking=False,
    auto_release_time=3600,
    ignore_env=False
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
                ignore_env=ignore_env,
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
            ignore_env=ignore_env,
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
