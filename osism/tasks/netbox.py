import io
import os
import subprocess

from celery import Celery
from pottery import synchronize
from redis import Redis

from osism.tasks import Config, ansible

app = Celery('kolla')
app.config_from_object(Config)

redis = Redis(host="redis", port="6379")


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


@app.task(bind=True, name="osism.tasks.netbox.import_device_types")
def import_device_types(self, vendors, library=False):
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
def connect(self, name):
    p = subprocess.Popen(f"python3 /connect/main.py --collection {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-connect-{name}", line)

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-connect-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.disable")
def disable(self, name):
    p = subprocess.Popen(f"python3 /disable/main.py {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-disable-{name}", line)

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-disable-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.generate")
def generate(self, name, template=None):
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
    p = subprocess.Popen(f"python3 /deploy/main.py --device {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        redis.publish(f"netbox-deploy-{name}", line)

    # NOTE: use task_id or request_id in future
    redis.publish(f"netbox-deploy-{name}", "QUIT")


@app.task(bind=True, name="osism.tasks.netbox.init")
@synchronize(key='netbox-init', masters={redis}, auto_release_time=600*1000, blocking=True, timeout=-1)
def init(self, arguments):
    ansible.run.delay("netbox-local", "init", arguments)
