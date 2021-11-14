#!/usr/bin/env python3

from oslo_config import cfg
from oslo_service import service

if __name__ == "__main__":
    CONF = cfg.CONF
    launcher = service.launch(CONF, service, workers=2)
