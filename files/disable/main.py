#!/usr/bin/env python3

import logging
import os
import sys

import pynetbox

import settings

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')

DEVICE = sys.argv[1]

nb = pynetbox.api(
    settings.NETBOX_URL,
    token=settings.NETBOX_TOKEN
)

if settings.IGNORE_SSL_ERRORS:
    import requests
    requests.packages.urllib3.disable_warnings()
    session = requests.Session()
    session.verify = False
    nb.http_session = session

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
