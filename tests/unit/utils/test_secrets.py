# SPDX-License-Identifier: Apache-2.0

import pytest

from osism.utils.secrets import (
    is_secret_key,
    is_vault_value,
    mask_structure,
    replace_literals,
    replace_literals_deep,
)


@pytest.mark.parametrize(
    "key", ["password", "DB_PASSWORD", "my_secret", "ironic_osism_x"]
)
def test_is_secret_key_matches(key):
    assert is_secret_key(key) is True


@pytest.mark.parametrize("key", ["host", "osism_ironic", None, 3])
def test_is_secret_key_does_not_match(key):
    assert is_secret_key(key) is False


def test_is_vault_value_string_prefix():
    assert is_vault_value("$ANSIBLE_VAULT;1.1;AES256\n6162") is True
    assert is_vault_value("  $ANSIBLE_VAULT;1.1") is True


def test_is_vault_value_inline_vault_dict():
    # ansible-inventory renders an inline !vault value as this dict
    # (observed with ansible-core 2.19.11, 2026-10-07).
    assert is_vault_value({"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n63"}) is True


def test_is_vault_value_plain():
    assert is_vault_value("plain") is False
    assert is_vault_value({"a": 1}) is False


def test_mask_structure_matches_api_behaviour():
    data = {
        "db_password": "x",
        "nested": {"secret_key": "y", "ok": "$ANSIBLE_VAULT;1.1"},
        "lst": ["$ANSIBLE_VAULT;1.1", "keep"],
        "plain": "z",
    }
    assert mask_structure(data) == {
        "db_password": "***",
        "nested": {"secret_key": "***", "ok": "***"},
        "lst": ["***", "keep"],
        "plain": "z",
    }


def test_replace_literals_threshold():
    assert replace_literals("a-abcdef-b", ["abcdef"], min_length=6) == "a-***-b"
    assert replace_literals("a-abcde-b", ["abcde"], min_length=6) == "a-abcde-b"


def test_replace_literals_overmasks_substrings_by_design():
    # Review focus 3: an unrelated value containing a secret is masked too.
    assert replace_literals("xabcdefx", ["abcdef"], min_length=6) == "x***x"


def test_replace_literals_longest_first():
    assert replace_literals("abcdefgh", ["abcdef", "abcdefgh"]) == "***"


def test_replace_literals_deep_copies():
    obj = {"a": ["xx-secret1-yy", 3]}
    out = replace_literals_deep(obj, ["secret1"])
    assert out == {"a": ["xx-***-yy", 3]}
    assert obj == {"a": ["xx-secret1-yy", 3]}


def test_mask_structure_keeps_api_inline_vault_shape():
    # The API masks by string prefix only (spec D6): an inline vault dict
    # keeps its shape, its ciphertext string is masked.
    data = {"x": {"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n63"}}
    assert mask_structure(data) == {"x": {"__ansible_vault": "***"}}


def test_mask_structure_structural_vault_masks_whole_value():
    data = {"x": {"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n63"}}
    assert mask_structure(data, structural_vault=True) == {"x": "***"}
