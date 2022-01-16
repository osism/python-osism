#!/usr/bin/env python3

import logging
import os
import sys

from oslo_config import cfg
import pynetbox
import jinja2

import settings

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')

PROJECT_NAME = 'deploy'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.StrOpt('device', help='Device', required=True),
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

if CONF.debug:
    level = logging.DEBUG
else:
    level = logging.INFO
logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

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

logging.info("Not yet implemented")
