# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from typing import Dict, Any
import yaml

MAP_ROLE2ENVIRONMENT: Dict[str, Any] = {}

for path in Path("/interface/playbooks").glob("*-ansible.yml"):
    with open(path) as fp:
        data = yaml.load(fp, Loader=yaml.SafeLoader)

    MAP_ROLE2ENVIRONMENT = MAP_ROLE2ENVIRONMENT | data
