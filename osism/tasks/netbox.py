import os
import subprocess

from celery import Celery
from celery.signals import worker_process_init
from pottery import Redlock
import pynetbox
from redis import Redis

from osism import settings
from osism.actions import generate_configuration, manage_device
from osism.tasks import Config, ansible

app = Celery('kolla')
app.config_from_object(Config)

redis = None
nb = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global nb
    global redis

    redis = Redis(host="redis", port="6379")
    nb = pynetbox.api(
        settings.NETBOX_URL,
        token=settings.NETBOX_TOKEN
    )

    if settings.IGNORE_SSL_ERRORS:
        import requests
        requests.packages.urllib3.disable_warnings()
        session = requests.Session()
        session.verify = False
        nb.http_session = session


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


@app.task(bind=True, name="osism.tasks.netbox.import_device_types")
def import_device_types(self, vendors, library=False):
    global redis

    if library:
        env = {**os.environ, "BASE_PATH": "/devicetype-library/device-types/"}
    else:
        env = {**os.environ, "BASE_PATH": "/netbox/device-types/"}

    if vendors:
        p = subprocess.Popen(f"python3 /import/main.py --vendors {vendors}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    else:
        p = subprocess.Popen("python3 /import/main.py", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    p.communicate()


def connect_device(self, device, state, data, current_states, enforce=False):
    global redis

    # Device is already in the target state, no transition necessary
    if not enforce and current_states[device] == state:
        return

    # Allow only one status change per device
    lock = Redlock(key="lock_{device}", masters={redis})
    lock.acquire()

    # transition: from-to, phase 1
    transition = f"from_{current_states[device]}-to_{state}-phase_1"
    manage_device.set_device_transition(device, transition)

    manage_device.manage_interfaces(device, data)
    manage_device.manage_port_channels(device, data)
    manage_device.remove_port_channels(device, data)
    manage_device.manage_virtual_interfaces(device, data)
    manage_device.remove_virtual_interfaces(device, data)
    manage_device.manage_mlag_devices(device, data)

    manage_device.set_device_state(device, f"{state}-phase_1")

    lock.release()


@app.task(bind=True, name="osism.tasks.netbox.connect")
def connect(self, collection, device=None, state=None, enforce=False, wait=False):
    data = manage_device.load_data_from_filesystem(collection, device, state)
    current_states = manage_device.get_current_states(data)

    tasks = []
    for device in data:
        task = connect_device.delay(device, state, data, current_states, enforce)
        tasks.append(task)

    if wait:
        for task in task:
            task.wait(timeout=None, interval=0.5)


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

        if interface.connected_endpoint and not interface.enabled:
            interface.enabled = True
            interface.save()


@app.task(bind=True, name="osism.tasks.netbox.generate")
def generate(self, name, template=None):
    generate_configuration.for_device(name, template)


@app.task(bind=True, name="osism.tasks.netbox.deploy")
def deploy(self, name):
    return


@app.task(bind=True, name="osism.tasks.netbox.init")
def init(self, arguments):
    ansible.run.delay("netbox-local", "init", arguments)
