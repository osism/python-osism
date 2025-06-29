# SPDX-License-Identifier: Apache-2.0

import copy
from celery import Celery
from celery.signals import worker_process_init
from loguru import logger

from osism.tasks import Config
from osism.tasks.conductor.config import get_configuration
from osism.tasks.conductor.ironic import sync_ironic as _sync_ironic
from osism.tasks.conductor.redfish import get_resources as _get_redfish_resources
from osism.tasks.conductor.sonic import sync_sonic as _sync_sonic


# App configuration
app = Celery("conductor")
app.config_from_object(Config)


@worker_process_init.connect
def celery_init_worker(**kwargs):
    pass


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


# Tasks
@app.task(bind=True, name="osism.tasks.conductor.get_ironic_parameters")
def get_ironic_parameters(self):
    configuration = get_configuration()
    if "ironic_parameters" in configuration:
        # NOTE: Do not pass by reference, everybody gets their own copy to work with
        return copy.deepcopy(configuration["ironic_parameters"])

    return {}


@app.task(bind=True, name="osism.tasks.conductor.sync_netbox")
def sync_netbox(self, force_update=False):
    logger.info("Not implemented")


@app.task(bind=True, name="osism.tasks.conductor.sync_ironic")
def sync_ironic(self, force_update=False):
    _sync_ironic(self.request.id, get_ironic_parameters, force_update)


@app.task(bind=True, name="osism.tasks.conductor.sync_sonic")
def sync_sonic(self, device_name=None, show_diff=True):
    return _sync_sonic(device_name, self.request.id, show_diff)


@app.task(bind=True, name="osism.tasks.conductor.get_redfish_resources")
def get_redfish_resources(self, hostname, resource_type):
    return _get_redfish_resources(hostname, resource_type)


__all__ = [
    "app",
    "get_ironic_parameters",
    "get_redfish_resources",
    "sync_netbox",
    "sync_ironic",
    "sync_sonic",
]
