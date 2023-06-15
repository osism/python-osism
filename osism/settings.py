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


NETBOX_URL = os.getenv("NETBOX_API")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", read_secret("NETBOX_TOKEN"))
IGNORE_SSL_ERRORS = os.getenv("IGNORE_SSL_ERRORS", "True") == "True"

BASE_PATH = os.getenv("BASE_PATH", "/devicetype-library/device-types/")
VENDORS = os.getenv("VENDORS", "").split()

# 43200 seconds = 12 hours
GATHER_FACTS_SCHEDULE = 43200.0
INVENTORY_RECONCILER_SCHEDULE = 600.0
