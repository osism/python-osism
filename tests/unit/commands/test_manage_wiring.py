# SPDX-License-Identifier: Apache-2.0

"""Wiring tests: verify each Image* command passes the correct validator to fetch_text."""

from unittest.mock import MagicMock, patch

from osism.commands import manage
from osism.commands.manage import _is_sha256, _validate_marker


def _stub_docker(release: str = "2024.1") -> MagicMock:
    docker_client = MagicMock()
    container = MagicMock()
    container.labels = {"de.osism.release.openstack": release}
    docker_client.containers.get.return_value = container
    return docker_client


def _stub_args(**overrides) -> MagicMock:
    args = MagicMock()
    args.no_wait = True  # short-circuit handle_task waiting
    args.cloud = "octavia"
    args.base_url = "https://example.com/octavia/"
    args.dry_run = False
    args.tag = None
    args.filter = None
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def test_w1_octavia_wires_validators_to_call_sites():
    cmd = manage.ImageOctavia(MagicMock(), MagicMock())
    args = _stub_args()

    fake_marker_body = "2026-04-12 octavia-amphora-haproxy-2024.1.20260412.qcow2"
    fake_checksum_body = ("a" * 64) + "  octavia-amphora-haproxy-2024.1.20260412.qcow2"

    with patch.object(manage.utils, "check_task_lock_and_exit"), patch(
        "docker.from_env", return_value=_stub_docker(release="2024.1")
    ), patch("osism.commands.manage.fetch_text") as mock_fetch, patch(
        "osism.tasks.openstack.image_manager"
    ) as mock_im, patch(
        "osism.tasks.handle_task"
    ) as mock_handle:
        mock_fetch.side_effect = [fake_marker_body, fake_checksum_body]
        mock_im.si.return_value.apply_async.return_value = MagicMock(task_id="x")
        mock_handle.return_value = 0

        cmd.take_action(args)

    assert mock_fetch.call_count == 2
    marker_call, checksum_call = mock_fetch.call_args_list

    # Marker fetch
    assert marker_call.args[0] == "https://example.com/octavia/last-2024.1"
    assert marker_call.kwargs["validate"] is _validate_marker

    # Checksum fetch
    assert checksum_call.args[0].endswith(".CHECKSUM")
    assert "octavia-amphora-haproxy-2024.1.20260412.qcow2" in checksum_call.args[0]
    assert checksum_call.kwargs["validate"] is _is_sha256


def test_w2_clusterapi_wires_validators_to_call_sites():
    cmd = manage.ImageClusterapi(MagicMock(), MagicMock())
    args = _stub_args(
        cloud="admin",
        base_url="https://example.com/capi/",
        filter="1.33",  # restrict to a single release for a deterministic call count
    )

    fake_marker_body = "2026-04-12 ubuntu-2404-kube-v1.33.1.qcow2"
    fake_checksum_body = ("a" * 64) + "  ubuntu-2404-kube-v1.33.1.qcow2"

    with patch.object(manage.utils, "check_task_lock_and_exit"), patch(
        "osism.commands.manage.fetch_text"
    ) as mock_fetch, patch("osism.tasks.openstack.image_manager") as mock_im, patch(
        "osism.tasks.handle_task"
    ) as mock_handle:
        mock_fetch.side_effect = [fake_marker_body, fake_checksum_body]
        mock_im.si.return_value.apply_async.return_value = MagicMock(task_id="x")
        mock_handle.return_value = 0

        cmd.take_action(args)

    assert mock_fetch.call_count == 2
    marker_call, checksum_call = mock_fetch.call_args_list
    assert marker_call.args[0] == "https://example.com/capi/last-1.33"
    assert marker_call.kwargs["validate"] is _validate_marker
    assert checksum_call.args[0].endswith(".CHECKSUM")
    assert checksum_call.kwargs["validate"] is _is_sha256


def test_w3_clusterapi_gardener_wires_validators_to_call_sites():
    cmd = manage.ImageClusterapiGardener(MagicMock(), MagicMock())
    args = _stub_args(
        cloud="admin",
        base_url="https://example.com/capi/",
        filter="1.33",
    )

    fake_marker_body = "2026-04-12 ubuntu-2404-kube-v1.33.1.qcow2"
    fake_checksum_body = ("a" * 64) + "  ubuntu-2404-kube-v1.33.1.qcow2"

    with patch.object(manage.utils, "check_task_lock_and_exit"), patch(
        "osism.commands.manage.fetch_text"
    ) as mock_fetch, patch("osism.tasks.openstack.image_manager") as mock_im, patch(
        "osism.tasks.handle_task"
    ) as mock_handle:
        mock_fetch.side_effect = [fake_marker_body, fake_checksum_body]
        mock_im.si.return_value.apply_async.return_value = MagicMock(task_id="x")
        mock_handle.return_value = 0

        cmd.take_action(args)

    assert mock_fetch.call_count == 2
    marker_call, checksum_call = mock_fetch.call_args_list
    assert marker_call.args[0] == "https://example.com/capi/last-1.33-gardener"
    assert marker_call.kwargs["validate"] is _validate_marker
    assert checksum_call.kwargs["validate"] is _is_sha256


def test_w4_gardenlinux_wires_sha256_validator():
    cmd = manage.ImageGardenlinux(MagicMock(), MagicMock())
    args = _stub_args(
        cloud="admin",
        base_url="https://example.com/gardenlinux/",
        filter="1877.7",  # one entry from SUPPORTED_GARDENLINUX_VERSIONS
    )

    fake_checksum_body = ("a" * 64) + "  openstack-gardener_prod-amd64-1877.7.qcow2"

    with patch.object(manage.utils, "check_task_lock_and_exit"), patch(
        "osism.commands.manage.fetch_text"
    ) as mock_fetch, patch("osism.tasks.openstack.image_manager") as mock_im, patch(
        "osism.tasks.handle_task"
    ) as mock_handle:
        mock_fetch.return_value = fake_checksum_body
        mock_im.si.return_value.apply_async.return_value = MagicMock(task_id="x")
        mock_handle.return_value = 0

        cmd.take_action(args)

    assert mock_fetch.call_count == 1
    (call,) = mock_fetch.call_args_list
    assert call.args[0].endswith(".qcow2.sha256")
    assert "1877.7" in call.args[0]
    assert call.kwargs["validate"] is _is_sha256
