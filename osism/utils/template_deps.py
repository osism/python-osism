# SPDX-License-Identifier: Apache-2.0

"""Which variables a raw Ansible value refers to, found without rendering it.

Uses ``jinja2.Environment().parse()`` and walks the tree. Do not use
``jinja2.meta.find_undeclared_variables``: it runs the code generator,
which raises on any filter the Environment does not know (every Ansible
filter), and it reports ``vars``/``hostvars`` instead of the subscript
target.

Names bound inside the template (loop targets, ``{% set %}``) are tracked
per scope and in statement order. A later binding never hides an earlier
reference.

``vars`` and ``hostvars`` are modelled only as the base of these accesses:
a subscript or attribute (``vars['x']``, ``hostvars[h].x``), ``.get(x)``,
``lookup('vars', x)`` and ``map('extract', hostvars, x)``. Any other use
(the bare name, an alias, ``vars.items()``, ``hostvars[h]`` on its own)
can reach every variable, so it makes the value unanalysable.
"""

import collections
from dataclasses import dataclass, field
from typing import Any

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

_ENV = Environment()
_GLOBALS = frozenset(
    {
        "groups",
        "group_names",
        "inventory_hostname",
        "omit",
        "lookup",
        "query",
        "q",
        "range",
        "dict",
        "lipsum",
        "cycler",
        "joiner",
        "namespace",
        "true",
        "false",
        "none",
        "True",
        "False",
        "None",
    }
)
_LOOKUPS = frozenset({"lookup", "query", "q"})
_VARS_LOOKUPS = frozenset({"vars", "ansible.builtin.vars", "ansible.legacy.vars"})
_VARIABLE_MAPS = frozenset({"vars", "hostvars"})
# Jinja's getattr prefers a Python attribute over a key, so vars.items is
# the method, not a variable named "items". HostVars adds raw_get.
_MAPPING_ATTRS = frozenset(
    a
    for a in dir(dict) + dir(collections.ChainMap) + ["raw_get"]
    if not a.startswith("_")
)
# Statements whose scoping this walker does not model; their presence makes
# the value unanalysable (masked), which is the safe direction.
_UNMODELLED = (nodes.Macro, nodes.CallBlock, nodes.With, nodes.FilterBlock)


_UNSAFE_MARKER = "__ansible_unsafe"


class UnsafeText(str):
    """A value tagged !unsafe: Ansible never templates it, so neither do we."""


