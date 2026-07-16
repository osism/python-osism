# SPDX-License-Identifier: Apache-2.0

"""Fixtures shared across the ``osism.tasks.openstack`` unit test modules.

The suite is split into ``test_openstack_env.py`` (cloud env/connection
helpers), ``test_openstack_baremetal.py`` (baremetal + NetBox getters and the
thin Celery task wrappers) and ``test_openstack_managers.py`` (the manager
tasks). Only fixtures used by more than one of those modules live here;
module-specific fixtures stay in their module.
"""

import pytest


@pytest.fixture
def mock_os(mocker):
    """Replace the module-level ``os`` binding so no test touches the real
    filesystem or working directory."""
    fake_os = mocker.patch("osism.tasks.openstack.os")
    fake_os.getcwd.return_value = "/orig"
    fake_os.path.exists.return_value = False
    return fake_os
