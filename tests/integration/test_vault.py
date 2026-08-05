# SPDX-License-Identifier: Apache-2.0

"""Ansible vault password round-trip integration tests.

``get_ansible_vault_password`` is the seam through which conductor workers get
the vault secret (``osism.tasks.conductor.utils.get_vault``). It glues Fernet to
Redis: the key comes from a keyfile, the token from Redis. These tests run that
chain against the live Redis, together with the ``osism vault`` commands that
write and remove the token.
"""

import sys
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet, InvalidToken

from osism import settings, utils
from osism.commands import vault

pytestmark = pytest.mark.integration

VAULT_KEY = "ansible_vault_password"


@pytest.fixture
def vault_keyfile(monkeypatch, tmp_path):
    """Redirect the keyfile path to ``tmp_path`` and return it.

    The file itself is not created: tests that need a pre-existing Fernet key
    write one themselves, and the command round trip leaves it absent so
    ``SetPassword`` generates it for real.
    """
    keyfile = tmp_path / "ansible_vault_password.key"
    monkeypatch.setattr(settings, "ANSIBLE_VAULT_KEYFILE", str(keyfile))
    return keyfile


@pytest.fixture(autouse=True)
def clean_vault_key():
    """Delete the vault key before and after each test.

    The key name is part of the contract under test, so it cannot be
    namespaced per run the way the sibling modules namespace theirs, and the
    Redis database is shared by the whole integration session -- the cleanup
    must not depend on the test passing. Deleting a name a real deployment
    also owns is safe only because ``conftest.py`` refuses to run against the
    default database.
    """
    utils.redis.delete(VAULT_KEY)
    yield
    utils.redis.delete(VAULT_KEY)


def _write_key(keyfile):
    """Write a fresh Fernet key to ``keyfile`` and return it."""
    key = Fernet.generate_key()
    keyfile.write_text(key.decode("utf-8"))
    return key


def _piped_stdin(text):
    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = text
    return stdin


def test_round_trip_returns_plaintext(vault_keyfile):
    """A password encrypted with the keyfile's key is read back as plaintext."""
    key = _write_key(vault_keyfile)
    utils.redis.set(VAULT_KEY, Fernet(key).encrypt(b"hunter2"))

    assert utils.get_ansible_vault_password() == "hunter2"


def test_missing_redis_key_raises_value_error(vault_keyfile):
    """Without the Redis key the read path raises ``ValueError``."""
    _write_key(vault_keyfile)

    with pytest.raises(ValueError, match="not set in Redis"):
        utils.get_ansible_vault_password()


def test_token_from_other_key_raises_invalid_token(vault_keyfile):
    """A token written under a different Fernet key raises ``InvalidToken``."""
    _write_key(vault_keyfile)
    utils.redis.set(VAULT_KEY, Fernet(Fernet.generate_key()).encrypt(b"hunter2"))

    with pytest.raises(InvalidToken):
        utils.get_ansible_vault_password()


def test_command_round_trip(vault_keyfile, monkeypatch, capsys):
    """``set`` writes what ``check`` accepts and ``unset`` removes again."""
    set_password = vault.SetPassword(MagicMock(), MagicMock())
    monkeypatch.setattr(sys, "stdin", _piped_stdin("hunter2\n"))
    set_password.take_action(set_password.get_parser("test").parse_args([]))

    assert vault_keyfile.exists()
    assert utils.get_ansible_vault_password() == "hunter2"

    check = vault.Check(MagicMock(), MagicMock())
    # The last check step decrypts a secrets.yml with ansible's VaultLib.
    # ansible-core is not installed in this environment (it lives in the
    # optional [ansible] extra), so tests/conftest.py stubs VaultLib and its
    # decrypt() is a no-op that would report success for any password -- the
    # step is skipped rather than mocked, since pointing --path at an
    # encrypted fixture would only look like coverage. Worth covering for real
    # if ansible-core is ever added to the test dependencies.
    monkeypatch.setattr(vault.Check, "_find_secrets_file", lambda self: None)
    rc = check.take_action(check.get_parser("test").parse_args(["--format", "script"]))

    assert rc == 0
    # ``--format script`` prints one token, ``PASSED`` or ``FAILED: <reason>``.
    # Compared after stripping, so the surrounding whitespace stays free to
    # change while the contract itself is still asserted.
    assert capsys.readouterr().out.strip() == "PASSED"

    unset = vault.UnsetPassword(MagicMock(), MagicMock())
    unset.take_action(unset.get_parser("test").parse_args([]))

    assert utils.redis.get(VAULT_KEY) is None
    with pytest.raises(ValueError, match="not set in Redis"):
        utils.get_ansible_vault_password()
