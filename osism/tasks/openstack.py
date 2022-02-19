import copy
import ipaddress

from celery import Celery
from celery.signals import worker_process_init
import jinja2
import keystoneauth1
import openstack
from redis import Redis

from osism.tasks import Config
from osism import utils

app = Celery('openstack')
app.config_from_object(Config)

redis = None
conn = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global conn
    global redis

    redis = Redis(host="redis", port="6379")

    # Parameters come from the environment, OS_*
    try:
        conn = openstack.connect()
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.openstack.image_get")
def image_get(self, image_name):
    result = conn.image.find_image(image_name)
    return result.id


@app.task(bind=True, name="osism.tasks.openstack.network_get")
def network_get(self, network_name):
    result = conn.network.find_network(network_name)
    return result.id


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_show")
def baremetal_node_show(self, node_id_or_name):
    result = conn.baremetal.find_node(node_id_or_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_list")
def baremetal_node_list(self):
    nodes = conn.baremetal.nodes()
    result = []

    # Simulate the output of the OpenStack CLI with -f json and without --long
    for node in nodes:
        result.append({
            "UUID": node.id,
            "Name": node.name,
            "Instance UUID": node.instance_id,
            "Power State": node.power_state,
            "Provisioning State": node.provision_state,
            "Maintenance": node.is_maintenance
        })

    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_introspection_interface_list")
def baremetal_introspection_interface_list(self, node_id_or_name):
    pass


@app.task(bind=True, name="osism.tasks.openstack.baremetal_introspection_status")
def baremetal_introspection_status(self, node_id_or_name):
    result = None
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_get_network_interface_name")
def baremetal_get_network_interface_name(self, node_name, mac_address):
    global conn

    introspection = conn.baremetal_introspection.get_introspection(node_name)

    # Wait up to 5 minutes for the completion of a running introspection
    conn.baremetal_introspection.wait_for_introspection(introspection, timeout=30)

    introspection_data = conn.baremetal_introspection.get_introspection_data(introspection)
    interfaces = introspection_data["inventory"]["interfaces"]

    result = None
    for interface in interfaces:
        if interface["mac_address"].lower() == mac_address.lower():
            result = interface["name"]

    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_set_node_provision_state")
def baremetal_set_node_provision_state(self, node, state):
    global conn
    conn.baremetal.set_node_provision_state(node, state)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_create_nodes")
def baremetal_create_nodes(self, nodes, ironic_parameters):
    global conn

    for node in nodes:
        # TODO: Filter on mgmt_only
        address_a = utils.nb.ipam.ip_addresses.get(device=node, interface="Ethernet0")

        node_parameters = copy.deepcopy(ironic_parameters)

        if node_parameters["driver"] == "redfish":
            remote_board_address = str(ipaddress.ip_interface(address_a["address"]).ip)
            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(node_parameters["driver_info"]["redfish_address"])
            node_parameters["driver_info"]["redfish_address"] = t.render(remote_board_address=remote_board_address)

        elif node_parameters["driver"] == "ipmi":
            remote_board_address = str(ipaddress.ip_interface(address_a["address"]).ip)
            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(node_parameters["driver_info"]["ipmi_address"])
            node_parameters["driver_info"]["ipmi_address"] = t.render(remote_board_address=remote_board_address)

        try:
            conn.baremetal.create_node(name=node, provision_state="manageable", **node_parameters)
            conn.baremetal.wait_for_nodes_provision_state([node], 'manageable')
            conn.baremetal.set_node_provision_state(node, 'inspect')

            # TODO: Check if the system has been registered correctly
            device_a = utils.nb.dcim.devices.get(name=node)
            device_a.custom_fields = {
                "ironic_state": "registered",
            }
            device_a.save()

        except openstack.exceptions.ResourceFailure:
            # TODO: Do something useful here
            pass
        except openstack.exceptions.ConflictException:
            # The node already exists and has a wronge state in the Netbox
            device_a = utils.nb.dcim.devices.get(name=node)
            device_a.custom_fields = {
                "ironic_state": "registered",
            }
            device_a.save()
