# SPDX-License-Identifier: Apache-2.0

from celery import Celery
from celery.signals import worker_process_init
import json
import pynetbox

from osism import settings, utils
from osism.actions import manage_device, manage_interface
from osism.tasks import Config, openstack, run_command

app = Celery("netbox")
app.config_from_object(Config)


@worker_process_init.connect
def celery_init_worker(**kwargs):
    if settings.NETBOX_URL and settings.NETBOX_TOKEN:
        utils.nb = pynetbox.api(settings.NETBOX_URL, token=settings.NETBOX_TOKEN)

        if settings.IGNORE_SSL_ERRORS:
            import requests

            requests.packages.urllib3.disable_warnings()
            session = requests.Session()
            session.verify = False
            utils.nb.http_session = session


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.netbox.periodic_synchronize_ironic")
def periodic_synchronize_ironic(self):
    """Synchronize the state of Ironic with Netbox"""
    openstack.baremetal_node_list.apply_async((), link=synchronize_device_state.s())


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


@app.task(bind=True, name="osism.tasks.netbox.update_network_interface_name")
def update_network_interface_name(self, mac_address, network_interface_name):
    manage_interface.update_network_interface_name(mac_address, network_interface_name)


@app.task(bind=True, name="osism.tasks.netbox.synchronize_device_state")
def synchronize_device_state(self, data):
    """Synchronize the state of Ironic with Netbox"""

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


@app.task(bind=True, name="osism.tasks.netbox.set_state")
def set_state(self, device=None, state=None, state_type=None):
    manage_device.set_state(device, state, state_type)


@app.task(bind=True, name="osism.tasks.netbox.set_maintenance")
def set_maintenance(self, device=None, state=None):
    manage_device.set_maintenance(device, state)


@app.task(bind=True, name="osism.tasks.netbox.diff")
@app.task(bind=True, name="osism.tasks.netbox.get_devices_not_yet_registered_in_ironic")
def get_devices_not_yet_registered_in_ironic(
    self, status="active", tags=["managed-by-ironic"], ironic_enabled=True
):
    devices = utils.nb.dcim.devices.filter(
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
    devices = utils.nb.dcim.devices.filter(
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


@app.task(bind=True, name="osism.tasks.netbox.manage")
def manage(self, *arguments, publish=True, locking=False, auto_release_time=3600):
    netbox_manager_env = {
        "NETBOX_MANAGER_URL": str(settings.NETBOX_URL),
        "NETBOX_MANAGER_TOKEN": str(settings.NETBOX_TOKEN),
        "NETBOX_MANAGER_IGNORE_SSL_ERRORS": str(settings.IGNORE_SSL_ERRORS),
        "NETBOX_MANAGER_VERBOSE": "true",
    }

    return run_command(
        self.request.id,
        "/usr/local/bin/netbox-manager",
        netbox_manager_env,
        *arguments,
        publish=publish,
        locking=locking,
        auto_release_time=auto_release_time
    )


@app.task(bind=True, name="osism.tasks.netbox.ping")
def ping(self):
    status = utils.nb.status()

    return status
