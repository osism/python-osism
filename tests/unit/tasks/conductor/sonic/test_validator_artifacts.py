# SPDX-License-Identifier: Apache-2.0

"""Run the ConfigDB validator over the artifacts the repository ships.

``test_validator`` checks the validator's behaviour against hand-built
configs. This module checks the other direction: that real committed
artifacts pass it. That is what makes the validator a gate rather than a
command someone has to remember to run — a change to the YANG models, the
schema generator or the config generator that starts rejecting a shipped
config fails here, at PR time, without NetBox or the docker-compose harness.

Warnings are deliberately not asserted on. They report tables with no schema,
which is a coverage signal rather than a defect signal: SONiC ships ConfigDB
tables that upstream YANG does not model, and the vendored models are
community SONiC while these configs come from Enterprise builds.
"""

import json

import pytest

from osism.tasks.conductor.sonic.validator import validate_config

from ._detection_helpers import repo_root


def _artifacts():
    """Every committed ConfigDB document the validator should accept.

    The base config is the one that is always present — it is lifted from a
    real device and is what generated configs are layered onto. The E2E
    goldens join it once that series lands; globbing rather than listing them
    means they are covered the moment they appear.
    """
    root = repo_root()
    paths = [root / "files" / "sonic" / "config_db.json"]
    paths.extend(sorted((root / "tests" / "e2e" / "golden").glob("*_config_db.json")))
    return [p for p in paths if p.exists()]


ARTIFACTS = _artifacts()


def test_there_is_something_to_validate():
    """Guard against the glob above quietly matching nothing and the module
    passing while checking no artifact at all."""
    assert ARTIFACTS, "no committed ConfigDB artifacts found to validate"


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_committed_config_validates_without_errors(path):
    config = json.loads(path.read_text())
    result = validate_config(config)
    assert result.errors == [], "\n".join(
        f"{e.table}.{e.path}: {e.message}" for e in result.errors
    )
    assert result.valid
