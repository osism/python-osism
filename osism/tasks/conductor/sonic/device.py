# SPDX-License-Identifier: Apache-2.0

"""Device-related helper functions for SONiC configuration."""

from loguru import logger

from osism import utils
from osism.tasks.conductor.netbox import (
    get_device_oob_ip,
    get_nb_device_query_list_sonic,
)
from osism.tasks.conductor.sonic.constants import DEFAULT_SONIC_ROLES


def get_device_platform(device, hwsku):
    """Get platform for device from sonic_parameters or generate from HWSKU.

    Args:
        device: NetBox device object
        hwsku: Hardware SKU name

    Returns:
        str: Platform string (e.g., 'x86_64-accton_as7326_56x-r0')
    """
    platform = None
    if (
        hasattr(device, "custom_fields")
        and "sonic_parameters" in device.custom_fields
        and device.custom_fields["sonic_parameters"]
        and "platform" in device.custom_fields["sonic_parameters"]
    ):
        platform = device.custom_fields["sonic_parameters"]["platform"]

    if not platform:
        # Generate platform from hwsku: x86_64-{hwsku_lower_with_underscores}-r0
        hwsku_formatted = hwsku.lower().replace("-", "_")
        platform = f"x86_64-{hwsku_formatted}-r0"

    return platform


def get_device_hostname(device):
    """Get hostname for device from inventory_hostname custom field or device name.

    Args:
        device: NetBox device object

    Returns:
        str: Hostname for the device
    """
    hostname = device.name
    if (
        hasattr(device, "custom_fields")
        and "inventory_hostname" in device.custom_fields
        and device.custom_fields["inventory_hostname"]
    ):
        hostname = device.custom_fields["inventory_hostname"]

    return hostname


def get_device_mac_address(device):
    """Get MAC address from device's management interface.

    Args:
        device: NetBox device object

    Returns:
        str: MAC address or default '00:00:00:00:00:00'
    """
    mac_address = "00:00:00:00:00:00"  # Default MAC
    try:
        # Get all interfaces for the device
        interfaces = utils.nb.dcim.interfaces.filter(device_id=device.id)
        for interface in interfaces:
            # Check if interface is marked as management only
            if interface.mgmt_only:
                if interface.mac_address:
                    mac_address = interface.mac_address
                    logger.debug(
                        f"Using MAC address {mac_address} from management interface {interface.name}"
                    )
                    break
    except Exception as e:
        logger.warning(f"Could not get MAC address for device {device.name}: {e}")

    return mac_address


def _serialize_device(device):
    """Convert a pynetbox device to a JSON-serializable dict for the list task.

    The Celery result backend uses JSON, so pynetbox Record objects cannot
    cross the task boundary directly. Each field is accessed defensively so
    a single malformed NetBox record cannot fail serialization for the whole
    list.
    """
    name = getattr(device, "name", None)

    role_name = None
    try:
        if device.role and hasattr(device.role, "name"):
            role_name = device.role.name
    except Exception as e:
        logger.debug(f"Could not get role for device {name}: {e}")

    oob_ip = None
    try:
        oob_result = get_device_oob_ip(device)
        if oob_result:
            oob_ip = oob_result[0]
    except Exception as e:
        logger.debug(f"Could not get OOB IP for device {name}: {e}")

    primary_ip = None
    try:
        if device.primary_ip4:
            primary_ip = str(device.primary_ip4).split("/")[0]
        elif device.primary_ip6:
            primary_ip = str(device.primary_ip6).split("/")[0]
    except Exception as e:
        logger.debug(f"Could not get primary IP for device {name}: {e}")

    hwsku = None
    version = None
    provision_state = None
    try:
        custom_fields = getattr(device, "custom_fields", {}) or {}
        sonic_params = custom_fields.get("sonic_parameters")
        if isinstance(sonic_params, dict):
            hwsku = sonic_params.get("hwsku") or None
            version = sonic_params.get("version") or None
        provision_state = custom_fields.get("provision_state") or None
    except Exception as e:
        logger.debug(f"Could not read custom fields for device {name}: {e}")

    return {
        "name": name,
        "role_name": role_name,
        "oob_ip": oob_ip,
        "primary_ip": primary_ip,
        "hwsku": hwsku,
        "version": version,
        "provision_state": provision_state,
    }


def get_devices(device_name=None):
    """Return serialized SONiC devices matching the query.

    On success always returns a list (possibly empty when no devices match).
    Raises RuntimeError for error conditions (device not found, wrong role,
    NetBox failure) so callers can distinguish errors from empty results.
    """
    devices = []

    if device_name:
        try:
            device = utils.nb.dcim.devices.get(name=device_name)
        except Exception as e:
            raise RuntimeError(f"Error fetching device {device_name}: {e}") from e

        if not device:
            raise RuntimeError(f"Device {device_name} not found in NetBox")

        role_slug = device.role.slug if device.role else None
        if role_slug not in DEFAULT_SONIC_ROLES:
            raise RuntimeError(
                f"Device {device_name} has role '{role_slug}' which is not "
                f"in allowed SONiC roles: {', '.join(DEFAULT_SONIC_ROLES)}"
            )

        devices.append(device)
        logger.debug(f"Found device: {device.name} with role: {role_slug}")
    else:
        try:
            nb_device_query_list = get_nb_device_query_list_sonic()
            for nb_device_query in nb_device_query_list:
                for device in utils.nb.dcim.devices.filter(**nb_device_query):
                    if device.role and device.role.slug in DEFAULT_SONIC_ROLES:
                        devices.append(device)
                        logger.debug(
                            f"Found device: {device.name} with role: {device.role.slug}"
                        )
        except Exception as e:
            raise RuntimeError(
                f"Error retrieving SONiC devices from NetBox: {e}"
            ) from e

    return [_serialize_device(device) for device in devices]
