# SPDX-License-Identifier: Apache-2.0

"""Tests for OpenStack release resolution.

``osism.data.releases`` answers one question -- which OpenStack release is
deployed -- from three sources in a fixed order, the last of them the versions
file the kolla-ansible container publishes under /interface. These tests
characterize the parser, the resolution order, and the distinct failures the
caller has to render differently (missing file, unreadable file, missing key,
malformed file, unparseable value).
"""

import os

import pytest

from osism.data import releases

# parse_release


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2025.1", (2025, 1)),
        ("2026.1", (2026, 1)),
        ("2024.2", (2024, 2)),
        (" 2025.1 ", (2025, 1)),
    ],
)
def test_parse_release_accepts_releases(value, expected):
    assert releases.parse_release(value) == expected


def test_parse_release_accepts_yaml_float():
    """YAML parses an unquoted ``openstack_version: 2024.2`` as a float."""
    assert releases.parse_release(2024.2) == (2024, 2)


@pytest.mark.parametrize("value", ["master", "2025", "", "stable/2025.1", "v2025.1"])
def test_parse_release_rejects_non_releases(value):
    with pytest.raises(releases.ReleaseUnparseable) as excinfo:
        releases.parse_release(value)

    assert "expected a release like 2025.1" in str(excinfo.value)
    assert repr(value) in str(excinfo.value)


def test_parse_release_orders_as_tuples():
    assert releases.parse_release("2025.2") > releases.parse_release("2025.1")
    assert releases.parse_release("2026.1") > releases.parse_release("2025.2")


# format_release


@pytest.mark.parametrize(
    "release,expected",
    [
        ((2025, 1), "2025.1"),
        ((2026, 1), "2026.1"),
        ((2024, 2), "2024.2"),
    ],
)
def test_format_release_renders_year_dot_minor(release, expected):
    assert releases.format_release(release) == expected


@pytest.mark.parametrize(
    "value",
    ["2025.1", "2026.1", "2024.2", 2024.2],
)
def test_format_release_round_trips_with_parse_release(value):
    release = releases.parse_release(value)

    assert releases.parse_release(releases.format_release(release)) == release


# openstack_release resolution order


def test_openstack_release_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSTACK_VERSION", "2024.1")
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(tmp_path / "absent.yml"))

    assert releases.openstack_release("2026.1") == (2026, 1)


