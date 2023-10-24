# SPDX-License-Identifier: Apache-2.0

__all__ = ["__version__"]

import pbr.version

version_info = pbr.version.VersionInfo("osism")
# We have a circular import problem when we first run python setup.py sdist
# It's harmless, so deflect it.
try:
    __version__ = version_info.version_string()
except AttributeError:
    __version__ = None
