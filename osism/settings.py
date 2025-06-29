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
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", read_secret("NETBOX_TOKEN"))
IGNORE_SSL_ERRORS = os.getenv("IGNORE_SSL_ERRORS", "True") == "True"

# 43200 seconds = 12 hours
GATHER_FACTS_SCHEDULE = float(os.getenv("GATHER_FACTS_SCHEDULE", "43200.0"))
INVENTORY_RECONCILER_SCHEDULE = float(
    os.getenv("INVENTORY_RECONCILER_SCHEDULE", "600.0")
)

OSISM_API_URL = os.getenv("OSISM_API_URL", None)

NETBOX_FILTER_CONDUCTOR_IRONIC = os.getenv(
    "NETBOX_FILTER_CONDUCTOR_IRONIC",
    "[{'state': 'active', 'tag': ['managed-by-ironic']}]",
)

NETBOX_FILTER_CONDUCTOR_SONIC = os.getenv(
    "NETBOX_FILTER_CONDUCTOR_SONIC",
    "[{'state': 'active', 'tag': ['managed-by-metalbox']}]",
)

# SONiC export configuration
SONIC_EXPORT_DIR = os.getenv("SONIC_EXPORT_DIR", "/etc/sonic/export")
SONIC_EXPORT_PREFIX = os.getenv("SONIC_EXPORT_PREFIX", "osism_")
SONIC_EXPORT_SUFFIX = os.getenv("SONIC_EXPORT_SUFFIX", "_config_db.json")
SONIC_EXPORT_IDENTIFIER = os.getenv("SONIC_EXPORT_IDENTIFIER", "serial-number")

NETBOX_SECONDARIES = (
    os.getenv("NETBOX_SECONDARIES", read_secret("NETBOX_SECONDARIES")) or "[]"
)

# Redfish connection timeout in seconds
REDFISH_TIMEOUT = int(os.getenv("REDFISH_TIMEOUT", "20"))
