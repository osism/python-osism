# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism vault`` commands."""

from unittest.mock import MagicMock, mock_open, patch

import pytest
from cryptography.fernet import Fernet

from osism.commands import vault


def _make_view():
    return vault.View(MagicMock(), MagicMock())


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client wherever the vault commands resolve it.

    ``osism.utils.redis`` is a lazily-initialised module attribute that opens
    a real connection on first access, so patch both the attribute and its
    initialiser to keep the test offline.
    """
    client = MagicMock()
    with patch("osism.utils._init_redis", return_value=client), patch(
        "osism.commands.vault.utils.redis", client, create=True
    ):
        yield client


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


def test_view_requires_path(loguru_logs):
    parser = _make_view().get_parser("test")
    parsed_args = parser.parse_args([])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        rc = _make_view().take_action(parsed_args)

    assert rc == 1
    mock_call.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("No path" in r["message"] for r in errors)


# --- Decrypt.take_action ---


def test_decrypt_requires_path(loguru_logs):
    cmd = vault.Decrypt(MagicMock(), MagicMock())
    parser = cmd.get_parser("test")
    parsed_args = parser.parse_args([])

    with patch("osism.commands.vault.subprocess.call") as mock_call:
        rc = cmd.take_action(parsed_args)

    assert rc == 1
    mock_call.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("No path" in r["message"] for r in errors)


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


def test_decrypt_propagates_exit_code(tmp_path):
    path = tmp_path / "secrets.yml"
    path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    cmd = vault.Decrypt(MagicMock(), MagicMock())
    parser = cmd.get_parser("test")
    parsed_args = parser.parse_args([str(path)])

    with patch("osism.commands.vault.subprocess.call", return_value=1):
        rc = cmd.take_action(parsed_args)

    assert rc == 1


# --- SetPassword.take_action ---


def _make_set_password(monkeypatch, tmp_path):
    """Build a SetPassword command whose keyfile lives under tmp_path.

    Returns the ``(command, parsed_args, keyfile)`` triple; the keyfile is
    not created, tests write it themselves when a pre-existing key is needed.
    """
    keyfile = tmp_path / "ansible_vault_password.key"
    monkeypatch.setattr(vault.SetPassword, "keyfile", str(keyfile))
    cmd = vault.SetPassword(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])
    return cmd, parsed_args, keyfile


def _piped_stdin(text):
    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = text
    return stdin


def test_set_password_reuses_existing_keyfile(monkeypatch, tmp_path, mock_redis):
    cmd, parsed_args, keyfile = _make_set_password(monkeypatch, tmp_path)
    key = Fernet.generate_key()
    keyfile.write_text(key.decode("utf-8"))

    with patch("sys.stdin", _piped_stdin("hunter2\n")), patch(
        "cryptography.fernet.Fernet.generate_key"
    ) as mock_generate:
        cmd.take_action(parsed_args)

    mock_generate.assert_not_called()
    assert keyfile.read_text() == key.decode("utf-8")
    name, token = mock_redis.set.call_args.args
    assert name == "ansible_vault_password"
    assert Fernet(key).decrypt(token) == b"hunter2"


def test_set_password_writes_generated_key_when_keyfile_missing(
    monkeypatch, tmp_path, mock_redis
):
    cmd, parsed_args, keyfile = _make_set_password(monkeypatch, tmp_path)
    key = Fernet.generate_key()

    with patch("sys.stdin", _piped_stdin("hunter2\n")), patch(
        "cryptography.fernet.Fernet.generate_key", return_value=key
    ):
        cmd.take_action(parsed_args)

    assert keyfile.read_text() == key.decode("utf-8")
    name, token = mock_redis.set.call_args.args
    assert name == "ansible_vault_password"
    assert Fernet(key).decrypt(token) == b"hunter2"


def test_set_password_reads_piped_stdin_without_prompting(
    monkeypatch, tmp_path, mock_redis
):
    cmd, parsed_args, keyfile = _make_set_password(monkeypatch, tmp_path)
    key = Fernet.generate_key()
    keyfile.write_text(key.decode("utf-8"))

    with patch("sys.stdin", _piped_stdin("  spacey-secret  \n")), patch(
        "prompt_toolkit.prompt"
    ) as mock_prompt:
        cmd.take_action(parsed_args)

    mock_prompt.assert_not_called()
    _, token = mock_redis.set.call_args.args
    assert Fernet(key).decrypt(token) == b"spacey-secret"


def test_set_password_prompts_on_tty(monkeypatch, tmp_path, mock_redis):
    cmd, parsed_args, keyfile = _make_set_password(monkeypatch, tmp_path)
    key = Fernet.generate_key()
    keyfile.write_text(key.decode("utf-8"))
    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch("sys.stdin", stdin), patch(
        "prompt_toolkit.prompt", return_value="tty-secret"
    ) as mock_prompt:
        cmd.take_action(parsed_args)

    mock_prompt.assert_called_once_with("Ansible Vault password: ", is_password=True)
    _, token = mock_redis.set.call_args.args
    assert Fernet(key).decrypt(token) == b"tty-secret"


# --- UnsetPassword.take_action ---


def test_unset_password_deletes_redis_key(mock_redis):
    cmd = vault.UnsetPassword(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    cmd.take_action(parsed_args)

    mock_redis.delete.assert_called_once_with("ansible_vault_password")


# --- Check._find_secrets_file ---


def _make_check():
    return vault.Check(MagicMock(), MagicMock())


def test_find_secrets_file_returns_first_existing_search_path():
    target = vault.SECRETS_SEARCH_PATHS[1]

    with patch(
        "osism.commands.vault.os.path.isfile", side_effect=lambda p: p == target
    ), patch("osism.commands.vault.glob.glob") as mock_glob:
        found = _make_check()._find_secrets_file()

    assert found == target
    mock_glob.assert_not_called()


def test_find_secrets_file_falls_back_to_glob():
    matches = [
        "/opt/configuration/environments/custom2/secrets.yml",
        "/opt/configuration/environments/other/secrets.yml",
    ]

    with patch("osism.commands.vault.os.path.isfile", return_value=False), patch(
        "osism.commands.vault.glob.glob", return_value=matches
    ) as mock_glob:
        found = _make_check()._find_secrets_file()

    assert found == matches[0]
    mock_glob.assert_called_once_with(
        "/opt/configuration/environments/**/secrets.yml", recursive=True
    )


def test_find_secrets_file_returns_none_when_nothing_found():
    with patch("osism.commands.vault.os.path.isfile", return_value=False), patch(
        "osism.commands.vault.glob.glob", return_value=[]
    ):
        assert _make_check()._find_secrets_file() is None


# --- Check.take_action ---


def _make_check_keyfile(monkeypatch, tmp_path, content=None):
    """Point ``Check.keyfile`` at a tmp_path file, optionally writing content."""
    keyfile = tmp_path / "ansible_vault_password.key"
    if content is not None:
        keyfile.write_text(content)
    monkeypatch.setattr(vault.Check, "keyfile", str(keyfile))
    return keyfile


def _setup_valid_chain(monkeypatch, tmp_path, mock_redis, password=b"secret"):
    """Real Fernet key on disk plus a matching encrypted password in Redis."""
    key = Fernet.generate_key()
    _make_check_keyfile(monkeypatch, tmp_path, key.decode("utf-8"))
    mock_redis.get.return_value = Fernet(key).encrypt(password)
    return key


def _parse_check(args):
    cmd = _make_check()
    return cmd, cmd.get_parser("test").parse_args(args)


def test_check_fails_when_keyfile_missing(monkeypatch, tmp_path, mock_redis, capsys):
    _make_check_keyfile(monkeypatch, tmp_path)
    cmd, parsed_args = _parse_check(["--format", "script"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: keyfile_missing\n"
    mock_redis.get.assert_not_called()


def test_check_fails_on_invalid_fernet_key(monkeypatch, tmp_path, mock_redis, capsys):
    _make_check_keyfile(monkeypatch, tmp_path, "not-a-fernet-key")
    cmd, parsed_args = _parse_check(["--format", "script"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: invalid_keyfile\n"
    mock_redis.get.assert_not_called()


def test_check_fails_when_password_not_set(monkeypatch, tmp_path, mock_redis, capsys):
    _make_check_keyfile(monkeypatch, tmp_path, Fernet.generate_key().decode("utf-8"))
    mock_redis.get.return_value = None
    cmd, parsed_args = _parse_check(["--format", "script"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: password_not_set\n"


def test_check_fails_when_token_cannot_be_decrypted(
    monkeypatch, tmp_path, mock_redis, capsys
):
    # Token encrypted with a different key than the one on disk, as after a
    # keyfile regeneration.
    _make_check_keyfile(monkeypatch, tmp_path, Fernet.generate_key().decode("utf-8"))
    mock_redis.get.return_value = Fernet(Fernet.generate_key()).encrypt(b"secret")
    cmd, parsed_args = _parse_check(["--format", "script"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: decryption_failed\n"


def test_check_fails_on_whitespace_only_password(
    monkeypatch, tmp_path, mock_redis, capsys
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis, password=b"  \t ")
    cmd, parsed_args = _parse_check(["--format", "script"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: password_empty\n"


def test_check_reports_wrong_password_for_undecryptable_file(
    monkeypatch, tmp_path, mock_redis, capsys
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis)
    secrets = tmp_path / "secrets.yml"
    secrets.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    cmd, parsed_args = _parse_check(["--format", "script", "--path", str(secrets)])

    # The unit-test environment stubs the ansible package (see
    # tests/conftest.py), so real vault decryption is impossible; mock the
    # VaultLib interaction instead.
    with patch("ansible.parsing.vault.VaultLib") as mock_vaultlib:
        mock_vaultlib.return_value.is_encrypted.return_value = True
        mock_vaultlib.return_value.decrypt.side_effect = Exception(
            "HMAC verification failed"
        )
        rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert capsys.readouterr().out == "FAILED: wrong_password\n"


def test_check_passes_with_valid_chain_and_encrypted_file(
    monkeypatch, tmp_path, mock_redis, capsys
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis)
    secrets = tmp_path / "secrets.yml"
    secrets.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")
    cmd, parsed_args = _parse_check(["--format", "script", "--path", str(secrets)])

    with patch("ansible.parsing.vault.VaultLib") as mock_vaultlib:
        mock_vaultlib.return_value.is_encrypted.return_value = True
        mock_vaultlib.return_value.decrypt.return_value = b"key: value\n"
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    assert capsys.readouterr().out == "PASSED\n"
    mock_vaultlib.return_value.decrypt.assert_called_once_with(
        b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n"
    )


def test_check_warns_when_no_secrets_file_found(
    monkeypatch, tmp_path, mock_redis, loguru_logs
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis)
    cmd, parsed_args = _parse_check(["--format", "log"])

    with patch.object(vault.Check, "_find_secrets_file", return_value=None):
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    warnings = [r for r in loguru_logs if r["level"] == "WARNING"]
    assert any("No secrets.yml file found" in r["message"] for r in warnings)


def test_check_resolves_relative_path_against_opt_configuration(
    monkeypatch, tmp_path, mock_redis, capsys
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis)
    cmd, parsed_args = _parse_check(
        ["--format", "script", "--path", "environments/kolla/secrets.yml"]
    )

    expected = "/opt/configuration/environments/kolla/secrets.yml"
    real_open = open
    opened = []

    def fake_open(path, *args, **kwargs):
        # Intercept only the resolved secrets path; the keyfile read in
        # step 2 must keep going to the real tmp_path file.
        if path == expected:
            opened.append(path)
            return mock_open(read_data=b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")()
        return real_open(path, *args, **kwargs)

    with patch("osism.commands.vault.open", fake_open, create=True), patch(
        "ansible.parsing.vault.VaultLib"
    ) as mock_vaultlib:
        mock_vaultlib.return_value.is_encrypted.return_value = True
        mock_vaultlib.return_value.decrypt.return_value = b"key: value\n"
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    assert opened == [expected]
    assert capsys.readouterr().out == "PASSED\n"


def test_check_skips_decryption_test_for_plain_file(
    monkeypatch, tmp_path, mock_redis, loguru_logs
):
    _setup_valid_chain(monkeypatch, tmp_path, mock_redis)
    secrets = tmp_path / "plain.yml"
    secrets.write_bytes(b"key: value\n")
    cmd, parsed_args = _parse_check(["--format", "log", "--path", str(secrets)])

    rc = cmd.take_action(parsed_args)

    assert rc == 0
    warnings = [r for r in loguru_logs if r["level"] == "WARNING"]
    assert any("not vault-encrypted" in r["message"] for r in warnings)
