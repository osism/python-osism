from celery import Celery
from celery.signals import worker_process_init
import openstack
from redis import Redis

from osism.tasks import Config

app = Celery('netbox')
app.config_from_object(Config)

redis = None
conn = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global conn
    global redis

    redis = Redis(host="redis", port="6379")

    # Parameters come from the environment, OS_*
    conn = openstack.connect()


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_create")
def baremetal_node_create(self):
    pass


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_show")
def baremetal_node_show(self, node_id_or_name):
    result = conn.baremetal.find_node(node_id_or_name)
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
