# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism sync`` commands.

``Facts``, ``CephKeys`` and ``Sonic`` are thin Celery dispatchers: they must
consult the task lock before scheduling anything, forward the right playbook
or conductor arguments and propagate ``handle_task``'s exit code. ``Versions``
syncs Kolla image versions from an SBOM container image into the configuration
repository; those tests cover the SBOM image derivation, the release lookup
against the release repository, the skopeo/OCI extraction and the rendering of
``versions.yml``.
"""

import contextlib
import io
import json
import subprocess
import tarfile
from unittest.mock import MagicMock, patch

import pytest
import requests
from yaml import YAMLError

from osism.commands import sync

from ._helpers import assert_not_called_before_lock_check, make_command, parse_args

# --- Facts.take_action ---


@pytest.mark.parametrize("rc", [0, 2])
def test_facts_schedules_gather_facts_and_returns_rc(rc):
    cmd, parsed_args = parse_args(sync.Facts, [])

    with patch(
        "osism.commands.sync.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.tasks.ansible.run.delay") as mock_delay, patch(
        "osism.tasks.handle_task", return_value=rc
    ) as mock_handle:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        result = cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with(
        "generic", "gather-facts", [], auto_release_time=3600
    )
    mock_handle.assert_called_once_with(mock_delay.return_value)
    assert result == rc


# --- CephKeys.take_action ---


def test_ceph_keys_schedules_copy_ceph_keys_and_waits(loguru_logs):
    cmd, parsed_args = parse_args(sync.CephKeys, [])

    with patch(
        "osism.commands.sync.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.tasks.ansible.run.delay") as mock_delay, patch(
        "osism.tasks.handle_task", return_value=0
    ) as mock_handle:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        result = cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with(
        "manager", "copy-ceph-keys", [], auto_release_time=3600
    )
    mock_handle.assert_called_once_with(mock_delay.return_value, True)
    assert result == 0
    assert any(
        "(sync ceph-keys) started" in record["message"] for record in loguru_logs
    )


def test_ceph_keys_no_wait_disables_waiting():
    cmd, parsed_args = parse_args(sync.CephKeys, ["--no-wait"])

    with patch("osism.commands.sync.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.ansible.run.delay"
    ) as mock_delay, patch("osism.tasks.handle_task", return_value=0) as mock_handle:
        cmd.take_action(parsed_args)

    mock_handle.assert_called_once_with(mock_delay.return_value, False)


# --- Sonic.take_action ---


def _run_sonic(args):
    cmd, parsed_args = parse_args(sync.Sonic, args)

    with patch(
        "osism.commands.sync.utils.check_task_lock_and_exit"
    ) as mock_check, patch(
        "osism.tasks.conductor.sync_sonic.delay"
    ) as mock_delay, patch(
        "osism.tasks.handle_task", return_value=0
    ) as mock_handle:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        result = cmd.take_action(parsed_args)

    return result, mock_check, mock_delay, mock_handle


def test_sonic_syncs_specific_device_and_logs_device_name(loguru_logs):
    result, mock_check, mock_delay, mock_handle = _run_sonic(["switch1"])

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with("switch1", True)
    mock_handle.assert_called_once_with(mock_delay.return_value, wait=True)
    assert result == 0
    assert any(
        "(sync sonic for device switch1) started" in record["message"]
        for record in loguru_logs
    )


def test_sonic_without_device_logs_generic_message(loguru_logs):
    _, _, mock_delay, _ = _run_sonic([])

    mock_delay.assert_called_once_with(None, True)
    assert any("(sync sonic) started" in record["message"] for record in loguru_logs)
    assert not any("for device" in record["message"] for record in loguru_logs)


def test_sonic_no_diff_and_no_wait_are_forwarded():
    _, _, mock_delay, mock_handle = _run_sonic(["switch1", "--no-diff", "--no-wait"])

    mock_delay.assert_called_once_with("switch1", False)
    mock_handle.assert_called_once_with(mock_delay.return_value, wait=False)


# --- Versions._get_kolla_version_from_release ---


def _release_response(text):
    response = MagicMock()
    response.text = text
    return response


def test_get_kolla_version_from_release_returns_version_from_base_yml():
    cmd = make_command(sync.Versions)
    response = _release_response('docker_images:\n  kolla: "0.20250928.0"\n')

    with patch("requests.get", return_value=response) as mock_get:
        version = cmd._get_kolla_version_from_release(
            "9.4.0", "https://example.com/release"
        )

    mock_get.assert_called_once_with(
        "https://example.com/release/9.4.0/base.yml", timeout=30
    )
    response.raise_for_status.assert_called_once_with()
    assert version == "0.20250928.0"


def test_get_kolla_version_from_release_raises_on_http_error():
    cmd = make_command(sync.Versions)
    response = MagicMock()
    response.raise_for_status.side_effect = requests.exceptions.RequestException("404")

    with patch("requests.get", return_value=response):
        with pytest.raises(RuntimeError, match="Failed to fetch release configuration"):
            cmd._get_kolla_version_from_release("9.4.0", "https://example.com/release")


def test_get_kolla_version_from_release_raises_on_invalid_yaml():
    cmd = make_command(sync.Versions)
    response = _release_response("\t")

    with patch("requests.get", return_value=response):
        with pytest.raises(RuntimeError, match="Failed to parse release configuration"):
            cmd._get_kolla_version_from_release("9.4.0", "https://example.com/release")


def test_get_kolla_version_from_release_raises_when_kolla_version_missing():
    cmd = make_command(sync.Versions)
    response = _release_response("docker_images: {}\n")

    with patch("requests.get", return_value=response):
        with pytest.raises(RuntimeError, match="Kolla version not found"):
            cmd._get_kolla_version_from_release("9.4.0", "https://example.com/release")


# --- Versions.take_action / _sync_kolla_versions ---


def _run_versions(
    tmp_path, args, *, sbom=None, extract=None, release=None, config=None
):
    """Run ``sync versions`` with the SBOM extraction and release lookup stubbed."""
    config_path = str(config) if config is not None else str(tmp_path)
    cmd, parsed_args = parse_args(
        sync.Versions, ["--configuration-path", config_path, *args]
    )

    extract_kwargs = extract or {"return_value": sbom if sbom is not None else {}}
    release_kwargs = release or {"return_value": "0.20250928.0"}

    with patch.object(
        sync.Versions, "_extract_sbom_with_skopeo", **extract_kwargs
    ) as mock_extract, patch.object(
        sync.Versions, "_get_kolla_version_from_release", **release_kwargs
    ) as mock_release:
        result = cmd.take_action(parsed_args)

    return result, mock_extract, mock_release


def test_versions_release_derives_sbom_image_from_release_repository(tmp_path):
    result, mock_extract, mock_release = _run_versions(
        tmp_path,
        [
            "--release",
            "9.4.0",
            "--release-repository-url",
            "https://example.com/release/",
            "--dry-run",
        ],
    )

    # A trailing slash on the repository URL is stripped before the lookup.
    mock_release.assert_called_once_with("9.4.0", "https://example.com/release")
    mock_extract.assert_called_once_with(
        "registry.osism.cloud/kolla/release/sbom:0.20250928.0"
    )
    assert result == 0


def test_versions_release_lookup_failure_returns_error(tmp_path, loguru_logs):
    result, mock_extract, _ = _run_versions(
        tmp_path,
        ["--release", "9.4.0", "--dry-run"],
        release={"side_effect": RuntimeError("Failed to fetch release configuration")},
    )

    assert result == 1
    mock_extract.assert_not_called()
    assert any(
        record["level"] == "ERROR"
        and "Failed to fetch release configuration" in record["message"]
        for record in loguru_logs
    )


def test_versions_date_tag_uses_release_sbom_image(tmp_path):
    _, mock_extract, _ = _run_versions(
        tmp_path, ["--openstack-version", "0.20251128.0", "--dry-run"]
    )
    mock_extract.assert_called_once_with(
        "registry.osism.cloud/kolla/release/sbom:0.20251128.0"
    )


def test_versions_v_prefixed_date_tag_is_stripped(tmp_path):
    _, mock_extract, _ = _run_versions(
        tmp_path, ["--openstack-version", "v0.20251128.0", "--dry-run"]
    )
    mock_extract.assert_called_once_with(
        "registry.osism.cloud/kolla/release/sbom:0.20251128.0"
    )


def test_versions_openstack_version_uses_plain_sbom_image(tmp_path):
    _, mock_extract, _ = _run_versions(
        tmp_path, ["--openstack-version", "2025.1", "--dry-run"]
    )
    mock_extract.assert_called_once_with("registry.osism.cloud/kolla/sbom:2025.1")


def test_versions_explicit_sbom_image_is_used_verbatim(tmp_path):
    _, mock_extract, mock_release = _run_versions(
        tmp_path,
        [
            "--sbom-image",
            "example.com/custom/sbom:1.2.3",
            "--release",
            "9.4.0",
            "--dry-run",
        ],
    )
    mock_extract.assert_called_once_with("example.com/custom/sbom:1.2.3")
    mock_release.assert_not_called()


def test_versions_missing_configuration_path_returns_error(tmp_path, loguru_logs):
    result, mock_extract, _ = _run_versions(tmp_path, [], config=tmp_path / "missing")

    assert result == 1
    mock_extract.assert_not_called()
    assert any(
        record["level"] == "ERROR"
        and "Configuration path does not exist" in record["message"]
        for record in loguru_logs
    )


def test_versions_extraction_runtime_error_returns_error(tmp_path, loguru_logs):
    result, _, _ = _run_versions(
        tmp_path,
        ["--dry-run"],
        extract={"side_effect": RuntimeError("skopeo copy failed: denied")},
    )

    assert result == 1
    assert any(
        record["level"] == "ERROR" and "skopeo copy failed" in record["message"]
        for record in loguru_logs
    )


def test_versions_extraction_yaml_error_returns_error(tmp_path, loguru_logs):
    result, _, _ = _run_versions(
        tmp_path,
        ["--dry-run"],
        extract={"side_effect": YAMLError("bad yaml")},
    )

    assert result == 1
    assert any(
        record["level"] == "ERROR" and "Failed to parse SBOM YAML" in record["message"]
        for record in loguru_logs
    )


def test_versions_sbom_openstack_version_overrides_cli_value(tmp_path, capsys):
    result, _, _ = _run_versions(
        tmp_path,
        ["--openstack-version", "2025.1", "--dry-run"],
        sbom={"openstack_version": "2024.2", "versions": {}},
    )

    out = capsys.readouterr().out
    assert result == 0
    assert 'kolla_aodh_version: "2024.2"' in out
    assert '"2025.1"' not in out


def test_versions_dry_run_prints_rendered_versions_without_writing(tmp_path, capsys):
    result, _, _ = _run_versions(
        tmp_path,
        ["--dry-run"],
        sbom={"openstack_version": "2025.1", "versions": {"aodh": "20.0.1"}},
    )

    out = capsys.readouterr().out
    assert result == 0
    assert 'kolla_aodh_version: "20.0.1"' in out
    assert 'kolla_barbican_version: "2025.1"' in out
    assert not (tmp_path / "environments").exists()


def test_versions_writes_versions_yml_and_creates_directories(tmp_path, loguru_logs):
    result, _, _ = _run_versions(
        tmp_path,
        [],
        sbom={"openstack_version": "2025.1", "versions": {"aodh": "20.0.1"}},
    )

    output_path = tmp_path / "environments" / "kolla" / "versions.yml"
    assert result == 0
    assert output_path.exists()
    content = output_path.read_text()
    assert content.startswith("---")
    assert 'kolla_aodh_version: "20.0.1"' in content
    assert 'kolla_barbican_version: "2025.1"' in content
    assert any(
        record["level"] == "SUCCESS" and "Versions written to" in record["message"]
        for record in loguru_logs
    )


# --- Versions._extract_sbom_with_skopeo ---


def _tar_bytes(files):
    """Build an uncompressed tar archive with the given ``{name: content}``."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _build_oci_layout(tmp_path, layer_blobs):
    """Create the OCI layout skopeo would have produced under ``tmp_path``.

    The code only ever splits digests on ``:`` to derive blob file names, so
    placeholder digests are sufficient.
    """
    blobs = tmp_path / "oci" / "blobs" / "sha256"
    blobs.mkdir(parents=True)

    layers = []
    for index, blob in enumerate(layer_blobs):
        (blobs / f"layer{index}").write_bytes(blob)
        layers.append({"digest": f"sha256:layer{index}"})

    (blobs / "manifest").write_text(json.dumps({"layers": layers}))
    (tmp_path / "oci" / "index.json").write_text(
        json.dumps({"manifests": [{"digest": "sha256:manifest"}]})
    )


