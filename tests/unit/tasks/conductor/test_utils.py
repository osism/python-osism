# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import pytest
from ansible.errors import AnsibleError
from ansible.parsing.vault import VaultLib

from osism.tasks.conductor.utils import (
    DELETE_SENTINEL,
    _is_secret_key,
    deep_compare,
    deep_decrypt,
    deep_merge,
    load_yaml_file,
)

# ---------------------------------------------------------------------------
# deep_compare
# ---------------------------------------------------------------------------


def test_deep_compare_identical_dicts_leaves_updates_empty():
    a = {"x": 1, "y": "two"}
    b = {"x": 1, "y": "two"}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {}


def test_deep_compare_records_missing_key_in_b():
    a = {"x": 1, "y": 2}
    b = {"x": 1}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"y": 2}


def test_deep_compare_records_changed_scalar_value():
    a = {"x": 1}
    b = {"x": 2}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"x": 1}


def test_deep_compare_records_nested_difference():
    a = {"outer": {"inner": "new", "same": 1}}
    b = {"outer": {"inner": "old", "same": 1}}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"outer": {"inner": "new"}}


def test_deep_compare_drops_empty_nested_branch():
    a = {"outer": {"inner": "same"}, "other": "diff"}
    b = {"outer": {"inner": "same"}, "other": "same"}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"other": "diff"}
    assert "outer" not in updates


def test_deep_compare_empty_a_leaves_updates_untouched():
    updates = {"preexisting": "value"}

    deep_compare({}, {"x": 1}, updates)

    assert updates == {"preexisting": "value"}


def test_deep_compare_records_none_value_when_key_missing_in_b():
    a = {"x": None}
    b = {}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"x": None}


def test_deep_compare_records_list_value_difference():
    a = {"items": [1, 2, 3]}
    b = {"items": [1, 2]}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"items": [1, 2, 3]}


def test_deep_compare_nested_key_missing_from_b_records_whole_subtree():
    a = {"outer": {"inner": "val", "other": 1}}
    b = {}
    updates = {}

    deep_compare(a, b, updates)

    assert updates == {"outer": {"inner": "val", "other": 1}}


# ---------------------------------------------------------------------------
# deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_disjoint_keys_kept():
    a = {"x": 1}
    b = {"y": 2}

    deep_merge(a, b)

    assert a == {"x": 1, "y": 2}


def test_deep_merge_overlapping_scalar_b_wins():
    a = {"x": 1}
    b = {"x": 2}

    deep_merge(a, b)

    assert a == {"x": 2}


def test_deep_merge_recurses_into_nested_dicts():
    a = {"outer": {"keep": 1, "shared": "old"}}
    b = {"outer": {"shared": "new", "added": 2}}

    deep_merge(a, b)

    assert a == {"outer": {"keep": 1, "shared": "new", "added": 2}}


def test_deep_merge_dict_overwritten_by_scalar():
    a = {"x": {"nested": 1}}
    b = {"x": "scalar"}

    deep_merge(a, b)

    assert a == {"x": "scalar"}


def test_deep_merge_scalar_overwritten_by_dict():
    a = {"x": 1}
    b = {"x": {"nested": 2}}

    deep_merge(a, b)

    assert a == {"x": {"nested": 2}}


def test_deep_merge_delete_sentinel_removes_key():
    a = {"x": 1, "y": 2}
    b = {"x": DELETE_SENTINEL}

    deep_merge(a, b)

    assert a == {"y": 2}


def test_deep_merge_delete_sentinel_for_missing_key_is_noop():
    a = {"y": 2}
    b = {"x": DELETE_SENTINEL}

    deep_merge(a, b)

    assert a == {"y": 2}


def test_deep_merge_mutates_a_in_place_and_leaves_b_unchanged():
    a = {"x": 1}
    b = {"y": 2, "nested": {"inner": 3}}
    b_snapshot = {"y": 2, "nested": {"inner": 3}}

    result = deep_merge(a, b)

    assert result is None
    assert a == {"x": 1, "y": 2, "nested": {"inner": 3}}
    assert b == b_snapshot


