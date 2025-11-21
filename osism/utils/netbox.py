# SPDX-License-Identifier: Apache-2.0

from loguru import logger
from osism import utils


def find_device_by_identifier(identifier: str, search_fields: list = None):
    """
    Find a NetBox device by multiple identifier types.

    Searches through various device fields in priority order to locate
    a device in NetBox. Default search order: name, cf_inventory_hostname, serial.

    Args:
        identifier: Device identifier (name, hostname, serial number, etc.)
        search_fields: List of field names to search.
                      Default: ['name', 'cf_inventory_hostname', 'serial']

    Returns:
        Device object if found, None otherwise

    Examples:
        >>> device = find_device_by_identifier('server-01')
        >>> device = find_device_by_identifier('host123', ['cf_inventory_hostname'])
    """
    if not utils.nb:
        logger.debug("NetBox connection not available")
        return None

    if not identifier or not str(identifier).strip():
        logger.debug("Empty identifier provided")
        return None

    identifier = str(identifier).strip()

    if search_fields is None:
        search_fields = ["name", "cf_inventory_hostname", "serial"]

    for field in search_fields:
        try:
            logger.debug(f"Searching for device by {field}: {identifier}")

            if field == "name":
                # Use get() for name field (expects unique result)
                device = utils.nb.dcim.devices.get(name=identifier)
                if device:
                    logger.debug(f"Found device '{device.name}' by {field}")
                    return device
            else:
                # Use filter() for custom fields and serial
                devices = utils.nb.dcim.devices.filter(**{field: identifier})
                if devices:
                    device = list(devices)[0]
                    logger.debug(f"Found device '{device.name}' by {field}")
                    return device

        except (StopIteration, IndexError):
            continue
        except Exception as e:
            logger.debug(f"Error searching by {field}: {e}")
            continue

    logger.warning(f"Device '{identifier}' not found in NetBox")
    return None
