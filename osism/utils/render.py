# osism/utils/render.py
# SPDX-License-Identifier: Apache-2.0

"""Render variables the way `osism apply` would see them in an environment.

One controller-side Ansible run per (host, stack). The stack is the
inventory plus the extra-vars files the standard run scripts pass
(osism-ansible files/scripts/run-*.sh, kolla-ansible
files/scripts/<series>/run.sh), in their order. The action plugin runs
osism.utils.evaluate.evaluate_request with Ansible's templar as the
resolver, so dependency closures, dynamic keys and values all come out of
that one run.
"""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import cast

import yaml

from osism import settings
from osism.utils.template_deps import UnsafeText

_PLUGIN = """\
import json
from ansible.plugins.action import ActionBase
from ansible.template import trust_as_template


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(self, tmp=None, task_vars=None):
        from osism.utils.evaluate import evaluate_request

        result = super().run(tmp, task_vars)

        def resolve(expr):
            try:
                value = self._templar.template(trust_as_template("{{ %s }}" % expr))
                json.dumps(value, default=str)
                return {"value": value}
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}"}

        with open(self._task.args["request"]) as fp:
            request = json.load(fp)
        with open(self._task.args["dest"], "w") as fp:
            json.dump(evaluate_request(resolve, request), fp, default=str)
        result["changed"] = False
        return result
"""


class RenderError(Exception):
    """Ansible could not run, or the stack cannot be applied or read.

    ``safe`` is True for messages composed here (missing file, invalid YAML
    at a line, cannot decrypt), which never carry values. It is False for
    Ansible's own output, which may quote secrets. Callers withhold it
    unless --show-secrets.
    """

    def __init__(self, message: str, safe: bool = True):
        super().__init__(message)
        self.safe = safe


@dataclass(frozen=True)
class Stack:
    environment: str | None
    files: tuple
    missing: tuple


class _VaultSafeLoader(yaml.SafeLoader):
    """SafeLoader that keeps an inline !vault value as the encrypted marker
    and loads an !unsafe value as UnsafeText, which is never analysed."""


def _construct_vault(loader: yaml.SafeLoader, node: yaml.Node) -> dict:
    return {"__ansible_vault": loader.construct_scalar(cast(yaml.ScalarNode, node))}


_VaultSafeLoader.add_constructor("!vault", _construct_vault)


def _construct_unsafe(loader: yaml.SafeLoader, node: yaml.Node) -> UnsafeText:
    return UnsafeText(loader.construct_scalar(cast(yaml.ScalarNode, node)))


_VaultSafeLoader.add_constructor("!unsafe", _construct_unsafe)


def list_environments(root: str | None = None) -> list:
    root = root or settings.ENVIRONMENTS_DIRECTORY
    try:
        entries = os.listdir(root)
    except OSError:
        return []
    return sorted(
        e
        for e in entries
        if not e.startswith(".") and os.path.isdir(os.path.join(root, e))
    )


def environment_files(environment: str, root: str | None = None) -> tuple:
    root = root or settings.ENVIRONMENTS_DIRECTORY
    return tuple(
        os.path.join(root, environment, f)
        for f in ("secrets.yml", "images.yml", "configuration.yml")
    )


def build_stack(environment: str | None, root: str | None = None) -> Stack:
    root = root or settings.ENVIRONMENTS_DIRECTORY
    files = [os.path.join(root, "configuration.yml"), os.path.join(root, "secrets.yml")]
    if environment:
        files += list(environment_files(environment, root))
    return Stack(
        environment, tuple(files), tuple(f for f in files if not os.path.isfile(f))
    )


def _check(stack: Stack) -> None:
    if stack.missing:
        raise RenderError(
            f"{stack.missing[0]} missing; this environment cannot be applied"
        )


def load_yaml(path: str, vault_password: str) -> dict:
    from ansible.constants import DEFAULT_VAULT_ID_MATCH
    from ansible.parsing.vault import VaultLib, VaultSecret

    vault = VaultLib([(DEFAULT_VAULT_ID_MATCH, VaultSecret(vault_password.encode()))])
    with open(path, "rb") as fp:
        data = fp.read()
    if vault.is_encrypted(data):
        try:
            data = vault.decrypt(data)
        except Exception as exc:
            raise RenderError(f"cannot decrypt {path} ({type(exc).__name__})") from exc
    try:
        loaded = yaml.load(data, Loader=_VaultSafeLoader) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else "?"
        raise RenderError(
            f"{path}: invalid YAML at line {line} ({type(exc).__name__})"
        ) from None
    if not isinstance(loaded, dict):
        raise RenderError(f"{path} is not a mapping")
    return loaded


def load_stack_files(
    stack: Stack, vault_password: str, allow_missing: bool = False
) -> list:
    if not allow_missing:
        _check(stack)
    return [
        (p, load_yaml(p, vault_password)) for p in stack.files if p not in stack.missing
    ]


def stack_file_names(
    stack: Stack, vault_password: str, allow_missing: bool = False
) -> dict:
    names: dict = {}
    for path, loaded in load_stack_files(stack, vault_password, allow_missing):
        for key in loaded:
            names[key] = path
    return names


def environment_local_names(
    environment: str, vault_password: str, root: str | None = None
) -> set:
    names: set = set()
    for path in environment_files(environment, root):
        if os.path.isfile(path):
            names |= set(load_yaml(path, vault_password))
    return names


def render_batch(
    host, request, inventory_path, stack, vault_password, facts=None, timeout=300
):
    _check(stack)
    with tempfile.TemporaryDirectory(prefix="osism-render-") as workdir:
        with open(os.path.join(workdir, "osism_render.py"), "w") as fp:
            fp.write(_PLUGIN)
        vault_file = os.path.join(workdir, "vault")
        with open(os.open(vault_file, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fp:
            fp.write(vault_password)
        request_file = os.path.join(workdir, "request.json")
        with open(request_file, "w") as fp:
            json.dump(request, fp)
        dest = os.path.join(workdir, "out.json")
        command = [
            "ansible",
            host,
            "-i",
            inventory_path,
            "-c",
            "local",
            "-m",
            "osism_render",
            "-a",
            json.dumps({"request": request_file, "dest": dest}),
            "--vault-password-file",
            vault_file,
        ]
        # A later -e wins. In a play, facts rank below extra-vars, so the
        # cached facts go before the stack files.
        if facts:
            facts_path = os.path.join(workdir, "facts.json")
            with open(facts_path, "w") as fp:
                json.dump(facts, fp)
            command += ["-e", f"@{facts_path}"]
        for path in stack.files:
            command += ["-e", f"@{path}"]
        env = os.environ.copy()
        env.update(
            ANSIBLE_GATHERING="explicit",
            ANSIBLE_NOCOLOR="1",
            ANSIBLE_RETRY_FILES_ENABLED="False",
        )
        env["ANSIBLE_ACTION_PLUGINS"] = os.pathsep.join(
            p for p in (workdir, env.get("ANSIBLE_ACTION_PLUGINS")) if p
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=workdir,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"ansible timed out after {timeout}s") from exc
        if result.returncode != 0:
            detail = (result.stdout or "").strip() or (result.stderr or "").strip()
            raise RenderError(
                detail or f"ansible exited {result.returncode}", safe=False
            )
        try:
            with open(dest) as fp:
                return json.load(fp)
        except OSError as exc:
            raise RenderError("ansible wrote no result") from exc
