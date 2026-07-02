# SPDX-License-Identifier: Apache-2.0

import os


# Read secret from file
def read_secret(secret_name):
    try:
        f = open("/run/secrets/" + secret_name, "r", encoding="utf-8")
    except EnvironmentError:
        return ""
    else:
        with f:
            return f.readline().strip()


OPENSEARCH_ADDRESS = os.getenv("OPENSEARCH_ADDRESS")
OPENSEARCH_PROTOCOL = os.getenv("OPENSEARCH_PROTOCOL", "https")
OPENSEARCH_PORT = os.getenv("OPENSEARCH_PORT")

REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))


NETBOX_URL = os.getenv("NETBOX_API", os.getenv("NETBOX_URL"))
NETBOX_TOKEN = str(
    os.getenv("NETBOX_TOKEN") or read_secret("NETBOX_TOKEN") or ""
).strip()
IGNORE_SSL_ERRORS = os.getenv("IGNORE_SSL_ERRORS", "True") == "True"

# 43200 seconds = 12 hours
_DEFAULT_FACTS_INTERVAL_SECONDS = 43200
GATHER_FACTS_SCHEDULE = float(
    os.getenv("GATHER_FACTS_SCHEDULE", str(_DEFAULT_FACTS_INTERVAL_SECONDS))
)
# Intentionally independent of GATHER_FACTS_SCHEDULE: setting the schedule to 0
# to disable periodic gathering must not force every fact to look stale.
FACTS_MAX_AGE = int(os.getenv("FACTS_MAX_AGE", str(_DEFAULT_FACTS_INTERVAL_SECONDS)))
INVENTORY_RECONCILER_SCHEDULE = float(
    os.getenv("INVENTORY_RECONCILER_SCHEDULE", "600.0")
)

OSISM_API_URL = os.getenv("OSISM_API_URL", None)

OPERATOR_USER = os.getenv("OSISM_OPERATOR_USER", "dragon")

FRR_DUMMY_INTERFACE = os.getenv("OSISM_FRR_DUMMY_INTERFACE", "loopback0")

DEFAULT_NETBOX_FILTER_CONDUCTOR_IRONIC = (
    "[{'status': 'active', 'tag': ['managed-by-ironic']}]"
)
DEFAULT_NETBOX_FILTER_CONDUCTOR_SONIC = (
    "[{'status': 'active', 'tag': ['managed-by-metalbox']}]"
)

NETBOX_FILTER_CONDUCTOR_IRONIC = os.getenv(
    "NETBOX_FILTER_CONDUCTOR_IRONIC",
    DEFAULT_NETBOX_FILTER_CONDUCTOR_IRONIC,
)

NETBOX_FILTER_CONDUCTOR_SONIC = os.getenv(
    "NETBOX_FILTER_CONDUCTOR_SONIC",
    DEFAULT_NETBOX_FILTER_CONDUCTOR_SONIC,
)

# SONiC export configuration
SONIC_EXPORT_DIR = os.getenv("SONIC_EXPORT_DIR", "/etc/sonic/export")
SONIC_EXPORT_PREFIX = os.getenv("SONIC_EXPORT_PREFIX", "osism_")
SONIC_EXPORT_SUFFIX = os.getenv("SONIC_EXPORT_SUFFIX", "_config_db.json")
SONIC_EXPORT_IDENTIFIER = os.getenv("SONIC_EXPORT_IDENTIFIER", "serial-number")

# SONiC ZTP firmware configuration
#
# The ZTP firmware install uses a dynamic-url built from
# <prefix><identifier><suffix> (see osism/ansible-collection-services#2131),
# so every switch fetches its firmware image via a per-device name during ZTP.
# sync_sonic creates that per-device name as a symlink to the version-specific
# image <prefix><version><suffix>, driven by the device's
# sonic_parameters.version custom field. The defaults mirror the ansible
# httpd role and place the links in the same httpd-served directory as the
# config exports (SONIC_EXPORT_DIR), which stays the single source of truth
# for the base export path unless a separate firmware directory is set.
SONIC_FIRMWARE_DIR = os.getenv("SONIC_FIRMWARE_DIR", SONIC_EXPORT_DIR)
SONIC_FIRMWARE_PREFIX = os.getenv(
    "SONIC_FIRMWARE_PREFIX", "sonic-broadcom-enterprise-base_"
)
SONIC_FIRMWARE_SUFFIX = os.getenv("SONIC_FIRMWARE_SUFFIX", ".bin")
SONIC_FIRMWARE_IDENTIFIER = os.getenv("SONIC_FIRMWARE_IDENTIFIER", "serial-number")


NETBOX_SECONDARIES = (
    os.getenv("NETBOX_SECONDARIES", read_secret("NETBOX_SECONDARIES")) or "[]"
)

# Redfish connection timeout in seconds
REDFISH_TIMEOUT = int(os.getenv("REDFISH_TIMEOUT", "20"))

# NetBox connection limiting
NETBOX_MAX_CONNECTIONS = int(os.getenv("NETBOX_MAX_CONNECTIONS", "5"))
