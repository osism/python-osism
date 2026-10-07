# osism/utils/hostvars.py
# SPDX-License-Identifier: Apache-2.0

"""Effective hostvars: the values `osism apply` would see, as output rows.

One render per stack: the primary stack (global, or the one given with
--environment) and, without --environment, each environment whose own
files can change a shown variable. Masking and row construction live in
osism.utils.hostvars_rows. When a whole stack fails, its secret values
are unknown, so Ansible's own output is withheld unless --show-secrets.
"""

from dataclasses import dataclass
from typing import Any, Callable

from osism.utils.hostvars_rows import (
    Rendered,
    Row,
    closure_of,
    secret_set,
    secret_values,
    stack_rows,
)
from osism.utils.render import (
    RenderError,
    Stack,
    build_stack,
    environment_local_names,
    list_environments,
    load_stack_files,
    render_batch,
)

__all__ = ["HostvarsError", "Row", "effective_rows"]

STACK_WITHHELD = (
    "render failed (Ansible failed for this stack; detail withheld; "
    "use --show-secrets)"
)


class HostvarsError(Exception):
    pass


@dataclass
class _Ctx:
    host: str
    show_secrets: bool
    inventory_path: str
    vault_password: str
    facts: Any
    raw_hostvars: dict
    all_raw_hostvars: dict
    root: str | None
    renderer: Callable


# Step 1
def _primary_stack(environment: str | None, root: str | None) -> Stack:
    if environment is not None:
        # Validated before any path is built from it.
        available = list_environments(root)
        if environment not in available:
            raise HostvarsError(
                f"unknown environment {environment}; "
                f"available: {', '.join(available)}"
            )
    return build_stack(environment, root=root)


# Step 2
def _merged_raw(stack: Stack, ctx: _Ctx) -> tuple:
    files = load_stack_files(stack, ctx.vault_password, allow_missing=True)
    raw = dict(ctx.raw_hostvars)
    for _, loaded in files:
        raw.update(loaded)
    return files, raw


def _raw_all(all_raw_hostvars: dict) -> dict:
    raw_all: dict = {}
    for host_vars in all_raw_hostvars.values():
        for name, value in host_vars.items():
            raw_all.setdefault(name, []).append(value)
    return raw_all


# Step 3
def _environment_locals(ctx: _Ctx) -> dict:
    """Each environment's own names, or the RenderError reading them."""
    env_local: dict = {}
    for e in list_environments(ctx.root):
        try:
            env_local[e] = set(
                environment_local_names(e, ctx.vault_password, root=ctx.root)
            )
        except RenderError as exc:
            env_local[e] = exc
    return env_local


def _shown_names(variable, files: list, ctx: _Ctx, env_local: dict) -> list:
    if variable is not None:
        return [variable]
    names = set(ctx.raw_hostvars)
    for _, loaded in files:
        names |= set(loaded)
    for local in env_local.values():
        if not isinstance(local, RenderError):
            names |= local
    return sorted(names)


# Steps 4 and 5
def _render(stack: Stack, names: list, ctx: _Ctx, merged=None) -> Rendered:
    files, raw = merged or _merged_raw(stack, ctx)
    secrets = secret_set(files, raw, ctx.all_raw_hostvars)
    request = {
        "names": list(names),
        "secrets": sorted(secrets),
        "raw": raw,
        "raw_all": _raw_all(ctx.all_raw_hostvars),
        "facts": sorted(ctx.facts) if isinstance(ctx.facts, dict) else [],
    }
    result = ctx.renderer(
        ctx.host, request, ctx.inventory_path, stack, ctx.vault_password, ctx.facts
    )
    values = result.get("values") or {}
    closures = result.get("closures") or {}
    return Rendered(values, closures, secrets, secret_values(values, secrets))


# Step 7
def _candidates(names: list, local, closures: dict) -> tuple:
    """(candidates, measured). Measured names are candidates only by being
    unanalysable; they keep their row only if the value differs."""
    if isinstance(local, RenderError):
        return list(names), set()
    candidates, measured = [], set()
    for name in names:
        closure = closure_of(closures, name)
        if name in local or set(closure["names"]) & local:
            candidates.append(name)
        elif closure["unanalysable"]:
            candidates.append(name)
            measured.add(name)
    return candidates, measured


def _environment_rows(e: str, local, names: list, primary: Rendered, ctx: _Ctx):
    candidates, measured = _candidates(names, local, primary.closures)
    if not candidates:
        return {}
    if isinstance(local, RenderError):
        return _failed_rows(candidates, e, _stack_failure_note(local, ctx), ctx)
    stack = build_stack(e, root=ctx.root)
    if stack.missing:
        note = (
            f"render failed: {stack.missing[0]} missing; "
            "this environment cannot be applied"
        )
        return _failed_rows(candidates, e, note, ctx)
    try:
        rendered = _render(stack, candidates, ctx)
    except RenderError as exc:
        return _failed_rows(candidates, e, _stack_failure_note(exc, ctx), ctx)
    rows = stack_rows(ctx.host, candidates, e, rendered, ctx.show_secrets)
    for name in measured & set(rows):
        if rendered.values.get(name) == primary.values.get(name):
            del rows[name]
    return rows


def _failed_rows(names: list, environment, note: str, ctx: _Ctx) -> dict:
    return {n: Row(ctx.host, n, environment, None, False, [note], True) for n in names}


# Step 9
def _stack_failure_note(exc: RenderError, ctx: _Ctx) -> str:
    if exc.safe or ctx.show_secrets:
        return f"render failed: {exc}"
    return STACK_WITHHELD


def effective_rows(
    host,
    variable,
    environment,
    show_secrets,
    *,
    inventory_path,
    vault_password,
    facts,
    raw_hostvars,
    all_raw_hostvars,
    root=None,
    renderer=render_batch,
) -> list:
    ctx = _Ctx(
        host,
        show_secrets,
        inventory_path,
        vault_password,
        facts,
        raw_hostvars,
        all_raw_hostvars,
        root,
        renderer,
    )
    stack = _primary_stack(environment, root)
    env_local = _environment_locals(ctx) if environment is None else {}
    try:
        merged = _merged_raw(stack, ctx)
        names = _shown_names(variable, merged[0], ctx, env_local)
        primary = _render(stack, names, ctx, merged)
    except RenderError as exc:
        # from None: an unsafe message must not ride along as __context__
        # into a printed traceback.
        raise HostvarsError(_stack_failure_note(exc, ctx)) from None
    per_env = [(None, stack_rows(host, names, None, primary, show_secrets))]
    for e, local in env_local.items():
        per_env.append((e, _environment_rows(e, local, names, primary, ctx)))
    # Step 8: an absent variable yields no rows, hence [].
    return [rows[n] for n in names for _, rows in per_env if n in rows]
