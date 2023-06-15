import os
import subprocess

from celery import Celery
from celery.signals import worker_process_init
import json
import pynetbox
from redis import Redis

from osism import settings
from osism.actions import (
    check_configuration,
    deploy_configuration,
    diff_configuration,
    generate_configuration,
    manage_device,
    manage_interface,
)
from osism.tasks import Config, ansible, openstack

app = Celery("netbox")
app.config_from_object(Config)

redis = None
nb = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global nb
    global redis

    redis = Redis(host="redis", port="6379")

    if settings.NETBOX_URL and settings.NETBOX_TOKEN:
        nb = pynetbox.api(settings.NETBOX_URL, token=settings.NETBOX_TOKEN)

        if settings.IGNORE_SSL_ERRORS:
            import requests

            requests.packages.urllib3.disable_warnings()
            session = requests.Session()
            session.verify = False
            nb.http_session = session


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):

    if Config.enable_bifrost in ["True", "true", "Yes", "yes"]:
        # Synchronize the status of Bifrost with Netbox every 5 minutes
        sender.add_periodic_task(300.0, periodic_synchronize_bifrost.s(), expires=10)


@app.task(bind=True, name="osism.tasks.netbox.periodic_synchronize_ironic")
def periodic_synchronize_ironic(self):
    """Synchronize the state of Ironic with Netbox"""
    openstack.baremetal_node_list.apply_async((), link=synchronize_device_state.s())


@app.task(bind=True, name="osism.tasks.netbox.periodic_synchronize_bifrost")
def periodic_synchronize_bifrost(self):
    """Synchronize the state of Bifrost with Netbox"""
    ansible.run.apply_async(
        ("manager", "bifrost-command", "baremetal node list -f json"),
        link=synchronize_device_state.s(),
    )


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


@app.task(bind=True, name="osism.tasks.netbox.update_network_interface_name")
def update_network_interface_name(self, mac_address, network_interface_name):
    manage_interface.update_network_interface_name(mac_address, network_interface_name)


@app.task(bind=True, name="osism.tasks.netbox.import_device_types")
def import_device_types(self, vendors, library=False):
    global redis

    if library:
        env = {**os.environ, "BASE_PATH": "/devicetype-library/device-types/"}
    else:
        env = {**os.environ, "BASE_PATH": "/netbox/device-types/"}

    if vendors:
        p = subprocess.Popen(
            f"python3 /import/main.py --vendors {vendors}",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
    else:
        p = subprocess.Popen(
            "python3 /import/main.py",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

    p.communicate()


@app.task(bind=True, name="osism.tasks.netbox.synchronize_device_state")
def synchronize_device_state(self, data):
    """Synchronize the state of Bifrost or Ironic with Netbox"""

    if type(data) == str:
        data = json.loads(data)

    if not data:
        return

    for device in data:
        manage_device.set_provision_state(device["Name"], device["Provisioning State"])
        manage_device.set_power_state(device["Name"], device["Power State"])


@app.task(bind=True, name="osism.tasks.netbox.states")
def states(self, data):
    result = manage_device.get_states(data.keys())
    return result


@app.task(bind=True, name="osism.tasks.netbox.transitions")
def transitions(self, data):
    result = manage_device.get_transitions(data.keys())
    return result


@app.task(bind=True, name="osism.tasks.netbox.data")
def data(self, collection, device, state):
    result = manage_device.load_data_from_filesystem(collection, device, state)
    return result


@app.task(bind=True, name="osism.tasks.netbox.connect")
def connect(self, device=None, state=None, data={}, enforce=False):
    manage_device.run(device, state, data, enforce)


@app.task(bind=True, name="osism.tasks.netbox.set_state")
def set_state(self, device=None, state=None, state_type=None):
    manage_device.set_state(device, state, state_type)


@app.task(bind=True, name="osism.tasks.netbox.set_maintenance")
def set_maintenance(self, device=None, state=None):
    manage_device.set_maintenance(device, state)


@app.task(bind=True, name="osism.tasks.netbox.disable")
def disable(self, name):
    global nb

    for interface in nb.dcim.interfaces.filter(device=name):
        if str(interface.type) in ["Virtual"]:
            continue

        if "Port-Channel" in interface.name:
            continue

        if not interface.connected_endpoint and interface.enabled:
            interface.enabled = False
            interface.save()

        # FIXME: only enable devices that are not disabled by configuration
        if interface.connected_endpoint and not interface.enabled:
            interface.enabled = True
            interface.save()


@app.task(bind=True, name="osism.tasks.netbox.generate")
def generate(self, name, template=None):
    generate_configuration.for_device(name, template)


@app.task(bind=True, name="osism.tasks.netbox.deploy")
def deploy(self, name):
    deploy_configuration.for_device(name)


@app.task(bind=True, name="osism.tasks.netbox.check")
def check(self, name):
    check_configuration.for_device(name)


@app.task(bind=True, name="osism.tasks.netbox.diff")
def diff(self, name):
    diff_configuration.for_device(name)


@app.task(bind=True, name="osism.tasks.netbox.get_devices_not_yet_registered_in_ironic")
def get_devices_not_yet_registered_in_ironic(
    self, status="active", tags=["managed-by-ironic"], ironic_enabled=True
):
    global nb

    devices = nb.dcim.devices.filter(
        tag=tags, status=status, cf_ironic_enabled=[ironic_enabled]
    )

    result = []

    for device in devices:
        if (
            "ironic_state" in device.custom_fields
            and device.custom_fields["ironic_state"] != "registered"
        ):
            result.append(device.name)

    return result


@app.task(
    bind=True,
    name="osism.tasks.netbox.get_devices_that_should_have_an_allocation_in_ironic",
)
def get_devices_that_should_have_an_allocation_in_ironic(self):
    global nb

    devices = nb.dcim.devices.filter(
        tag=["managed-by-ironic", "managed-by-osism"],
        status="active",
        cf_ironic_enabled=[True],
        cf_ironic_state=["registered"],
        cf_provision_state=["available"],
        cf_introspection_state=["introspected"],
        cf_device_type=["server"],
    )

    result = []

    for device in devices:
        result.append(device.name)

    return result


@app.task(bind=True, name="osism.tasks.netbox.ping")
def ping(self):
    global nb

    status = nb.status()

    return status
