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
"""

from dataclasses import dataclass, field
from typing import Any

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

_ENV = Environment()
_GLOBALS = frozenset(
    {
        "vars",
        "hostvars",
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
# Statements whose scoping this walker does not model; their presence makes
# the value unanalysable (masked), which is the safe direction.
_UNMODELLED = (nodes.Macro, nodes.CallBlock, nodes.With, nodes.FilterBlock)


@dataclass(frozen=True)
class DynamicKey:
    expression: str | None
    cross_host: bool


@dataclass(frozen=True)
class Refs:
    names: frozenset = field(default_factory=frozenset)
    cross_host_names: frozenset = field(default_factory=frozenset)
    dynamic_keys: tuple = ()
    unanalysable: bool = False


class _Acc:
    def __init__(self) -> None:
        self.names: set = set()
        self.cross: set = set()
        self.dynamic: list = []
        self.unanalysable = False


def references(raw: Any) -> Refs:
    acc = _Acc()
    _collect(raw, acc)
    return Refs(
        names=frozenset(acc.names),
        cross_host_names=frozenset(acc.cross),
        dynamic_keys=tuple(acc.dynamic),
        unanalysable=acc.unanalysable,
    )


def _collect(raw: Any, acc: _Acc) -> None:
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
    if isinstance(base, nodes.Getattr) and _is_name(base.node, "hostvars"):
        return True, True
    return False, None


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
        base = node.node
        is_hostvars, cross = _hostvars_host(base)
        if _is_name(base, "vars") or is_hostvars:
            if is_hostvars and isinstance(base, nodes.Getitem):
                _walk(base.arg, acc, bound)
            if isinstance(node, nodes.Getattr):
                (acc.cross if cross else acc.names).add(node.attr)
            else:
                _target(node.arg, acc, bool(cross), bound)
            return
    if isinstance(node, nodes.Call) and isinstance(node.node, nodes.Name):
        if node.node.name in _LOOKUPS and node.args and _const(node.args[0]) == "vars":
            for arg in node.args[1:]:
                _target(arg, acc, False, bound)
            return
    if isinstance(node, nodes.Name) and node.ctx == "load":
        if node.name not in _GLOBALS and node.name not in bound:
            acc.names.add(node.name)
        return
    for child in node.iter_child_nodes():
        _walk(child, acc, bound)


def _const(node: nodes.Node) -> Any:
    return node.value if isinstance(node, nodes.Const) else None


def _target(key: nodes.Node, acc: _Acc, cross: bool, bound: frozenset) -> None:
    value = _const(key)
    if isinstance(value, str):
        (acc.cross if cross else acc.names).add(value)
        return
    # A key that uses a template-bound name ({% set %}, a loop target) cannot
    # be resolved as a standalone expression: it would read the host's
    # variable of that name instead of the local binding. Unresolvable.
    uses_bound = bool(_target_names(key) & bound)
    expression = None if uses_bound else _unparse(key)
    acc.dynamic.append(DynamicKey(expression=expression, cross_host=cross))
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
