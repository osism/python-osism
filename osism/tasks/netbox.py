# SPDX-License-Identifier: Apache-2.0

import requests.exceptions
from celery import Celery
from loguru import logger

from osism import settings, utils
from osism.tasks import Config, run_command

app = Celery("netbox")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


def _update_netbox_device_field(nb, device_name, field_name, value):
    """Helper to update a NetBox device field with semaphore limiting.

    Args:
        nb: NetBox API instance
        device_name: Name of the device
        field_name: Custom field name to update
        value: Value to set

    Returns:
        bool: True if successful, False otherwise
    """
    semaphore = utils.create_netbox_semaphore(nb.base_url)
    with semaphore:
        try:
            device = nb.dcim.devices.get(name=device_name)
            if device:
                device.custom_fields.update({field_name: value})
                device.save()
                return True
            return False
        except requests.exceptions.ConnectTimeout as e:
            logger.error(
                f"Connection timeout while updating {field_name} for device {device_name} "
                f"on {nb.base_url}: {e}"
            )
            return False
        except requests.exceptions.Timeout as e:
            logger.error(
                f"Request timeout while updating {field_name} for device {device_name} "
                f"on {nb.base_url}: {e}"
            )
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(
                f"Connection error while updating {field_name} for device {device_name} "
                f"on {nb.base_url}: {e}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Request error while updating {field_name} for device {device_name} "
                f"on {nb.base_url}: {e}"
            )
            return False


def _matches_netbox_filter(nb, netbox_filter, is_primary=False):
    """Check if a NetBox instance matches the given filter.

    Args:
        nb: NetBox API instance
        netbox_filter: Filter string (substring match, case-insensitive)
        is_primary: Whether this is the primary NetBox instance

    Returns:
        bool: True if the NetBox instance matches the filter
    """
    if not netbox_filter:
        return True

    filter_lower = netbox_filter.lower()

    # Check if primary NetBox matches 'primary' filter
    if is_primary and "primary" in filter_lower:
        return True

    # Check URL
    if filter_lower in nb.base_url.lower():
        return True

    # Check NETBOX_NAME attribute (if present on secondary instances)
    netbox_name = getattr(nb, "netbox_name", None)
    if netbox_name and filter_lower in netbox_name.lower():
        return True

    # Check NETBOX_SITE attribute (if present on secondary instances)
    netbox_site = getattr(nb, "netbox_site", None)
    if netbox_site and filter_lower in netbox_site.lower():
        return True

    return False


@app.task(bind=True, name="osism.tasks.netbox.run")
def run(self, action, arguments):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    pass


# NOTE: While `get_*` tasks only operate on the NetBox configured in NETBOX_URL,
#       `set_*` tasks additionally operate on all NetBox instances listed in
#       NETBOX_SECONDARIES