def encode_unsafe(obj: Any) -> Any:
    """Keep the !unsafe tag through JSON, which turns UnsafeText into str."""
    if isinstance(obj, UnsafeText):
        return {_UNSAFE_MARKER: str(obj)}
    if isinstance(obj, dict):
        return {k: encode_unsafe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [encode_unsafe(v) for v in obj]
    return obj


def _is_unsafe(raw: Any) -> bool:
    return isinstance(raw, UnsafeText) or (
        isinstance(raw, dict) and set(raw) == {_UNSAFE_MARKER}
    )


@dataclass(frozen=True)
class DynamicKey:
    expression: str | None
    cross_host: bool
    # Inside a default/d filter's base or argument.
    defaulted: bool = False


@dataclass(frozen=True)
class Refs:
    names: frozenset = field(default_factory=frozenset)
    cross_host_names: frozenset = field(default_factory=frozenset)
    dynamic_keys: tuple = ()
    unanalysable: bool = False
    # Referenced names (either scope) inside a default/d filter's base or
    # argument: if undefined, the value falls back.
    defaulted: frozenset = field(default_factory=frozenset)


_DEFAULT_FILTERS = frozenset({"default", "d"})


class _Acc:
    def __init__(self) -> None:
        self.names: set = set()
        self.cross: set = set()
        self.dynamic: list = []
        self.defaulted: set = set()
        self.defaulting = 0
        self.unanalysable = False

    def add(self, name: str, cross: bool = False) -> None:
        (self.cross if cross else self.names).add(name)
        if self.defaulting:
            self.defaulted.add(name)

    def add_dynamic(self, expression: str | None, cross: bool) -> None:
        self.dynamic.append(
            DynamicKey(expression, cross, defaulted=bool(self.defaulting))
        )


def references(raw: Any) -> Refs:
    acc = _Acc()
    _collect(raw, acc)
    return Refs(
        names=frozenset(acc.names),
        cross_host_names=frozenset(acc.cross),
        dynamic_keys=tuple(acc.dynamic),
        defaulted=frozenset(acc.defaulted),
        unanalysable=acc.unanalysable,
    )


def _collect(raw: Any, acc: _Acc) -> None:
    if _is_unsafe(raw):
        return
    if isinstance(raw, dict):
        for value in raw.values():
            _collect(value, acc)
    elif isinstance(raw, list):
        for value in raw:
            _collect(value, acc)
    elif isinstance(raw, str) and ("{{" in raw or "{%" in raw):
        try:
            tree = _ENV.parse(raw)
        except TemplateSyntaxError:
            acc.unanalysable = True
            return
        _walk_body(tree.body, acc, frozenset())


def _target_names(target: nodes.Node) -> set:
    found = {n.name for n in target.find_all(nodes.Name)}
    if isinstance(target, nodes.Name):
        found.add(target.name)
    return found


def _walk_body(body: list, acc: _Acc, bound: frozenset) -> None:
    """Statements in order: a {% set %} binds only for what follows it."""
    current = set(bound)
    for stmt in body:
        if isinstance(stmt, nodes.Assign):
            _walk(stmt.node, acc, frozenset(current))
            current |= _target_names(stmt.target)
        elif isinstance(stmt, nodes.AssignBlock):
            _walk_body(stmt.body, acc, frozenset(current))
            current |= _target_names(stmt.target)
        else:
            _walk(stmt, acc, frozenset(current))


def _hostvars_host(base: nodes.Node):
    """For hostvars[H] / hostvars.H return (True, cross_host); else (False, None)."""
    if isinstance(base, nodes.Getitem) and _is_name(base.node, "hostvars"):
        return True, not _is_name(base.arg, "inventory_hostname")
    if (
        isinstance(base, nodes.Getattr)
        and _is_name(base.node, "hostvars")
        and not _is_mapping_attr(base.attr)
    ):
        return True, True
    return False, None


def _is_mapping_attr(attr: str) -> bool:
    return attr.startswith("_") or attr in _MAPPING_ATTRS


def _variable_map(base: nodes.Node, acc: _Acc, bound: frozenset):
    """If base is vars or hostvars[H]/hostvars.H, walk H and return cross_host.

    Returns None when base is not one of them.
    """
    if _is_name(base, "vars") and "vars" not in bound:
        return False
    is_hostvars, cross = _hostvars_host(base)
    if not is_hostvars or "hostvars" in bound:
        return None
    if isinstance(base, nodes.Getitem):
        _walk(base.arg, acc, bound)
    return bool(cross)


def _walk_call_rest(node: nodes.Call, args: list, acc: _Acc, bound) -> None:
    if node.dyn_args is not None or node.dyn_kwargs is not None:
        # *args/**kwargs may carry further variable names.
        acc.unanalysable = True
    for arg in args:
        _walk(arg, acc, bound)
    for kwarg in node.kwargs:
        _walk(kwarg, acc, bound)
    for dyn in (node.dyn_args, node.dyn_kwargs):
        if dyn is not None:
            _walk(dyn, acc, bound)


def _is_name(node: nodes.Node, name: str) -> bool:
    return isinstance(node, nodes.Name) and node.name == name


def _walk(node: nodes.Node, acc: _Acc, bound: frozenset) -> None:
    if isinstance(node, _UNMODELLED):
        acc.unanalysable = True
        return
    if isinstance(node, nodes.For):
        _walk(node.iter, acc, bound)
        inner = bound | _target_names(node.target) | {"loop"}
        if node.test is not None:
            _walk(node.test, acc, inner)
        _walk_body(node.body, acc, inner)
        _walk_body(node.else_, acc, bound)
        return
    if isinstance(node, nodes.If):
        _walk(node.test, acc, bound)
        _walk_body(node.body, acc, bound)
        for elif_ in node.elif_:
            _walk(elif_, acc, bound)
        _walk_body(node.else_, acc, bound)
        return
    if isinstance(node, (nodes.Getitem, nodes.Getattr)):
        cross = _variable_map(node.node, acc, bound)
        if cross is not None:
            if isinstance(node, nodes.Getattr):
                if _is_mapping_attr(node.attr):
                    acc.unanalysable = True
                else:
                    acc.add(node.attr, cross)
            else:
                _target(node.arg, acc, cross, bound)
            return
    if isinstance(node, nodes.Call) and _walk_call(node, acc, bound):
        return
    if isinstance(node, nodes.Filter) and _walk_map_extract(node, acc, bound):
        return
    if isinstance(node, nodes.Filter) and node.name in _DEFAULT_FILTERS:
        acc.defaulting += 1
        try:
            for child in node.iter_child_nodes():
                _walk(child, acc, bound)
        finally:
            acc.defaulting -= 1
        return
    if isinstance(node, nodes.Name) and node.ctx == "load":
        if node.name in bound:
            return
        if node.name in _VARIABLE_MAPS:
            # Not the base of a modelled access: it can reach anything.
            acc.unanalysable = True
        elif node.name not in _GLOBALS:
            acc.add(node.name)
        return
    for child in node.iter_child_nodes():
        _walk(child, acc, bound)


def _walk_call(node: nodes.Call, acc: _Acc, bound: frozenset) -> bool:
    """lookup('vars', ...) and <vars or hostvars[H]>.get(key, ...)."""
    callee = node.node
    if (
        isinstance(callee, nodes.Name)
        and callee.name in _LOOKUPS
        and callee.name not in bound
        and node.args
        and _const(node.args[0]) in _VARS_LOOKUPS
    ):
        for arg in node.args[1:]:
            _target(arg, acc, False, bound)
        _walk_call_rest(node, [], acc, bound)
        return True
    if isinstance(callee, nodes.Getattr) and callee.attr == "get" and node.args:
        cross = _variable_map(callee.node, acc, bound)
        if cross is None:
            return False
        _target(node.args[0], acc, cross, bound)
        _walk_call_rest(node, node.args[1:], acc, bound)
        return True
    return False


def _walk_map_extract(node: nodes.Filter, acc: _Acc, bound: frozenset) -> bool:
    """seq | map('extract', hostvars, key) and seq | map('extract', vars).

    extract(item, container, morekeys) is container[item][morekeys...]:
    with hostvars the items are hosts and the first key component is the
    variable; with vars the items are the variables.
    """
    args = node.args
    if not (
        node.name == "map"
        and len(args) >= 2
        and _const(args[0]) == "extract"
        and isinstance(args[1], nodes.Name)
        and args[1].name in _VARIABLE_MAPS
        and args[1].name not in bound
    ):
        return False
    if args[1].name == "hostvars":
        if node.node is not None:
            _walk(node.node, acc, bound)
        key = _first_key(args[2]) if len(args) >= 3 else None
        if key is None:
            acc.unanalysable = True
        else:
            acc.add(key, cross=True)
    else:
        items = node.node
        if isinstance(items, (nodes.List, nodes.Tuple)) and all(
            isinstance(_const(i), str) for i in items.items
        ):
            for item in items.items:
                acc.add(_const(item))
        else:
            acc.unanalysable = True
            if items is not None:
                _walk(items, acc, bound)
    for arg in args[2:]:
        _walk(arg, acc, bound)
    for kwarg in node.kwargs:
        _walk(kwarg, acc, bound)
    if node.dyn_args is not None or node.dyn_kwargs is not None:
        acc.unanalysable = True
    return True


def _first_key(key: nodes.Node) -> str | None:
    if isinstance(key, (nodes.List, nodes.Tuple)):
        if not key.items:
            return None
        key = key.items[0]
    value = _const(key)
    return value if isinstance(value, str) else None


def _const(node: nodes.Node) -> Any:
    return node.value if isinstance(node, nodes.Const) else None


def _target(key: nodes.Node, acc: _Acc, cross: bool, bound: frozenset) -> None:
    value = _const(key)
    if isinstance(value, str):
        acc.add(value, cross)
        return
    # A key that uses a template-bound name ({% set %}, a loop target) cannot
    # be resolved as a standalone expression: it would read the host's
    # variable of that name instead of the local binding. Unresolvable.
    uses_bound = bool(_target_names(key) & bound)
    expression = None if uses_bound else _unparse(key)
    acc.add_dynamic(expression, cross)
    _walk(key, acc, bound)


def _unparse(node: nodes.Node) -> str | None:
    if isinstance(node, nodes.Const):
        return repr(node.value)
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Getattr):
        inner = _unparse(node.node)
        return None if inner is None else f"{inner}.{node.attr}"
    if isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const):
        inner = _unparse(node.node)
        return None if inner is None else f"{inner}[{node.arg.value!r}]"
    if isinstance(node, nodes.Add):
        left, right = _unparse(node.left), _unparse(node.right)
        return None if left is None or right is None else f"{left} + {right}"
    if isinstance(node, nodes.Concat):
        parts = [_unparse(p) for p in node.nodes]
        return (
            None
            if any(p is None for p in parts)
            else " ~ ".join(parts)  # type: ignore[arg-type]
        )
    if (
        isinstance(node, nodes.Filter)
        and node.node is not None
        and not node.args
        and not node.kwargs
    ):
        inner = _unparse(node.node)
        return None if inner is None else f"{inner} | {node.name}"
    return None
