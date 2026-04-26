# SPDX-License-Identifier: Apache-2.0

"""Pytest configuration shared by all unit tests.

``osism/tasks/conductor/utils.py`` imports ``ansible`` at module level, so
importing any submodule under ``osism.tasks.conductor`` triggers that import
via the package ``__init__`` chain. ``ansible-core`` lives in the optional
``[ansible]`` extra and is not installed in the unit-test environment.

To keep test setup lightweight we register stub modules in ``sys.modules``
before tests are collected. The stubs only need to satisfy the
``from ansible... import ...`` statements; no runtime behaviour is emulated.
Tests that genuinely exercise ansible-using code paths must install
``ansible-core`` (or replace these stubs with mocks at the test level).
"""

import sys
import types


def _install_ansible_stubs() -> None:
    try:
        import ansible  # noqa: F401
    except ImportError:
        pass
    else:
        return

    ansible_mod = types.ModuleType("ansible")
    ansible_mod.__path__ = []  # type: ignore[attr-defined]

    constants = types.ModuleType("ansible.constants")
    setattr(constants, "DEFAULT_VAULT_ID_MATCH", "default")

    errors = types.ModuleType("ansible.errors")

    class AnsibleError(Exception):
        pass

    setattr(errors, "AnsibleError", AnsibleError)

    parsing = types.ModuleType("ansible.parsing")
    parsing.__path__ = []  # type: ignore[attr-defined]

    vault = types.ModuleType("ansible.parsing.vault")

    class VaultLib:
        def __init__(self, *args, **kwargs):
            pass

        def is_encrypted(self, data, *args, **kwargs):
            if isinstance(data, str):
                data = data.encode("utf-8", errors="ignore")
            return isinstance(data, (bytes, bytearray)) and bytes(data).startswith(
                b"$ANSIBLE_VAULT"
            )

        def decrypt(self, *args, **kwargs):
            return b""

    class VaultSecret:
        def __init__(self, *args, **kwargs):
            pass

    setattr(vault, "VaultLib", VaultLib)
    setattr(vault, "VaultSecret", VaultSecret)

    setattr(ansible_mod, "constants", constants)
    setattr(ansible_mod, "errors", errors)
    setattr(ansible_mod, "parsing", parsing)
    setattr(parsing, "vault", vault)

    sys.modules["ansible"] = ansible_mod
    sys.modules["ansible.constants"] = constants
    sys.modules["ansible.errors"] = errors
    sys.modules["ansible.parsing"] = parsing
    sys.modules["ansible.parsing.vault"] = vault


_install_ansible_stubs()
