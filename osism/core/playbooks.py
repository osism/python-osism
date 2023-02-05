from pathlib import Path

import yaml

MAP_ROLE2ENVIRONMENT = {}

for path in Path("/interface/playbooks").glob("*-ansible.yml"):
    with open(path) as fp:
        data = yaml.load(fp, Loader=yaml.SafeLoader)

    MAP_ROLE2ENVIRONMENT = MAP_ROLE2ENVIRONMENT | data
