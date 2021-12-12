from celery import Celery
import subprocess

from osism.tasks import Config

app = Celery('reconciler')
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(600.0, run.s(), expires=10)
    sender.add_periodic_task(600.0, sync_inventory_with_netbox.s(), expires=10)


@app.task(bind=True, name="osism.tasks.reconciler.run")
def run(self):
    p = subprocess.Popen("/run.sh", shell=True)
    p.wait()


@app.task(bind=True, name="osism.tasks.reconciler.sync_inventory_with_netbox")
def sync_inventory_with_netbox(self):
    p = subprocess.Popen("/sync-inventory-with-netbox.sh.sh", shell=True)
    p.wait()
