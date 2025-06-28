# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from typing import Dict, Any

from loguru import logger
import yaml

MAP_ROLE2ENVIRONMENT: Dict[str, Any] = {}
MAP_ROLE2RUNTIME: Dict[str, Any] = {}

for path in Path("/interface/playbooks").glob("*.yml"):
    try:
        with open(path) as fp:
            data = yaml.load(fp, Loader=yaml.SafeLoader)

        MAP_ROLE2ENVIRONMENT = MAP_ROLE2ENVIRONMENT | data
        MAP_ROLE2RUNTIME[os.path.basename(path)[:-4]] = data.keys()

    # Ignore YAML errors here so that we can prevent the command
    # from being non-functional if a runtime environment provides
    # an invalid interface file.
    except yaml.YAMLError as e:
        logger.warning(e)
