# SPDX-License-Identifier: Apache-2.0

from ansible import constants as ansible_constants
from ansible.parsing.vault import VaultLib, VaultSecret
from loguru import logger

from osism import utils
import sushy
import urllib3


def deep_compare(a, b, updates):
    """
    Find items in a that do not exist in b or are different.
    Write required changes into updates
    """
    for key, value in a.items():
        if type(value) is not dict:
            if key not in b or b[key] != value:
                updates[key] = value
        else:
            updates[key] = {}
            deep_compare(a[key], b[key], updates[key])
            if not updates[key]:
                updates.pop(key)


def deep_merge(a, b):
    for key, value in b.items():
        if value == "DELETE":
            # NOTE: Use special string to remove keys
            a.pop(key, None)
        elif (
            key not in a.keys()
            or not isinstance(a[key], dict)
            or not isinstance(value, dict)
        ):
            a[key] = value
        else:
            deep_merge(a[key], value)


def deep_decrypt(a, vault):
    if a is None:
        return
    if isinstance(a, dict):
        for key, value in list(a.items()):
            if isinstance(value, (dict, list)):
                deep_decrypt(a[key], vault)
            elif vault.is_encrypted(value):
                try:
                    a[key] = vault.decrypt(value).decode()
                except Exception:
                    a.pop(key, None)
    elif isinstance(a, list):
        for i, item in enumerate(a):
            if isinstance(item, (dict, list)):
                deep_decrypt(item, vault)
            elif vault.is_encrypted(item):
                try:
                    a[i] = vault.decrypt(item).decode()
                except Exception:
                    pass


def get_vault():
    """Create and return a VaultLib instance for decrypting secrets"""
    try:
        vault_secret = utils.get_ansible_vault_password()
        vault = VaultLib(
            [
                (
                    ansible_constants.DEFAULT_VAULT_ID_MATCH,
                    VaultSecret(vault_secret.encode()),
                )
            ]
        )
    except Exception:
        logger.error("Unable to get vault secret. Dropping encrypted entries")
        vault = VaultLib()
    return vault


def get_redfish_connection(
    hostname, username=None, password=None, ignore_ssl_errors=True, timeout=None
):
    """Create a Redfish connection to the specified hostname."""
    from osism import settings
    from osism.tasks import openstack

    if not hostname:
        return None

    # Use configurable timeout if not provided
    if timeout is None:
        timeout = settings.REDFISH_TIMEOUT

    # Get Redfish address from Ironic driver_info
    base_url = f"https://{hostname}"
    device = None

    # Try to find NetBox device first for conductor configuration fallback
    if utils.nb:
        try:
            # First try to find device by name
            device = utils.nb.dcim.devices.get(name=hostname)

            # If not found by name, try by inventory_hostname custom field
            if not device:
                devices = utils.nb.dcim.devices.filter(cf_inventory_hostname=hostname)
                if devices:
                    device = devices[0]
        except Exception as exc:
            logger.warning(f"Could not resolve hostname {hostname} via NetBox: {exc}")

    try:
        ironic_node = openstack.baremetal_node_show(hostname, ignore_missing=True)
        if ironic_node and "driver_info" in ironic_node:
            driver_info = ironic_node["driver_info"]
            # Use redfish_address from driver_info if available (contains full URL)
            if "redfish_address" in driver_info:
                base_url = driver_info["redfish_address"]
                logger.info(f"Using Ironic redfish_address {base_url} for {hostname}")
        else:
            # Fallback to conductor configuration if Ironic driver_info not available
            conductor_address = _get_conductor_redfish_address(device)
            if conductor_address:
                base_url = conductor_address
                logger.info(
                    f"Using conductor redfish_address {base_url} for {hostname}"
                )
    except Exception as exc:
        logger.warning(f"Could not get Ironic node for {hostname}: {exc}")
        # Fallback to conductor configuration on Ironic error
        conductor_address = _get_conductor_redfish_address(device)
        if conductor_address:
            base_url = conductor_address
            logger.info(f"Using conductor redfish_address {base_url} for {hostname}")

    # Get credentials from conductor configuration if not provided
    if not username or not password:
        conductor_username, conductor_password = _get_conductor_redfish_credentials(
            device
        )
        if not username:
            username = conductor_username
        if not password:
            password = conductor_password

    auth = sushy.auth.SessionOrBasicAuth(username=username, password=password)

    try:
        if ignore_ssl_errors:
            urllib3.disable_warnings()
            conn = sushy.Sushy(base_url, auth=auth, verify=False)
        else:
            conn = sushy.Sushy(base_url, auth=auth)

        return conn
    except Exception as exc:
        logger.error(
            f"Unable to connect to Redfish API at {base_url} with timeout {timeout}s: {exc}"
        )
        return None


def _get_conductor_redfish_credentials(device):
    """Get Redfish credentials from conductor configuration and device secrets."""
    from osism.tasks.conductor.config import get_configuration
    from osism.tasks.conductor.ironic import _prepare_node_attributes

    try:
        if not device:
            return None, None

        # Use _prepare_node_attributes to get processed node attributes
        def get_ironic_parameters():
            configuration = get_configuration()
            return configuration.get("ironic_parameters", {})

        node_attributes = _prepare_node_attributes(device, get_ironic_parameters)

        # Extract Redfish credentials if available
        if (
            "driver_info" in node_attributes
            and node_attributes.get("driver") == "redfish"
        ):
            driver_info = node_attributes["driver_info"]
            username = driver_info.get("redfish_username")
            password = driver_info.get("redfish_password")
            return username, password

    except Exception as exc:
        logger.warning(f"Could not get conductor Redfish credentials: {exc}")

    return None, None


def _get_conductor_redfish_address(device):
    """Get Redfish address from conductor configuration and device OOB IP."""
    from osism.tasks.conductor.config import get_configuration
    from osism.tasks.conductor.ironic import _prepare_node_attributes

    try:
        if not device:
            return None

        # Use _prepare_node_attributes to get processed node attributes
        def get_ironic_parameters():
            configuration = get_configuration()
            return configuration.get("ironic_parameters", {})

        node_attributes = _prepare_node_attributes(device, get_ironic_parameters)

        # Extract Redfish address if available
        if (
            "driver_info" in node_attributes
            and node_attributes.get("driver") == "redfish"
        ):
            driver_info = node_attributes["driver_info"]
            address = driver_info.get("redfish_address")
            return address

    except Exception as exc:
        logger.warning(f"Could not get conductor Redfish address: {exc}")

    return None
