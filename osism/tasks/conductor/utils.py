# SPDX-License-Identifier: Apache-2.0

from ansible import constants as ansible_constants
from ansible.parsing.vault import VaultLib, VaultSecret
from loguru import logger

from osism import utils


def deep_compare(a, b, updates):
    """
    Find items in a that do not exist in b or are different.
    Write required changes into updates
    """
    for key, value in a.items():
        if type(value) is not dict:
            if key not in b or b[key] != value:
                updates[key] = value
        else:
            updates[key] = {}
            deep_compare(a[key], b[key], updates[key])
            if not updates[key]:
                updates.pop(key)


def deep_merge(a, b):
    for key, value in b.items():
        if value == "DELETE":
            # NOTE: Use special string to remove keys
            a.pop(key, None)
        elif (
            key not in a.keys()
            or not isinstance(a[key], dict)
            or not isinstance(value, dict)
        ):
            a[key] = value
        else:
            deep_merge(a[key], value)


def deep_decrypt(a, vault):
    for key, value in list(a.items()):
        if not isinstance(value, dict):
            if vault.is_encrypted(value):
                try:
                    a[key] = vault.decrypt(value).decode()
                except Exception:
                    a.pop(key, None)
        else:
            deep_decrypt(a[key], vault)


def get_vault():
    """Create and return a VaultLib instance for decrypting secrets"""
    try:
        vault_secret = utils.get_ansible_vault_password()
        vault = VaultLib(
            [
                (
                    ansible_constants.DEFAULT_VAULT_ID_MATCH,
                    VaultSecret(vault_secret.encode()),
                )
            ]
        )
    except Exception:
        logger.error("Unable to get vault secret. Dropping encrypted entries")
        vault = VaultLib()
    return vault
