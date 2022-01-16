import io
import os
import subprocess

from celery import Celery
import redis

from osism.tasks import Config

app = Celery('kolla')
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


@app.task(bind=True, name="osism.tasks.netbox.import_device_types")
def import_device_types(self, vendors, library=False):
    r = redis.Redis(host="redis", port="6379")

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
        r.publish("netbox-import-device-types", line)

    # NOTE: use task_id or request_id in future
    r.publish("netbox-import-device-types", "QUIT")
    r.close()


@app.task(bind=True, name="osism.tasks.netbox.connect")
def connect(self, name):
    r = redis.Redis(host="redis", port="6379")
    p = subprocess.Popen(f"python3 /connect/main.py --collection {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        r.publish(f"netbox-connect-{name}", line)

    # NOTE: use task_id or request_id in future
    r.publish(f"netbox-connect-{name}", "QUIT")
    r.close()


@app.task(bind=True, name="osism.tasks.netbox.disable")
def disable(self, name):
    r = redis.Redis(host="redis", port="6379")
    p = subprocess.Popen(f"python3 /disable/main.py {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        r.publish(f"netbox-disable-{name}", line)

    # NOTE: use task_id or request_id in future
    r.publish(f"netbox-disable-{name}", "QUIT")
    r.close()


@app.task(bind=True, name="osism.tasks.netbox.generate")
def generate(self, name, template=None):
    r = redis.Redis(host="redis", port="6379")

    if template:
        p = subprocess.Popen(f"python3 /generate/main.py --template {template} --device {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    else:
        p = subprocess.Popen(f"python3 /generate/main.py --device {name}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
        # NOTE: use task_id or request_id in future
        r.publish(f"netbox-generate-{name}", line)

    # NOTE: use task_id or request_id in future
    r.publish(f"netbox-generate-{name}", "QUIT")
    r.close()
