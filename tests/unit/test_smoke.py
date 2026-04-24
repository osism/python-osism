# SPDX-License-Identifier: Apache-2.0

import osism


def test_package_importable():
    assert osism is not None


def test_package_has_version_attribute():
    assert hasattr(osism, "__version__")
    assert isinstance(osism.__version__, str)
    assert osism.__version__