@contextlib.contextmanager
def _fake_tempdir(path):
    yield str(path)


def _extract_sbom(tmp_path, *, run_kwargs=None):
    """Call ``_extract_sbom_with_skopeo`` against a fake OCI layout."""
    cmd = make_command(sync.Versions)

    with patch(
        "osism.commands.sync.tempfile.TemporaryDirectory",
        return_value=_fake_tempdir(tmp_path),
    ), patch("osism.commands.sync.subprocess.run", **(run_kwargs or {})) as mock_run:
        sbom = cmd._extract_sbom_with_skopeo("registry.example.com/sbom:1")

    return sbom, mock_run


def test_extract_sbom_returns_parsed_images_yml(tmp_path):
    layer = _tar_bytes({"images.yml": 'versions:\n  aodh: "1.2.3"\n'})
    _build_oci_layout(tmp_path, [layer])

    sbom, mock_run = _extract_sbom(tmp_path)

    assert sbom == {"versions": {"aodh": "1.2.3"}}
    mock_run.assert_called_once()
    command = mock_run.call_args[0][0]
    assert command[:3] == ["skopeo", "copy", "docker://registry.example.com/sbom:1"]
    assert command[3] == f"oci:{tmp_path / 'oci'}:latest"
    assert mock_run.call_args[1]["check"] is True


def test_extract_sbom_skopeo_failure_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="skopeo copy failed: denied"):
        _extract_sbom(
            tmp_path,
            run_kwargs={
                "side_effect": subprocess.CalledProcessError(
                    1, ["skopeo"], stderr="denied"
                )
            },
        )


def test_extract_sbom_missing_skopeo_binary_raises_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="skopeo not found"):
        _extract_sbom(tmp_path, run_kwargs={"side_effect": FileNotFoundError})


def test_extract_sbom_skips_layers_that_are_not_tar_archives(tmp_path):
    layers = [
        b"this is not a tar archive",
        _tar_bytes({"sbom/images.yml": "versions: {}\n"}),
    ]
    _build_oci_layout(tmp_path, layers)

    sbom, _ = _extract_sbom(tmp_path)

    assert sbom == {"versions": {}}


def test_extract_sbom_without_images_yml_raises_runtime_error(tmp_path):
    _build_oci_layout(tmp_path, [_tar_bytes({"other.yml": "foo: bar\n"})])

    with pytest.raises(RuntimeError, match="images.yml not found"):
        _extract_sbom(tmp_path)
