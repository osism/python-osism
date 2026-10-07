# osism/utils/evaluate.py
# SPDX-License-Identifier: Apache-2.0

"""Evaluate one render request: dependency closures and values, in one pass.

Runs inside the ``osism_render`` action plugin, so that dynamic keys
discovered while walking a closure are resolved by Ansible's own templar
in the same invocation (one Ansible run per stack). ``resolve`` templates
one expression and returns ``{"value": ...}`` or ``{"error": str}``; unit
tests pass a fake. Dynamic keys are templated as expressions; variable
values are looked up as ``vars['<name>']``.

Request:
    names    -- variables to report
    secrets  -- the secret set S of this stack; always rendered, for the
                literal net
    raw      -- name -> raw value for the queried host, stack files already
                applied over the inventory
    raw_all  -- name -> list of raw values across all hosts (and the stack
                value), for cross-host references
    facts    -- optional; names of the queried host's cached facts, which
                count as defined

Result:
    values   -- name -> {"value": v} | {"error": str}, for names and secrets
    closures -- name -> {"names": [...], "unanalysable": bool,
                         "undefined": [...], "secret_hits": [...],
                         "fallback": [...]}

    fallback lists the undefined names that occur inside a default/d
    filter's base or argument, where the value falls back.
"""

from typing import Callable

from osism.utils.template_deps import references

Resolve = Callable[[str], dict]


def _closure(name: str, request: dict, resolve: Resolve, key_cache: dict) -> dict:
    raw, raw_all = request["raw"], request["raw_all"]
    facts = set(request.get("facts") or ())
    seen: set = set()
    names: set = set()
    undefined: set = set()
    defaulted: set = set()
    unanalysable = False
    work = [(name, "host")]
    while work:
        current, scope = work.pop()
        if (current, scope) in seen:
            continue
        seen.add((current, scope))
        if current != name:
            names.add(current)
        sources = [raw[current]] if scope == "host" and current in raw else []
        if scope == "all":
            sources = list(raw_all.get(current, []))
            if current in raw:
                sources.append(raw[current])
        if not sources:
            if current != name and current not in facts:
                undefined.add(current)
            continue
        for value in sources:
            refs = references(value)
            if refs.unanalysable:
                unanalysable = True
            defaulted |= refs.defaulted
            for n in refs.names:
                work.append((n, scope))
            for n in refs.cross_host_names:
                work.append((n, "all"))
            for key in refs.dynamic_keys:
                if key.expression is None:
                    unanalysable = True
                    continue
                if key.expression not in key_cache:
                    key_cache[key.expression] = resolve(key.expression)
                result = key_cache[key.expression]
                if "error" in result or not isinstance(result.get("value"), str):
                    unanalysable = True
                    continue
                if key.defaulted:
                    defaulted.add(result["value"])
                work.append((result["value"], "all" if key.cross_host else scope))
    secrets = set(request["secrets"])
    return {
        "names": sorted(names),
        "unanalysable": unanalysable,
        "undefined": sorted(undefined),
        "secret_hits": sorted(names & secrets),
        "fallback": sorted(undefined & defaulted),
    }


def _value(resolve: Resolve, name: str) -> dict:
    """Look a variable up by name; a name is never templated as an expression.

    vars['<absent>'] fails with Jinja's "has no attribute" message, so an
    absent name is checked first and reported in the shape of templating
    an undefined name, which callers rely on to drop the row.
    """
    key = repr(str(name))
    present = resolve(f"{key} in vars")
    if present.get("value") is False:
        return {"error": f"AnsibleUndefinedVariable: '{name}' is undefined"}
    return resolve(f"vars[{key}]")


def evaluate_request(resolve: Resolve, request: dict) -> dict:
    key_cache: dict = {}
    closures = {n: _closure(n, request, resolve, key_cache) for n in request["names"]}
    values: dict = {}
    for n in list(request["names"]) + sorted(
        set(request["secrets"]) - set(request["names"])
    ):
        values[n] = _value(resolve, n)
    return {"values": values, "closures": closures}
