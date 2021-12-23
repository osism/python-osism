#!/usr/bin/env python3

import logging
import os
import pynetbox
import sys

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')

DEVICE = sys.argv[1]

NETBOX_URL = os.environ.get("NETBOX_API", "http://127.0.0.1:8121")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN", "1111111111111111111111111111111111111111")

nb = pynetbox.api(
    NETBOX_URL,
    token=NETBOX_TOKEN
)

for interface in nb.dcim.interfaces.filter(device=DEVICE):
    if str(interface.type) in ["Virtual"]:
        continue

    if "Port-Channel" in interface.name:
        continue

    if not interface.connected_endpoint and interface.enabled:
        logging.info(f"{interface} --> disabled")
        interface.enabled = False
        interface.save()

    if interface.connected_endpoint and not interface.enabled:
        logging.info(f"{interface} --> enabled")
        interface.enabled = True
        interface.save()
