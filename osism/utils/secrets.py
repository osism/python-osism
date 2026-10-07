# SPDX-License-Identifier: Apache-2.0

"""Secret detection and masking shared by the CLI, the API and the conductor.

The key rule and structural masking moved here from
``osism.tasks.conductor.utils`` and ``osism.api``. Their callers keep
their output. ``replace_literals`` is the literal half of masking: it
replaces known secret values inside arbitrary text.
"""

import copy
from typing import Any, Iterable

VAULT_PREFIX = "$ANSIBLE_VAULT;"


def is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lower = key.lower()
    return "password" in lower or "secret" in lower or lower.startswith("ironic_osism_")


def is_vault_value(value: Any) -> bool:
    """True for a vault-encrypted value as Ansible tools present it.

    A vaulted file's value is a string with the vault header. An inline
    ``!vault`` value comes out of ``ansible-inventory`` as
    ``{"__ansible_vault": "<ciphertext>"}``.
    """
    if isinstance(value, str):
        return value.strip().startswith(VAULT_PREFIX)
    if isinstance(value, dict) and set(value) == {"__ansible_vault"}:
        return True
    return False


def mask_structure(data: dict, mask: str = "***") -> dict:
    """Mask by key name and by vault value, recursively. The API's rule."""
    masked: dict = {}
    for key, value in data.items():
        masked[key] = mask if is_secret_key(key) else _mask_value(value, mask)
    return masked


def _mask_value(value: Any, mask: str) -> Any:
    if is_vault_value(value):
        return mask
    if isinstance(value, dict):
        return mask_structure(value, mask)
    if isinstance(value, list):
        return [_mask_value(item, mask) for item in value]
    return value


def replace_literals(
    text: str, secret_values: Iterable[str], mask: str = "***", min_length: int = 0
) -> str:
    """Replace every occurrence of each secret value, longest first."""
    values = sorted(
        {v for v in secret_values if isinstance(v, str) and v and len(v) >= min_length},
        key=len,
        reverse=True,
    )
    for value in values:
        text = text.replace(value, mask)
    return text


def replace_literals_deep(
    obj: Any, secret_values: Iterable[str], mask: str = "***", min_length: int = 0
) -> Any:
    values = list(secret_values)
    result = copy.deepcopy(obj)

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return replace_literals(node, values, mask, min_length)
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(result)