def test_openstack_release_env_beats_file(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: 2024.1\n")
    monkeypatch.setenv("OPENSTACK_VERSION", "2026.1")
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    assert releases.openstack_release() == (2026, 1)


def test_openstack_release_reads_versions_file(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: 2026.1\nother_key: value\n")
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    assert releases.openstack_release() == (2026, 1)


def test_openstack_release_reads_versions_file_as_published(monkeypatch, tmp_path):
    """The file as the kolla-ansible container publishes it.

    Two shapes in it would break a naive reader: openstack_version is quoted,
    so it arrives as a string and not as the float an unquoted 2024.1 would
    become, and the keys beside it hold un-rendered Jinja that must not be
    mistaken for anything but opaque text.
    """
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text(
        'openstack_version: "2024.1"\n'
        'kolla_ansible_version: "{{ openstack_version }}"\n'
        'kolla_image_version: "{{ openstack_version }}"\n'
        'openstack_release: "{{ openstack_version }}"\n'
    )
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    assert releases.openstack_release() == (2024, 1)


def test_openstack_release_empty_env_falls_through(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: 2026.1\n")
    monkeypatch.setenv("OPENSTACK_VERSION", "")
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    assert releases.openstack_release() == (2026, 1)


# openstack_release failures


def test_openstack_release_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "absent.yml"
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(missing))

    with pytest.raises(releases.ReleaseUndetermined) as excinfo:
        releases.openstack_release()

    assert str(missing) in str(excinfo.value)
    assert "not found" in str(excinfo.value)


def test_openstack_release_unreadable_file(monkeypatch, tmp_path):
    """A file that exists but cannot be opened is still a ReleaseError.

    Testing for existence and then opening leaves a window -- the file can be
    unreadable, a directory, or gone by the time the open runs -- and an
    OSError escaping here would reach the operator as a traceback instead of
    the release-resolution diagnostic the caller renders.
    """
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: 2025.1\n")
    versions.chmod(0o000)
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    try:
        if os.access(str(versions), os.R_OK):
            pytest.skip("running with privileges that ignore file permissions")

        with pytest.raises(releases.ReleaseUndetermined) as excinfo:
            releases.openstack_release()
    finally:
        versions.chmod(0o644)

    assert str(versions) in str(excinfo.value)
    assert "could not be read" in str(excinfo.value)


def test_openstack_release_versions_path_is_a_directory(monkeypatch, tmp_path):
    """The same window, in the form that does not depend on the test's uid."""
    versions = tmp_path / "kolla-ansible.yml"
    versions.mkdir()
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUndetermined) as excinfo:
        releases.openstack_release()

    assert str(versions) in str(excinfo.value)
    assert "could not be read" in str(excinfo.value)


def test_openstack_release_missing_key(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("other_key: value\n")
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUndetermined) as excinfo:
        releases.openstack_release()

    assert "openstack_version not set" in str(excinfo.value)
    assert str(versions) in str(excinfo.value)


def test_openstack_release_empty_file(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("")
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUndetermined):
        releases.openstack_release()


def test_openstack_release_invalid_yaml(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: [unclosed\n")
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUndetermined) as excinfo:
        releases.openstack_release()

    assert "not valid YAML" in str(excinfo.value)


@pytest.mark.parametrize(
    "content,label",
    [
        ("- a\n- b\n", "a list"),
        ("just a scalar\n", "a bare scalar"),
        # Falsy non-mappings. An "or {}" on the load turns each of these into
        # an empty mapping, which passes the isinstance check below and is
        # then reported as an unset key rather than as a malformed file.
        ("[]\n", "an empty list"),
        ("false\n", "a false scalar"),
        ("0\n", "a zero scalar"),
        ("''\n", "an empty string"),
    ],
)
def test_openstack_release_yaml_that_is_not_a_mapping(
    monkeypatch, tmp_path, content, label
):
    """Well-formed YAML need not be a mapping.

    A list or a bare scalar parses without error, and looking a key up on it
    would raise AttributeError -- escaping the ReleaseError diagnostic that
    callers render.
    """
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text(content)
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUndetermined) as excinfo:
        releases.openstack_release()

    assert "does not contain a YAML mapping" in str(excinfo.value)


def test_openstack_release_unparseable_value(monkeypatch, tmp_path):
    versions = tmp_path / "kolla-ansible.yml"
    versions.write_text("openstack_version: master\n")
    monkeypatch.delenv("OPENSTACK_VERSION", raising=False)
    monkeypatch.setattr(releases, "VERSIONS_FILE", str(versions))

    with pytest.raises(releases.ReleaseUnparseable):
        releases.openstack_release()


def test_undetermined_and_unparseable_are_both_release_errors():
    assert issubclass(releases.ReleaseUndetermined, releases.ReleaseError)
    assert issubclass(releases.ReleaseUnparseable, releases.ReleaseError)


# import-time safety


def test_import_does_not_read_environment():
    """A bad OPENSTACK_VERSION must break one command, not every import.

    ``osism/settings.py`` and ``osism/utils/__init__.py`` parse env vars at
    import, so a typo there takes down the whole CLI. This module must not.

    This characterizes the environment half only: a bad ``OPENSTACK_VERSION``
    must not raise on import. It says nothing about filesystem access at
    import time -- there is no environment variable to poison the way
    ``OPENSTACK_VERSION`` poisons the environment half, so that half is not
    exercised here.

    The subprocess also prints ``__file__`` so the assertion below pins down
    which copy of the module was actually imported: run from a different
    working directory, ``python -c`` can silently resolve an installed
    package instead of this worktree's source, and a stale copy would make
    this test pass without proving anything about the code under review.
    """
    import os
    import subprocess
    import sys

    environment = dict(os.environ, OPENSTACK_VERSION="not-a-release")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import osism.data.releases as r; print(r.__file__)",
        ],
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    expected_file = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "osism", "data", "releases.py"
        )
    )
    imported_file = os.path.abspath(result.stdout.strip())
    assert imported_file == expected_file
