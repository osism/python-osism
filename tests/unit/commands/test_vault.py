# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism vault`` commands."""

from unittest.mock import MagicMock, mock_open, patch

import pytest

from osism.commands import vault


def _make_view():
    return vault.View(MagicMock(), MagicMock())


# --- View.take_action ---


def test_view_invokes_ansible_vault_for_encrypted_file(tmp_path):
    path = tmp_path / "secrets.yml"
    path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        _make_view().take_action(parsed_args)

    mock_call.assert_called_once_with(
        ["/usr/local/bin/ansible-vault", "view", str(path)]
    )


def test_view_prints_plain_content_with_warning(tmp_path, capsys, loguru_logs):
    path = tmp_path / "plain.yml"
    path.write_text("key: value\n")
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        _make_view().take_action(parsed_args)

    mock_call.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == "key: value\n"
    warnings = [r for r in loguru_logs if r["level"] == "WARNING"]
    assert any("not vault-encrypted" in r["message"] for r in warnings)


def test_view_resolves_relative_path_against_opt_configuration():
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args(["environments/openstack/secure.yml"])

    open_mock = mock_open(read_data=b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    with patch("osism.commands.vault.open", open_mock, create=True), patch(
        "osism.commands.vault.subprocess.call"
    ) as mock_call:
        _make_view().take_action(parsed_args)

    expected = "/opt/configuration/environments/openstack/secure.yml"
    open_mock.assert_called_once_with(expected, "rb")
    mock_call.assert_called_once_with(
        ["/usr/local/bin/ansible-vault", "view", expected]
    )


def test_view_reports_missing_file(tmp_path, loguru_logs):
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([str(tmp_path / "missing.yml")])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        rc = _make_view().take_action(parsed_args)

    assert rc == 1
    mock_call.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("File not found" in r["message"] for r in errors)


def test_view_reports_permission_error(tmp_path, loguru_logs):
    path = tmp_path / "secrets.yml"
    path.write_bytes(b"key: value\n")
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    open_mock = MagicMock(side_effect=PermissionError("denied"))
    with patch("osism.commands.vault.open", open_mock, create=True), patch(
        "osism.commands.vault.subprocess.call"
    ) as mock_call:
        rc = _make_view().take_action(parsed_args)

    assert rc == 1
    mock_call.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Permission denied" in r["message"] for r in errors)


@pytest.mark.parametrize(
    "header",
    [b"$ANSIBLE_VAULT;1.1;AES256", b"$ANSIBLE_VAULT;1.2;AES256;dev"],
)
def test_view_invokes_ansible_vault_for_vault_variants(tmp_path, header):
    path = tmp_path / "secrets.yml"
    path.write_bytes(header + b"\n3033...\n")
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        _make_view().take_action(parsed_args)

    mock_call.assert_called_once_with(
        ["/usr/local/bin/ansible-vault", "view", str(path)]
    )


# --- Decrypt.take_action ---


def test_decrypt_invokes_ansible_vault_without_shell(tmp_path):
    path = tmp_path / "secrets.yml"
    path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    cmd = vault.Decrypt(MagicMock(), MagicMock())
    parser = cmd.get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        cmd.take_action(parsed_args)

    mock_call.assert_called_once_with(
        ["/usr/local/bin/ansible-vault", "decrypt", str(path)]
    )
