# SPDX-License-Identifier: Apache-2.0

import copy
import os
from celery import Celery
from celery.signals import worker_process_init
from loguru import logger

from osism.tasks import Config
from osism.tasks.conductor.config import get_configuration
from osism.tasks.conductor.ironic import sync_ironic as _sync_ironic


# App configuration
app = Celery("conductor")
app.config_from_object(Config)


@worker_process_init.connect
def celery_init_worker(**kwargs):
    pass


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


def get_port_config(hwsku):
    """Get port configuration for a given HWSKU.

    Args:
        hwsku: Hardware SKU name (e.g., 'Accton-AS5835-54T')

    Returns:
        dict: Port configuration with port names as keys and their properties as values
              Example: {'Ethernet0': {'lanes': '2', 'alias': 'tenGigE1', 'index': '1', 'speed': '10000'}}
    """
    port_config = {}
    config_path = f"/etc/sonic/port_config/{hwsku}.ini"

    if not os.path.exists(config_path):
        logger.error(f"Port config file not found: {config_path}")
        return port_config

    try:
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                parts = line.split()
                if len(parts) >= 5:
                    port_name = parts[0]
                    port_config[port_name] = {
                        "lanes": parts[1],
                        "alias": parts[2],
                        "index": parts[3],
                        "speed": parts[4],
                    }
    except Exception as e:
        logger.error(f"Error parsing port config file {config_path}: {e}")

    return port_config


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
def sync_sonic(self):
    logger.info("Preparing SONIC configuration files")

    # List of supported HWSKUs
    supported_hwskus = [
        "Accton-AS5835-54T",
        "Accton-AS7326-56X",
        "Accton-AS7726-32X",
        "Accton-AS9716-32D",
    ]

    logger.debug(f"Supported HWSKUs: {', '.join(supported_hwskus)}")

    # TODO: Implement SONIC configuration file preparation
    logger.info("SONIC sync task not yet implemented")


__all__ = [
    "app",
    "get_ironic_parameters",
    "get_port_config",
    "sync_netbox",
    "sync_ironic",
    "sync_sonic",
]