def test_deep_merge_empty_b_leaves_a_unchanged():
    a = {"x": 1}

    deep_merge(a, {})

    assert a == {"x": 1}


def test_deep_merge_delete_removes_nested_dict_value():
    a = {"x": {"nested": 1}}
    b = {"x": DELETE_SENTINEL}

    deep_merge(a, b)

    assert a == {}


# ---------------------------------------------------------------------------
# deep_decrypt
# ---------------------------------------------------------------------------


def _make_vault(encrypted_values=None, decrypt_map=None, decrypt_errors=None):
    """Build a VaultLib mock that recognises specific encrypted strings."""
    encrypted_values = set(encrypted_values or [])
    decrypt_map = decrypt_map or {}
    decrypt_errors = decrypt_errors or {}

    vault = MagicMock(spec=VaultLib)

    def _is_encrypted(value):
        return value in encrypted_values

    def _decrypt(value):
        if value in decrypt_errors:
            raise decrypt_errors[value]
        return decrypt_map[value]

    vault.is_encrypted.side_effect = _is_encrypted
    vault.decrypt.side_effect = _decrypt
    return vault


def test_deep_decrypt_none_returns_without_calling_vault():
    vault = MagicMock(spec=VaultLib)

    deep_decrypt(None, vault)

    vault.is_encrypted.assert_not_called()
    vault.decrypt.assert_not_called()


def test_deep_decrypt_dict_replaces_encrypted_string():
    vault = _make_vault(
        encrypted_values=["enc-token"],
        decrypt_map={"enc-token": b"  plaintext  "},
    )
    data = {"secret": "enc-token"}

    deep_decrypt(data, vault)

    assert data == {"secret": "plaintext"}


def test_deep_decrypt_dict_leaves_plaintext_untouched():
    vault = _make_vault()
    data = {"name": "alice"}

    deep_decrypt(data, vault)

    assert data == {"name": "alice"}
    vault.decrypt.assert_not_called()


def test_deep_decrypt_recurses_into_nested_dict():
    vault = _make_vault(
        encrypted_values=["enc"],
        decrypt_map={"enc": b"plain"},
    )
    data = {"outer": {"inner": "enc"}}

    deep_decrypt(data, vault)

    assert data == {"outer": {"inner": "plain"}}


def test_deep_decrypt_recurses_into_nested_list():
    vault = _make_vault(
        encrypted_values=["enc"],
        decrypt_map={"enc": b"plain"},
    )
    data = {"items": ["enc", "kept"]}

    deep_decrypt(data, vault)

    assert data == {"items": ["plain", "kept"]}


def test_deep_decrypt_top_level_list_replaces_encrypted_strings():
    vault = _make_vault(
        encrypted_values=["enc-1", "enc-2"],
        decrypt_map={"enc-1": b"plain-1\n", "enc-2": b"  plain-2"},
    )
    data = ["enc-1", "literal", "enc-2"]

    deep_decrypt(data, vault)

    assert data == ["plain-1", "literal", "plain-2"]


def test_deep_decrypt_dict_value_decrypt_failure_drops_key():
    vault = _make_vault(
        encrypted_values=["broken", "ok"],
        decrypt_map={"ok": b"clear"},
        decrypt_errors={"broken": AnsibleError("bad signature")},
    )
    data = {"a": "broken", "b": "ok"}

    deep_decrypt(data, vault)

    assert data == {"b": "clear"}


def test_deep_decrypt_list_element_decrypt_failure_left_in_place():
    vault = _make_vault(
        encrypted_values=["broken", "ok"],
        decrypt_map={"ok": b"clear"},
        decrypt_errors={"broken": AnsibleError("bad signature")},
    )
    data = ["broken", "ok"]

    deep_decrypt(data, vault)

    assert data == ["broken", "clear"]


def test_deep_decrypt_strips_whitespace_after_decode():
    vault = _make_vault(
        encrypted_values=["enc"],
        decrypt_map={"enc": b"\n  value with trailing space   \n"},
    )
    data = {"k": "enc"}

    deep_decrypt(data, vault)

    assert data == {"k": "value with trailing space"}