@app.task(bind=True, name="osism.tasks.netbox.set_maintenance")
def set_maintenance(
    self, device_name, state=True, netbox_filter=None, secondary_nb_list=None
):
    """Set the maintenance state for a device in the NetBox.

    Args:
        device_name: Name of the device
        state: Maintenance state (True/False)
        netbox_filter: Optional filter (substring match, case-insensitive).
                      Matches against NetBox name, site, or URL.
                      Use 'primary' to match the primary NetBox instance.
        secondary_nb_list: Optional list of secondary NetBox instances to use.
                          If not provided, uses utils.secondary_nb_list.

    Returns:
        bool: True if lock was acquired and operation succeeded, False if lock could not be acquired.
    """
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_{device_name}",
        auto_release_time=300,
    )
    if lock.acquire(timeout=120):
        try:
            # Process primary NetBox
            if _matches_netbox_filter(utils.nb, netbox_filter, is_primary=True):
                logger.info(
                    f"Set maintenance state of device {device_name} = {state} on {utils.nb.base_url}"
                )
                if not _update_netbox_device_field(
                    utils.nb, device_name, "maintenance", state
                ):
                    logger.error(
                        f"Could not set maintenance for {device_name} on {utils.nb.base_url}"
                    )
            else:
                logger.debug(
                    f"Skipping primary NetBox {utils.nb.base_url} (does not match filter: {netbox_filter})"
                )

            # Process secondary NetBox instances
            secondary_list = (
                secondary_nb_list
                if secondary_nb_list is not None
                else utils.secondary_nb_list
            )
            for nb in secondary_list:
                if not _matches_netbox_filter(nb, netbox_filter, is_primary=False):
                    logger.debug(
                        f"Skipping {nb.base_url} (does not match filter: {netbox_filter})"
                    )
                    continue

                logger.info(
                    f"Set maintenance state of device {device_name} = {state} on {nb.base_url}"
                )
                if not _update_netbox_device_field(
                    nb, device_name, "maintenance", state
                ):
                    logger.error(
                        f"Could not set maintenance for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
        return True
    else:
        logger.error(f"Could not acquire lock for node {device_name}")
        return False


@app.task(bind=True, name="osism.tasks.netbox.set_provision_state")
def set_provision_state(
    self, device_name, state, netbox_filter=None, secondary_nb_list=None
):
    """Set the provision state for a device in the NetBox.

    Args:
        device_name: Name of the device
        state: Provision state value
        netbox_filter: Optional filter (substring match, case-insensitive).
                      Matches against NetBox name, site, or URL.
                      Use 'primary' to match the primary NetBox instance.
        secondary_nb_list: Optional list of secondary NetBox instances to use.
                          If not provided, uses utils.secondary_nb_list.

    Returns:
        bool: True if lock was acquired and operation succeeded, False if lock could not be acquired.
    """
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_{device_name}",
        auto_release_time=300,
    )
    if lock.acquire(timeout=120):
        try:
            # Process primary NetBox
            if _matches_netbox_filter(utils.nb, netbox_filter, is_primary=True):
                logger.info(
                    f"Set provision state of device {device_name} = {state} on {utils.nb.base_url}"
                )
                if not _update_netbox_device_field(
                    utils.nb, device_name, "provision_state", state
                ):
                    logger.error(
                        f"Could not set provision state for {device_name} on {utils.nb.base_url}"
                    )
            else:
                logger.debug(
                    f"Skipping primary NetBox {utils.nb.base_url} (does not match filter: {netbox_filter})"
                )

            # Process secondary NetBox instances
            secondary_list = (
                secondary_nb_list
                if secondary_nb_list is not None
                else utils.secondary_nb_list
            )
            for nb in secondary_list:
                if not _matches_netbox_filter(nb, netbox_filter, is_primary=False):
                    logger.debug(
                        f"Skipping {nb.base_url} (does not match filter: {netbox_filter})"
                    )
                    continue

                logger.info(
                    f"Set provision state of device {device_name} = {state} on {nb.base_url}"
                )
                if not _update_netbox_device_field(
                    nb, device_name, "provision_state", state
                ):
                    logger.error(
                        f"Could not set provision state for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
        return True
    else:
        logger.error(f"Could not acquire lock for node {device_name}")
        return False


@app.task(bind=True, name="osism.tasks.netbox.set_power_state")
def set_power_state(
    self, device_name, state, netbox_filter=None, secondary_nb_list=None
):
    """Set the power state for a device in the NetBox.

    Args:
        device_name: Name of the device
        state: Power state value (None is converted to "n/a")
        netbox_filter: Optional filter (substring match, case-insensitive).
                      Matches against NetBox name, site, or URL.
                      Use 'primary' to match the primary NetBox instance.
        secondary_nb_list: Optional list of secondary NetBox instances to use.
                          If not provided, uses utils.secondary_nb_list.

    Returns:
        bool: True if lock was acquired and operation succeeded, False if lock could not be acquired.
    """
    # Convert None to "n/a" for clearer user feedback
    if state is None:
        state = "n/a"

    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    lock = utils.create_redlock(
        key=f"lock_osism_tasks_netbox_{device_name}",
        auto_release_time=300,
    )
    if lock.acquire(timeout=120):
        try:
            # Process primary NetBox
            if _matches_netbox_filter(utils.nb, netbox_filter, is_primary=True):
                logger.info(
                    f"Set power state of device {device_name} = {state} on {utils.nb.base_url}"
                )
                if not _update_netbox_device_field(
                    utils.nb, device_name, "power_state", state
                ):
                    logger.error(
                        f"Could not set power state for {device_name} on {utils.nb.base_url}"
                    )
            else:
                logger.debug(
                    f"Skipping primary NetBox {utils.nb.base_url} (does not match filter: {netbox_filter})"
                )

            # Process secondary NetBox instances
            secondary_list = (
                secondary_nb_list
                if secondary_nb_list is not None
                else utils.secondary_nb_list
            )
            for nb in secondary_list:
                if not _matches_netbox_filter(nb, netbox_filter, is_primary=False):
                    logger.debug(
                        f"Skipping {nb.base_url} (does not match filter: {netbox_filter})"
                    )
                    continue

                logger.info(
                    f"Set power state of device {device_name} = {state} on {nb.base_url}"
                )
                if not _update_netbox_device_field(
                    nb, device_name, "power_state", state
                ):
                    logger.error(
                        f"Could not set power state for {device_name} on {nb.base_url}"
                    )
        finally:
            lock.release()
        return True
    else:
        logger.error(f"Could not acquire lock for node {device_name}")
        return False


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
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

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
