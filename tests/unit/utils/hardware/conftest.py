# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Return a loader for the collector documents in ``fixtures/``."""

    def _load(name):
        return json.loads((FIXTURES / name).read_text())

    return _load
