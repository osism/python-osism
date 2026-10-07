# osism/utils/hostvars_rows.py
# SPDX-License-Identifier: Apache-2.0

"""Masking and row construction for one stack's render result.

Used by osism.utils.hostvars. Every value and every error text that
reaches a Row passes here first:

- taint: a variable in the secret set S, or whose dependency closure
  reaches S, is masked; an unanalysable one is masked too;
- literal net: every rendered secret value of 6 or more characters is
  replaced wherever it occurs, in values and in notes;
- the error detail of a tainted or unanalysable variable is withheld.

show_secrets disables all of it.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any

from osism.utils.secrets import (
    is_secret_key,
    is_vault_value,
    replace_literals,
    replace_literals_deep,
)

MASK = "***"
MIN_SECRET_LENGTH = 6
WITHHELD = "render failed (detail withheld; use --show-secrets)"
_UNDEFINED = re.compile(r"^AnsibleUndefinedVariable: '([^']*)' is undefined")
# A closure, or a key of one, that did not come back counts as the worst case.
_UNKNOWN_CLOSURE: dict[str, Any] = {
    "names": [],
    "unanalysable": True,
    "undefined": [],
    "secret_hits": [],
    "uses_default": False,
}


@dataclass
class Row:
    host: str
    variable: str
    environment: str | None
    value: Any
    masked: bool
    notes: list = field(default_factory=list)
    failed: bool = False


@dataclass
class Rendered:
    """One stack's render: its result, secret set S and secret values."""

    values: dict
    closures: dict
    secrets: set
    secret_values: list


def closure_of(closures: dict, name: str) -> dict[str, Any]:
    return {**_UNKNOWN_CLOSURE, **(closures.get(name) or {})}


def secret_set(files: list, raw: dict, all_raw_hostvars: dict) -> set:
    """Step 4: the secret set S of a stack."""
    secrets: set = set()
    for path, loaded in files:
        if os.path.basename(path) == "secrets.yml":
            secrets |= set(loaded)
    for name, value in raw.items():
        if is_secret_key(name) or is_vault_value(value):
            secrets.add(name)
    for host_vars in all_raw_hostvars.values():
        secrets |= {n for n, v in host_vars.items() if is_vault_value(v)}
    return secrets


def secret_values(values: dict, secrets: set) -> list:
    """Rendered strings of S (6+ characters), and every string inside
    a list or dict value of S."""
    found: list = []

    def collect(node: Any, top: bool) -> None:
        if isinstance(node, str):
            if not top or len(node) >= MIN_SECRET_LENGTH:
                found.append(node)
        elif isinstance(node, dict):
            for item in node.values():
                collect(item, False)
        elif isinstance(node, list):
            for item in node:
                collect(item, False)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            collect(str(node), top)

    for name in secrets:
        result = values.get(name) or {}
        if "value" in result:
            collect(result["value"], True)
    return found


def _clean(text: Any, rendered: Rendered, show_secrets: bool) -> str:
    if show_secrets:
        return str(text)
    return replace_literals(str(text), rendered.secret_values, MASK, MIN_SECRET_LENGTH)


def _row(
    host: str, name: str, environment, rendered: Rendered, show_secrets: bool
) -> Row | None:
    result = rendered.values.get(name) or {"error": "no result for this variable"}
    closure = closure_of(rendered.closures, name)
    tainted = name in rendered.secrets or bool(closure["secret_hits"])
    if "value" not in result:
        error = str(result.get("error"))
        match = _UNDEFINED.match(error)
        if match and match.group(1) == name:
            return None
        if not show_secrets and (tainted or closure["unanalysable"]):
            note = WITHHELD
        else:
            note = "render failed: " + _clean(error, rendered, show_secrets)
        return Row(host, name, environment, None, False, [note], True)
    value, masked, notes = result["value"], False, []
    if not show_secrets:
        if tainted:
            hits = sorted(closure["secret_hits"])
            sources = name if name in rendered.secrets else ", ".join(hits)
            value, masked = MASK, True
            notes.append(f"masked: derived from {sources}")
        elif closure["unanalysable"]:
            value, masked = MASK, True
            notes.append("masked: could not analyse dependencies")
        else:
            cleaned = replace_literals_deep(
                value, rendered.secret_values, MASK, MIN_SECRET_LENGTH
            )
            value, masked = cleaned, cleaned != value
    if closure["uses_default"]:
        # A dynamic key resolved to a value can land in `undefined`.
        notes += [
            _clean(
                f"fallback: {n} undefined here, a role may define it",
                rendered,
                show_secrets,
            )
            for n in sorted(closure["undefined"])
        ]
    return Row(host, name, environment, value, masked, notes, False)


def stack_rows(
    host: str, names: list, environment, rendered: Rendered, show_secrets: bool
) -> dict:
    """Step 6: name -> Row; a name undefined in this stack gets none."""
    rows = {}
    for name in names:
        row = _row(host, name, environment, rendered, show_secrets)
        if row is not None:
            rows[name] = row
    return rows
