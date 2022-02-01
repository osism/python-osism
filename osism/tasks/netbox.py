import io
import os
import subprocess

from celery import Celery
from celery.signals import worker_process_init
from pottery import synchronize
import pynetbox
from redis import Redis

from osism import settings
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

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        redis.publish("netbox-import-device-types", line)

    # NOTE: use task_id or request_id in future
    redis.publish("netbox-import-device-types", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.connect")
def connect(self, collection, device=None, state=None):
    global redis

    if collection and device:
        name = f"{collection}-{device}"
    elif collection:
        name = collection
    else:
        name = device

    if device:
        if state:
            if collection:
                p = subprocess.Popen(f"python3 /connect/main.py --collection {collection} --device={device} --state {state}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            else:
                p = subprocess.Popen(f"python3 /connect/main.py --device={device} --state {state}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            if collection:
                p = subprocess.Popen(f"python3 /connect/main.py --collection {collection} --device={device}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            else:
                p = subprocess.Popen(f"python3 /connect/main.py --device={device}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            # NOTE: use task_id or request_id in future
            redis.publish(f"netbox-connect-{name}", line)

        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-connect-{name}", "QUIT")
    else:
        if state:
            p = subprocess.Popen(f"python3 /connect/main.py --collection {collection} --state {state}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            p = subprocess.Popen(f"python3 /connect/main.py --collection {collection}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            # NOTE: use task_id or request_id in future
            redis.publish(f"netbox-connect-{name}", line)

        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-connect-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.disable")
def disable(self, name):
    global nb
    global redis

    for interface in nb.dcim.interfaces.filter(device=name):
        if str(interface.type) in ["Virtual"]:
            continue

        if "Port-Channel" in interface.name:
            continue

        if not interface.connected_endpoint and interface.enabled:
            redis.publish(f"netbox-disable-{name}", f"{interface} --> disabled")
            interface.enabled = False
            interface.save()

        if interface.connected_endpoint and not interface.enabled:
            redis.publish(f"netbox-disable-{name}", f"{interface} --> enabled")
            interface.enabled = True
            interface.save()

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-disable-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.generate")
@synchronize(key='netbox-generate', masters={redis}, auto_release_time=60*1000, blocking=True, timeout=-1)
def generate(self, name, template=None):
    global redis

    if template:
        p = subprocess.Popen(f"python3 /generate/main.py --template {template} --device {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    else:
        p = subprocess.Popen(f"python3 /generate/main.py --device {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-generate-{name}", line)

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-generate-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.deploy")
def deploy(self, name):
    global redis

    redis.publish(f"netbox-deploy-{name}", "Not yet implemented")

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-deploy-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.init")
@synchronize(key='netbox-init', masters={redis}, auto_release_time=600*1000, blocking=True, timeout=-1)
def init(self, arguments):
    ansible.run.delay("netbox-local", "init", arguments)
