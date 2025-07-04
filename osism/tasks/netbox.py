# SPDX-License-Identifier: Apache-2.0

from celery import Celery
from loguru import logger

from osism import settings, utils
from osism.tasks import Config, run_command

app = Celery("netbox")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    pass


# NOTE: While `get_*` tasks only operate on the NetBox configured in NETBOX_URL,
#       `set_*` tasks additionally operate on all NetBox instances listed in
#       NETBOX_SECONDARIES


@app.task(bind=True, name="osism.tasks.netbox.set_maintenance")
def set_maintenance(self, device_name, state=True):
    """Set the maintenance state for a device in the NetBox."""

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_set_maintenance_{device_name}",
        auto_release_time=60,
    )
    if lock.acquire(timeout=20):
        try:
            for nb in [utils.nb] + utils.secondary_nb_list:
                logger.info(
                    f"Set maintenance state of device {device_name} = {state} on {nb.base_url}"
                )
                device = nb.dcim.devices.get(name=device_name)
                if device:
                    device.custom_fields.update({"maintenance": state})
                    device.save()
                else:
                    logger.error(
                        f"Could not set maintenance for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
    else:
        logger.error("Could not acquire lock for node {device_name}")


@app.task(bind=True, name="osism.tasks.netbox.set_provision_state")
def set_provision_state(self, device_name, state):
    """Set the provision state for a device in the NetBox."""

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_set_provision_state_{device_name}",
        auto_release_time=60,
    )
    if lock.acquire(timeout=20):
        try:

            for nb in [utils.nb] + utils.secondary_nb_list:
                logger.info(
                    f"Set provision state of device {device_name} = {state} on {nb.base_url}"
                )
                device = nb.dcim.devices.get(name=device_name)
                if device:
                    device.custom_fields.update({"provision_state": state})
                    device.save()
                else:
                    logger.error(
                        f"Could not set provision state for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
    else:
        logger.error("Could not acquire lock for node {device_name}")


@app.task(bind=True, name="osism.tasks.netbox.set_power_state")
def set_power_state(self, device_name, state):
    """Set the provision state for a device in the NetBox."""

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_set_provision_state_{device_name}",
        auto_release_time=60,
    )
    if lock.acquire(timeout=20):
        try:
            for nb in [utils.nb] + utils.secondary_nb_list:
                logger.info(
                    f"Set power state of device {device_name} = {state} on {nb.base_url}"
                )
                device = nb.dcim.devices.get(name=device_name)
                if device:
                    device.custom_fields.update({"power_state": state})
                    device.save()
                else:
                    logger.error(
                        f"Could not set power state for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
    else:
        logger.error("Could not acquire lock for node {device_name}")


@app.task(bind=True, name="osism.tasks.netbox.get_location_id")
def get_location_id(self, location_name):
    try:
        location = utils.nb.dcim.locations.get(name=location_name)
    except ValueError:
        return None
    if location:
        return location.id
    else:
        return None


@app.task(bind=True, name="osism.tasks.netbox.get_rack_id")
def get_rack_id(self, rack_name):
    try:
        rack = utils.nb.dcim.racks.get(name=rack_name)
    except ValueError:
        return None
    if rack:
        return rack.id
    else:
        return None


@app.task(bind=True, name="osism.tasks.netbox.get_devices")
def get_devices(self, **query):
    return utils.nb.dcim.devices.filter(**query)


@app.task(bind=True, name="osism.tasks.netbox.get_device_by_name")
def get_device_by_name(self, name):
    return utils.nb.dcim.devices.get(name=name)


@app.task(bind=True, name="osism.tasks.netbox.get_interfaces_by_device")
def get_interfaces_by_device(self, device_name):
    return utils.nb.dcim.interfaces.filter(device=device_name)


@app.task(bind=True, name="osism.tasks.netbox.get_addresses_by_device_and_interface")
def get_addresses_by_device_and_interface(self, device_name, interface_name):
    return utils.nb.dcim.addresses.filter(device=device_name, interface=interface_name)


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
        auto_release_time=auto_release_time,
    )


@app.task(bind=True, name="osism.tasks.netbox.ping")
def ping(self):
    status = utils.nb.status()

    return status
