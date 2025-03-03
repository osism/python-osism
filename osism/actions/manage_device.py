# SPDX-License-Identifier: CC-BY-NC-4.0
# Copyright OSISM GmbH, 2022-2023

from loguru import logger
from pottery import Redlock

from osism import utils


def get_state(device):
    """Gets the state (device_state) stored in the Netbox for a  device."""

    result = None
    device_a = utils.nb.dcim.devices.get(name=device)
    result = device_a.custom_fields["device_state"]

    return result


def get_states(devices):
    """Gets the state (device_state) stored in the Netbox for a list of devices."""

    result = {}
    for device in devices:
        device_a = utils.nb.dcim.devices.get(name=device)
        result[device] = device_a.custom_fields["device_state"]

    return result


def set_maintenance(device, state):
    """Set the maintenance state for a device in the Netbox."""

    logger.info(f"Set maintenance state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"maintenance": state}
    device_a.save()


def set_ironic_state(device, state):
    """Set the ironic state (ironic_state) for a device in the Netbox."""

    logger.info(f"Set ironic state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"ironic_state": state}
    device_a.save()


def set_introspection_state(device, state):
    """Set the introspection state (introspection_state) for a device in the Netbox."""

    logger.info(f"Set introspection state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"introspection_state": state}
    device_a.save()


def set_deployment_state(device, state):
    """Set the deployment state (deployment_state) for a device in the Netbox."""

    logger.info(f"Set deployment state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"deployment_state": state}
    device_a.save()


def set_device_state(device, state):
    """Set the state (device_state) for a device in the Netbox."""

    logger.info(f"Set state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"device_state": state}
    device_a.save()


def set_state(device, state, state_type):
    """Set the state for a device in the Netbox."""

    lock = Redlock(key=f"lock_state_{device}", masters={utils.redis})
    lock.acquire()

    if state_type == "power":
        set_power_state(device, state)
    elif state_type == "provision":
        set_provision_state(device, state)
    elif state_type == "introspection":
        set_introspection_state(device, state)
    elif state_type == "ironic":
        set_ironic_state(device, state)
    elif state_type == "deployment":
        set_deployment_state(device, state)
    else:
        set_device_state(device, state)

    lock.release()


def set_provision_state(device, state):
    """Set the provision state (provision_state) for a device in the Netbox."""

    logger.info(f"Set provision state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"provision_state": state}
    device_a.save()


def set_power_state(device, state):
    """Set the power state (power_state) for a device in the Netbox."""

    logger.info(f"Set power state of device {device} = {state}")

    device_a = utils.nb.dcim.devices.get(name=device)
    device_a.custom_fields = {"power_state": state}
    device_a.save()
