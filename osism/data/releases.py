# SPDX-License-Identifier: Apache-2.0

"""Resolution of the OpenStack release a deployment runs.

Collections deploy a few roles only on some releases -- see the ``since`` and
``until`` bounds on ``osism.data.enums.Role`` -- so expanding one needs to know
which release is deployed.

The value is read at call time, never at import. ``osism/settings.py`` and
``osism/utils/__init__.py`` parse environment variables during module import,
which turns a single typo into a CLI that cannot start at all; this module does
not repeat that.
"""

import os
import re

import yaml

# The kolla-ansible container copies its own group_vars/all/versions.yml here
# when it starts, so the file describes the containers that are actually
# deployed and is present for a stable release as well as for latest. Reading
# /interface/versions has precedent in tasks/__init__.py, which takes container
# versions from the same directory.
#
# The manager configuration is deliberately not a source. It carries
# openstack_version only on a latest deployment: for a stable release the
# OpenStack and Ceph versions follow manager_version, and the key is stripped
# from environments/manager/configuration.yml -- so it is missing on exactly
# the deployments that pin a release.
VERSIONS_FILE = "/interface/versions/kolla-ansible.yml"

# OpenStack releases are YYYY.N. Note YAML parses an unquoted 2024.2 as a float,
# so parse_release stringifies before matching.
_RELEASE_RE = re.compile(r"^(\d{4})\.(\d+)$")


class ReleaseError(Exception):
    """Base class for failures to establish the OpenStack release."""


class ReleaseUndetermined(ReleaseError):
    """No source supplied a release.

    The message is a *cause fragment* ("... not found."), meant to be appended
    to a sentence naming what needed the release.
    """


class ReleaseUnparseable(ReleaseError):
    """A source supplied something that is not a release.

    The message is a complete sentence and is printed as-is.
    """


def parse_release(value):
    """Return ``value`` as a ``(year, minor)`` tuple, e.g. ``(2025, 1)``.

    Tuples compare in release order, so callers can use ``<`` and ``>``.
    """
    match = _RELEASE_RE.match(str(value).strip())
    if not match:
        raise ReleaseUnparseable(
            f"Could not parse OpenStack release {value!r} "
            f"(expected a release like 2025.1)."
        )

    return int(match.group(1)), int(match.group(2))


def format_release(release):
    """Return ``release`` (a ``(year, minor)`` tuple) as ``"year.minor"``.

    Inverse of ``parse_release``.
    """
    return f"{release[0]}.{release[1]}"


def openstack_release(override=None):
    """Return the deployed OpenStack release as a ``(year, minor)`` tuple.

    Sources, in order: ``override`` (the ``--openstack-version`` argument), the
    ``OPENSTACK_VERSION`` environment variable, and ``openstack_version`` in
    ``VERSIONS_FILE``, which the kolla-ansible container publishes for every
    deployment.

    Raises ``ReleaseUnparseable`` if a source supplied a value that is not a
    release, and ``ReleaseUndetermined`` if no source supplied one at all.
    """
    if override:
        return parse_release(override)

    from_environment = os.environ.get("OPENSTACK_VERSION")
    if from_environment:
        return parse_release(from_environment)

    # Opened without testing for existence first: a stat that says the file is
    # there is no promise that the open succeeds, and every way it can fail --
    # gone since, unreadable, a directory, /interface not mounted -- has to
    # reach the caller as a ReleaseError anyway.
    try:
        with open(VERSIONS_FILE) as fp:
            versions = yaml.safe_load(fp)
    except FileNotFoundError:
        raise ReleaseUndetermined(f"{VERSIONS_FILE} not found.")
    except OSError as exc:
        raise ReleaseUndetermined(f"{VERSIONS_FILE} could not be read: {exc.strerror}.")
    except yaml.YAMLError:
        raise ReleaseUndetermined(f"{VERSIONS_FILE} is not valid YAML.")

    # An empty file parses to None, which is the one non-mapping that means
    # nothing is published rather than that the file is malformed.
    if versions is None:
        versions = {}

    # Well-formed YAML is not necessarily a mapping: a list or a bare scalar
    # parses fine and would turn the lookup below into an AttributeError,
    # escaping the diagnostic this function exists to produce. Falsy ones
    # ([], false, 0, "") are caught here too, so they are reported as the
    # malformed file they are and not as an unset key.
    if not isinstance(versions, dict):
        raise ReleaseUndetermined(f"{VERSIONS_FILE} does not contain a YAML mapping.")

    value = versions.get("openstack_version")
    if not value:
        raise ReleaseUndetermined(f"openstack_version not set in {VERSIONS_FILE}.")

    return parse_release(value)