def test_deep_decrypt_deeply_nested_mixed_structures():
    vault = _make_vault(
        encrypted_values=["e1", "e2"],
        decrypt_map={"e1": b"p1", "e2": b"p2"},
    )
    data = {"a": [{"b": "e1"}, ["e2", "literal"]]}

    deep_decrypt(data, vault)

    assert data == {"a": [{"b": "p1"}, ["p2", "literal"]]}


# ---------------------------------------------------------------------------
# _is_secret_key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [42, None, b"password", 1.5, ("password",)])
def test_is_secret_key_non_string_returns_false(value):
    assert _is_secret_key(value) is False


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "PASSWORD",
        "db_password",
        "secret",
        "client_secret",
        "SECRET_KEY",
        "ironic_osism_foo",
        "IRONIC_OSISM_BAR",
        "user_password_hash",
    ],
)
def test_is_secret_key_matches(key):
    assert _is_secret_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "username",
        "host",
        "ironic_other",
        "ironic",
        "osism_ironic_foo",
        "",
    ],
)
def test_is_secret_key_does_not_match(key):
    assert _is_secret_key(key) is False


# ---------------------------------------------------------------------------
# load_yaml_file
# ---------------------------------------------------------------------------


def test_load_yaml_file_missing_path_returns_none(tmp_path):
    assert load_yaml_file(str(tmp_path / "does-not-exist.yml")) is None


def test_load_yaml_file_parses_plain_yaml(tmp_path):
    path = tmp_path / "plain.yml"
    path.write_text("foo:\n  bar: 1\n")

    assert load_yaml_file(str(path)) == {"foo": {"bar": 1}}


def test_load_yaml_file_empty_file_returns_none(tmp_path):
    path = tmp_path / "empty.yml"
    path.write_text("")

    assert load_yaml_file(str(path)) is None


def test_load_yaml_file_malformed_yaml_returns_none(tmp_path):
    path = tmp_path / "bad.yml"
    path.write_text("foo: [unterminated\n")

    assert load_yaml_file(str(path)) is None


def test_load_yaml_file_oserror_returns_none(tmp_path):
    path = tmp_path / "exists.yml"
    path.write_text("foo: 1\n")

    real_open = open

    def _failing_open(file, *args, **kwargs):
        if str(file) == str(path):
            raise OSError("simulated failure")
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=_failing_open):
        assert load_yaml_file(str(path)) is None


def test_load_yaml_file_directory_returns_none(tmp_path):
    directory = tmp_path / "dir.yml"
    directory.mkdir()

    assert load_yaml_file(str(directory)) is None


def test_load_yaml_file_decrypts_vault_encrypted_file(tmp_path):
    path = tmp_path / "encrypted.yml"
    path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")

    fake_vault = MagicMock()
    fake_vault.decrypt.return_value = b"foo:\n  bar: 1\n"

    with patch("osism.tasks.conductor.utils.get_vault", return_value=fake_vault):
        result = load_yaml_file(str(path))

    assert result == {"foo": {"bar": 1}}
    fake_vault.decrypt.assert_called_once()


def test_load_yaml_file_encrypted_decrypt_failure_returns_none(tmp_path):
    path = tmp_path / "encrypted.yml"
    path.write_bytes(b"$ANSIBLE_VAULT;1.1;AES256\nciphertext\n")

    fake_vault = MagicMock()
    fake_vault.decrypt.side_effect = AnsibleError("bad password")

    with patch("osism.tasks.conductor.utils.get_vault", return_value=fake_vault):
        assert load_yaml_file(str(path)) is None


def test_load_yaml_file_does_not_call_get_vault_for_plain_file(tmp_path):
    path = tmp_path / "plain.yml"
    path.write_text("foo: 1\n")

    with patch("osism.tasks.conductor.utils.get_vault") as get_vault:
        result = load_yaml_file(str(path))

    assert result == {"foo": 1}
    get_vault.assert_not_called()
