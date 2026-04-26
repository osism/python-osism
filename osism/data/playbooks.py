# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from loguru import logger
import yaml

_PLAYBOOK_DIR = Path("/interface/playbooks")
_MAP_ROLE2ENVIRONMENT = None
_MAP_ROLE2RUNTIME = None


def _reset_caches():
    global _MAP_ROLE2ENVIRONMENT, _MAP_ROLE2RUNTIME
    _MAP_ROLE2ENVIRONMENT = None
    _MAP_ROLE2RUNTIME = None
    globals().pop("MAP_ROLE2ENVIRONMENT", None)
    globals().pop("MAP_ROLE2RUNTIME", None)


def _load_playbook_data():
    global _MAP_ROLE2ENVIRONMENT, _MAP_ROLE2RUNTIME
    if _MAP_ROLE2ENVIRONMENT is not None:
        return

    _MAP_ROLE2ENVIRONMENT = {}
    _MAP_ROLE2RUNTIME = {}

    for path in _PLAYBOOK_DIR.glob("*.yml"):
        try:
            with open(path) as fp:
                data = yaml.load(fp, Loader=yaml.SafeLoader)

            _MAP_ROLE2ENVIRONMENT = _MAP_ROLE2ENVIRONMENT | data
            _MAP_ROLE2RUNTIME[os.path.basename(path)[:-4]] = data.keys()

        # Ignore YAML errors here so that we can prevent the command
        # from being non-functional if a runtime environment provides
        # an invalid interface file.
        except yaml.YAMLError as e:
            logger.warning(e)


def __getattr__(name):
    if name == "MAP_ROLE2ENVIRONMENT":
        _load_playbook_data()
        globals()["MAP_ROLE2ENVIRONMENT"] = _MAP_ROLE2ENVIRONMENT
        return _MAP_ROLE2ENVIRONMENT
    elif name == "MAP_ROLE2RUNTIME":
        _load_playbook_data()
        globals()["MAP_ROLE2RUNTIME"] = _MAP_ROLE2RUNTIME
        return _MAP_ROLE2RUNTIME
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
