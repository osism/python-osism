#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate Pydantic v2 validators from SONiC YANG models.

Walks the AST produced by pyang and emits a self-contained Pydantic schema
for every ConfigDB table defined in the YANG models. The generator output is
committed to the repository so the runtime needs zero YANG tooling — only
pydantic.

pyang and black are not runtime dependencies of python-osism; install them
ad-hoc when regenerating schemas:

    pip install pyang black
    python tools/sonic_yang_to_pydantic.py \
        --yang-dir files/sonic/yang_models \
        --output osism/tasks/conductor/sonic/_generated
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pyang import context, repository  # type: ignore[import-untyped]

HEADER_PREFIX = '''\
# SPDX-License-Identifier: Apache-2.0
# AUTO-GENERATED — DO NOT EDIT BY HAND.
# Regenerate with: python tools/sonic_yang_to_pydantic.py
# flake8: noqa: E501
"""SONiC ConfigDB Pydantic schemas, generated from files/sonic/yang_models."""

'''

TYPING_NAMES = ("Annotated", "Any", "Dict", "List", "Literal", "Optional", "Union")

YANG_INT_BOUNDS = {
    "int8": (-(2**7), 2**7 - 1),
    "int16": (-(2**15), 2**15 - 1),
    "int32": (-(2**31), 2**31 - 1),
    "int64": (-(2**63), 2**63 - 1),
    "uint8": (0, 2**8 - 1),
    "uint16": (0, 2**16 - 1),
    "uint32": (0, 2**32 - 1),
    "uint64": (0, 2**64 - 1),
}

PY_KEYWORDS = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
    "match",
    "case",
}


def to_class_name(yang_name: str) -> str:
    """`SOME_TABLE_NAME` or `sonic-port` → `SomeTableName` / `SonicPort`."""
    parts = re.split(r"[-_]", yang_name)
    return "".join(p[0:1].upper() + p[1:].lower() for p in parts if p)


def safe_field_name(yang_name: str) -> Tuple[str, Optional[str]]:
    """Return (python_field_name, alias_or_None) for a YANG identifier."""
    name = yang_name.replace("-", "_")
    if name in PY_KEYWORDS or not name.isidentifier():
        return f"{name}_", yang_name
    if name != yang_name:
        return name, yang_name
    return name, None


@dataclass
class PyType:
    annotation: str  # e.g. "str", "Annotated[int, Field(ge=1, le=100)]"


@dataclass(frozen=True)
class LeafrefConstraint:
    """One cross-table reference: ``source_table.source_field`` must point at
    an existing key in *one of* ``targets`` (modeled as YANG `union of leafref`).

    ``is_leaf_list`` flags element-wise checks; ``source_is_simple_key`` is
    true when the source leaf is the sole `key` of its YANG list, so the row
    key in ConfigDB JSON directly carries the value.

    ``plain_arms`` carries the non-leafref arms of a union — a union accepts a
    value if *any* arm does, so a value one of these admits is legal even
    though it resolves to no target. Each arm is the tuple of YANG patterns
    that arm imposes; YANG requires every pattern of an arm to match, so an
    arm matches when all of its patterns do, and an *empty* arm therefore
    matches everything. See :func:`extract_union_plain_arms`.
    """

    source_table: str
    source_field: str
    targets: Tuple[Tuple[str, str], ...]
    is_leaf_list: bool = False
    source_is_simple_key: bool = False
    plain_arms: Tuple[Tuple[str, ...], ...] = ()

    @property
    def is_vacuous(self) -> bool:
        """True when a plain arm admits any string, making the leafref
        unenforceable: every value is legal via that arm."""
        return any(len(arm) == 0 for arm in self.plain_arms)


def parse_leafref_path(path: str) -> Optional[Tuple[str, str]]:
    """Parse a YANG `leafref` XPath and return ``(target_table, target_field)``.

    Handles the regular SONiC shape::

        /<prefix>:sonic-X/<prefix>:TABLE/<prefix>:TABLE_LIST/<prefix>:field

    Returns ``None`` for relative paths (`../...`) and for any path containing
    XPath predicates (`[...]`) — those need richer resolution and are tracked
    as separate follow-ups.
    """
    p = path.strip().strip('"').strip("'")
    if not p.startswith("/"):
        return None
    if "[" in p or "]" in p:
        return None
    parts = [seg for seg in p.lstrip("/").split("/") if seg]
    if len(parts) < 4:
        return None
    bare = [seg.split(":", 1)[-1] for seg in parts]
    return bare[1], bare[-1]


def extract_leafref_targets(type_stmt) -> List[Tuple[str, str]]:
    """Walk a YANG `type` statement and return every leafref target it
    declares — directly, via `union`, or via a typedef. Order is preserved
    and duplicates are removed."""
    base = type_stmt.arg
    if base == "leafref":
        path_stmt = type_stmt.search_one("path")
        if path_stmt is None:
            return []
        parsed = parse_leafref_path(path_stmt.arg)
        return [parsed] if parsed else []
    if base == "union":
        out: List[Tuple[str, str]] = []
        seen: set = set()
        for s in type_stmt.substmts:
            if s.keyword != "type":
                continue
            for tgt in extract_leafref_targets(s):
                if tgt not in seen:
                    seen.add(tgt)
                    out.append(tgt)
        return out
    td = getattr(type_stmt, "i_typedef", None)
    if td is not None:
        inner = td.search_one("type")
        if inner is not None:
            return extract_leafref_targets(inner)
    return []


def extract_union_plain_arms(type_stmt) -> List[Tuple[str, ...]]:
    """Return one entry per non-leafref arm of a union, as that arm's patterns.

    A YANG `union` accepts a value if any arm accepts it, so the leafref arms
    of a mixed union constrain only the values no plain arm admits. The
    generator therefore has to keep the plain arms rather than discard them —
    dropping them makes a legal value look like a dangling reference, and
    dropping the whole constraint instead gives up checks the plain arms
    barely widen (`PFC_WD.ifname` is a PORT leafref unioned with the single
    literal `GLOBAL`).

    An arm is represented by the YANG patterns it imposes; YANG requires all
    of them to match. An arm that restricts nothing a pattern can
    express — a bare `string`, or a numeric or boolean type we do not render —
    yields an empty tuple, which matches everything and so renders the whole
    constraint unenforceable (:attr:`LeafrefConstraint.is_vacuous`).
    `length` restrictions are not rendered either; ignoring them only widens
    what an arm admits, which costs coverage rather than causing false errors.
    """
    base = type_stmt.arg
    if base == "leafref":
        return []
    if base == "union":
        arms: List[Tuple[str, ...]] = []
        for s in type_stmt.substmts:
            if s.keyword == "type":
                arms.extend(extract_union_plain_arms(s))
        return arms
    td = getattr(type_stmt, "i_typedef", None)
    if td is not None:
        inner = td.search_one("type")
        if inner is not None:
            return extract_union_plain_arms(inner)
    if base == "enumeration":
        enums = [s.arg for s in type_stmt.substmts if s.keyword == "enum"]
        if enums:
            return [("|".join(re.escape(e) for e in enums),)]
        return [()]
    if base == "string":
        return [tuple(s.arg for s in type_stmt.substmts if s.keyword == "pattern")]
    return [()]


# Values the generator matches each pattern against to confirm the runtime
# engine reads it the way YANG means it. Not a proof — a smoke check wide
# enough to catch the ways the two dialects are known to diverge: unanchored
# matching, and Unicode category escapes such as `\\p{N}`.
PATTERN_PROBES = (
    "10.0.0.1",
    "999.1.1.1",
    "10.0.0.1%eth0",
    "fe80::1",
    "Ethernet0",
    "Vlan100",
    "Vlan4095",
    "default",
    "GLOBAL",
    "",
    " ",
    "10.0.0.1\n",
    "\n10.0.0.1",
)


def render_arm_pattern(pattern: str) -> str:
    """Return *pattern* in the form the validator will match it in.

    Two things happen here rather than at runtime, so that exactly one place
    knows how a YANG pattern becomes a runtime one and the two cannot drift.

    First, the pattern is anchored: XSD patterns match a whole value, while
    the pydantic engine the validator uses searches, which would accept
    `999.1.1.1` for an IPv4 arm.

    Second, generation fails unless both engines then agree. pyang carries a
    conformant XSD matcher (libxml2 via lxml), so a dialect difference — the
    Unicode escapes in `inet:ip-address`, say — is settled here as a build
    failure instead of surfacing in the validator as a wrong error about a
    real config.
    """
    from typing import Annotated

    from pyang.types import XSDPattern  # generation-time only, not a runtime dep
    from pydantic import StringConstraints, TypeAdapter, ValidationError

    reference = XSDPattern(pattern, pos=None, invert_match=False)
    if not reference:
        raise ValueError(f"not a valid XSD pattern: {pattern!r} ({reference.error})")

    rendered = rf"\A(?:{pattern})\z"
    adapter: TypeAdapter[str] = TypeAdapter(
        Annotated[str, StringConstraints(pattern=rendered)]
    )
    for probe in PATTERN_PROBES:
        try:
            adapter.validate_python(probe)
            got = True
        except ValidationError:
            got = False
        if got != reference(probe):
            raise ValueError(
                f"pattern {pattern!r} reads differently at runtime: XSD says "
                f"{reference(probe)} for {probe!r}, the validator says {got}"
            )
    return rendered


def list_keys(list_stmt) -> List[str]:
    """Return the leaf names that form a YANG `list`'s key (empty if none)."""
    key_stmt = list_stmt.search_one("key")
    if key_stmt is None:
        return []
    return key_stmt.arg.split()


def collect_leafref_constraints(
    table_name: str, list_or_container, leaves
) -> List[LeafrefConstraint]:
    """Inspect the leaves of one row schema and emit leafref constraints."""
    if list_or_container.keyword == "list":
        keys = list_keys(list_or_container)
    else:
        keys = []
    constraints: List[LeafrefConstraint] = []
    for leaf in leaves:
        type_stmt = leaf.search_one("type")
        if type_stmt is None:
            continue
        targets = extract_leafref_targets(type_stmt)
        if not targets:
            continue
        # Drop targets that point back at the same source (no-op self-refs).
        targets = [t for t in targets if t != (table_name, leaf.arg)]
        if not targets:
            continue
        is_simple_key = len(keys) == 1 and leaf.arg == keys[0]
        plain_arms = tuple(
            tuple(render_arm_pattern(p) for p in arm)
            for arm in extract_union_plain_arms(type_stmt)
        )
        constraints.append(
            LeafrefConstraint(
                source_table=table_name,
                source_field=leaf.arg,
                targets=tuple(targets),
                is_leaf_list=(leaf.keyword == "leaf-list"),
                source_is_simple_key=is_simple_key,
                plain_arms=plain_arms,
            )
        )
    return constraints


def parse_range_part(part: str) -> Tuple[Optional[int], Optional[int]]:
    part = part.strip()
    if ".." in part:
        lo, hi = part.split("..", 1)
        return parse_int(lo), parse_int(hi)
    v = parse_int(part)
    return v, v


def parse_range(arg: str) -> List[Tuple[Optional[int], Optional[int]]]:
    return [parse_range_part(p) for p in arg.split("|")]


def parse_int(s: str) -> Optional[int]:
    s = s.strip()
    if s in ("min", "max"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def coalesce_bounds(
    ranges: List[Tuple[Optional[int], Optional[int]]],
) -> Tuple[Optional[int], Optional[int]]:
    los = [r[0] for r in ranges if r[0] is not None]
    his = [r[1] for r in ranges if r[1] is not None]
    return (min(los) if los else None, max(his) if his else None)


def yang_type_to_py(type_stmt) -> PyType:  # noqa: C901
    base = type_stmt.arg

    if base == "union":
        members = []
        for s in type_stmt.substmts:
            if s.keyword == "type":
                members.append(yang_type_to_py(s).annotation)
        # de-dup while preserving order
        seen = set()
        unique = []
        for m in members:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        if not unique:
            return PyType("Any")
        if len(unique) == 1:
            return PyType(unique[0])
        return PyType(f"Union[{', '.join(unique)}]")

    if base == "leafref":
        # No type-level cross-table check — leafref is most often a string key.
        return PyType("str")

    if base == "enumeration":
        enums = [s.arg for s in type_stmt.substmts if s.keyword == "enum"]
        if enums:
            return PyType("Literal[" + ", ".join(repr(e) for e in enums) + "]")
        return PyType("str")

    # typedef reference (prefixed or local)
    td = getattr(type_stmt, "i_typedef", None)
    if td is not None:
        inner = td.search_one("type")
        if inner is not None:
            return yang_type_to_py(inner)

    if base == "decimal64":
        return PyType("float")

    if base == "boolean":
        return PyType("bool")

    if base in YANG_INT_BOUNDS:
        rng = type_stmt.search_one("range")
        if rng:
            ranges = parse_range(rng.arg)
            lo, hi = coalesce_bounds(ranges)
        else:
            lo, hi = YANG_INT_BOUNDS[base]
        parts = []
        if lo is not None:
            parts.append(f"ge={lo}")
        if hi is not None:
            parts.append(f"le={hi}")
        if parts:
            return PyType(f"Annotated[int, Field({', '.join(parts)})]")
        return PyType("int")

    if base == "string":
        constraints = []
        length = type_stmt.search_one("length")
        if length:
            lengths = parse_range(length.arg)
            lo, hi = coalesce_bounds(lengths)
            if lo is not None:
                constraints.append(f"min_length={lo}")
            if hi is not None:
                constraints.append(f"max_length={hi}")
        patterns = [s.arg for s in type_stmt.substmts if s.keyword == "pattern"]
        # YANG allows multiple pattern statements (all must match). Pydantic's
        # StringConstraints accepts only one, so we apply a single pattern when
        # there is exactly one; otherwise we drop the regex constraint and keep
        # length checks. A future iteration could emit a model_validator.
        if len(patterns) == 1:
            constraints.append(f"pattern={patterns[0]!r}")
        if constraints:
            return PyType(
                f"Annotated[str, StringConstraints({', '.join(constraints)})]"
            )
        return PyType("str")

    # binary / bits / instance-identifier / identityref / empty / unknown
    return PyType("str")


def is_mandatory(stmt) -> bool:
    m = stmt.search_one("mandatory")
    return m is not None and m.arg == "true"


def default_for_type(default_arg: str, annotation: str) -> str:
    """Render a YANG default value as a Python literal compatible with the
    field's annotation. Falls back to a string literal."""
    ann_lower = annotation.lower()
    if "literal[" in annotation:
        return repr(default_arg)
    if "bool" in ann_lower and "boolean" not in default_arg.lower():
        if default_arg.lower() == "true":
            return "True"
        if default_arg.lower() == "false":
            return "False"
    if "int]" in annotation or annotation == "int" or "Field(ge=" in annotation:
        try:
            int(default_arg)
            return default_arg
        except ValueError:
            pass
    if annotation == "float":
        try:
            float(default_arg)
            return default_arg
        except ValueError:
            pass
    return repr(default_arg)


def leaf_field_decl(leaf_stmt) -> str:
    py = (
        yang_type_to_py(leaf_stmt.search_one("type"))
        if leaf_stmt.search_one("type")
        else PyType("Any")
    )
    field_name, alias = safe_field_name(leaf_stmt.arg)
    mandatory = is_mandatory(leaf_stmt)
    default_stmt = leaf_stmt.search_one("default")

    if mandatory:
        annotation = py.annotation
        if alias:
            return f"    {field_name}: {annotation} = Field(alias={alias!r})"
        return f"    {field_name}: {annotation}"

    annotation = f"Optional[{py.annotation}]"
    if default_stmt is not None:
        default_repr = default_for_type(default_stmt.arg, py.annotation)
    else:
        default_repr = "None"
    if alias:
        return (
            f"    {field_name}: {annotation} = "
            f"Field(default={default_repr}, alias={alias!r})"
        )
    return f"    {field_name}: {annotation} = {default_repr}"


def leaf_list_field_decl(stmt) -> str:
    py = (
        yang_type_to_py(stmt.search_one("type"))
        if stmt.search_one("type")
        else PyType("Any")
    )
    field_name, alias = safe_field_name(stmt.arg)
    annotation = f"Optional[List[{py.annotation}]]"
    if alias:
        return (
            f"    {field_name}: {annotation} = " f"Field(default=None, alias={alias!r})"
        )
    return f"    {field_name}: {annotation} = None"


def iter_resolved_children(stmt):
    """Iterate the resolved children of a YANG statement (uses/grouping expanded)."""
    children = getattr(stmt, "i_children", None)
    if children is not None:
        return list(children)
    return list(stmt.substmts)


def collect_leaves(stmt):
    """Recursively collect leaf / leaf-list statements from inside a stmt.

    Used for the singleton-container pattern (DEVICE_METADATA → localhost → leafs)
    where a row's fields live one or more containers deep.
    """
    out = []
    for child in iter_resolved_children(stmt):
        if child.keyword in ("leaf", "leaf-list"):
            out.append(child)
        elif child.keyword == "container":
            out.extend(collect_leaves(child))
    return out


def generate_row_class(class_name: str, leaves) -> str:
    rows = []
    for leaf in leaves:
        if leaf.keyword == "leaf":
            rows.append(leaf_field_decl(leaf))
        elif leaf.keyword == "leaf-list":
            rows.append(leaf_list_field_decl(leaf))
    if not rows:
        rows = ["    pass"]
    return (
        f"class {class_name}(BaseModel):\n"
        f"    model_config = ConfigDict(extra='allow', populate_by_name=True)\n\n"
        + "\n".join(rows)
        + "\n"
    )


def generate_table(
    table_container,
) -> Tuple[str, str, str, List[LeafrefConstraint]]:
    """Generate code for one ConfigDB table container.
    Returns (table_name, table_class, code_block, leafref_constraints).

    Two patterns are recognised:
      1. table → list+ → leafs           (most common, e.g. PORT)
      2. table → container+ → leafs      (singleton/fixed-key, e.g. DEVICE_METADATA)
    """
    table_name = table_container.arg
    base = to_class_name(table_name)
    children = iter_resolved_children(table_container)
    lists = [s for s in children if s.keyword == "list"]
    sub_containers = [s for s in children if s.keyword == "container"]

    parts: List[str] = []
    row_classes: List[str] = []
    constraints: List[LeafrefConstraint] = []

    if lists:
        for lst in lists:
            row_class = to_class_name(lst.arg) + "Row"
            leaves = collect_leaves(lst)
            parts.append(generate_row_class(row_class, leaves))
            row_classes.append(row_class)
            constraints.extend(collect_leafref_constraints(table_name, lst, leaves))
    elif sub_containers:
        for sc in sub_containers:
            row_class = base + to_class_name(sc.arg) + "Row"
            leaves = collect_leaves(sc)
            parts.append(generate_row_class(row_class, leaves))
            row_classes.append(row_class)
            constraints.extend(collect_leafref_constraints(table_name, sc, leaves))
    else:
        raise ValueError(f"table {table_name} has neither list nor container children")

    table_class = f"{base}Table"
    if len(row_classes) == 1:
        row_type = row_classes[0]
    else:
        row_type = f"Union[{', '.join(row_classes)}]"
    parts.append(f"class {table_class}(RootModel[Dict[str, {row_type}]]):\n    pass\n")

    return table_name, table_class, "\n".join(parts), constraints


def load_yang_modules(yang_dir: Path):
    repo = repository.FileRepository(str(yang_dir))
    ctx = context.Context(repo)
    modules = []
    for path in sorted(yang_dir.glob("*.yang")):
        with open(path) as f:
            text = f.read()
        m = ctx.add_module(str(path), text)
        if m is not None:
            modules.append((path, m))
    ctx.validate()
    return ctx, modules


def find_table_containers(modules):
    """Yield (yang_path, module, table_container) for every ConfigDB table.

    A "table container" is a container two levels deep inside a module
    (module → container sonic-X → container TABLE_NAME) and contains either
    list children or container children (singleton-row tables).
    """
    for path, module in modules:
        for top in module.substmts:
            if top.keyword != "container":
                continue
            for child in iter_resolved_children(top):
                if child.keyword != "container":
                    continue
                inner = iter_resolved_children(child)
                has_list = any(s.keyword == "list" for s in inner)
                has_container = any(s.keyword == "container" for s in inner)
                if has_list or has_container:
                    yield path, module, child


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yang-dir",
        default="files/sonic/yang_models",
        help="Directory with sonic-*.yang files",
    )
    parser.add_argument(
        "--output",
        default="osism/tasks/conductor/sonic/_generated",
        help="Output directory for generated Pydantic schemas",
    )
    args = parser.parse_args(argv)

    yang_dir = Path(args.yang_dir).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    print(f"Loading YANG models from {yang_dir}")
    _, modules = load_yang_modules(yang_dir)
    print(f"Loaded {len(modules)} modules")

    code_blocks: List[str] = []
    registry: List[Tuple[str, str]] = []
    leafrefs: List[LeafrefConstraint] = []
    skipped: List[Tuple[str, str]] = []
    seen_tables: set = set()

    for path, module, container in find_table_containers(modules):
        try:
            table_name, table_class, code, table_leafrefs = generate_table(container)
        except Exception as exc:  # pragma: no cover - generator-time only
            skipped.append((container.arg, f"{path.name}: {exc}"))
            continue

        if table_name in seen_tables:
            skipped.append(
                (table_name, f"{path.name}: duplicate table name across modules")
            )
            continue
        seen_tables.add(table_name)

        code_blocks.append(f"\n# {path.name} :: {module.arg} :: {table_name}\n{code}")
        registry.append((table_name, table_class))
        leafrefs.extend(table_leafrefs)

    body = "".join(code_blocks)
    body += "\n\nTABLE_MODELS: Dict[str, type[BaseModel]] = {\n"
    for table_name, table_class in sorted(registry):
        body += f'    "{table_name}": {table_class},\n'
    body += "}\n"

    used_typing = [n for n in TYPING_NAMES if re.search(rf"\b{n}\b", body)]
    typing_import = (
        f"from typing import {', '.join(used_typing)}\n\n" if used_typing else ""
    )
    pydantic_import = "from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints\n\n"
    schema_code = HEADER_PREFIX + typing_import + pydantic_import + body

    out_file = output / "_schemas.py"
    out_file.write_text(schema_code)

    leafrefs_file = output / "_leafrefs.py"
    leafrefs_file.write_text(render_leafrefs_module(leafrefs))

    init_file = output / "__init__.py"
    init_file.write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# AUTO-GENERATED — DO NOT EDIT BY HAND.\n"
        '"""Generated SONiC ConfigDB schemas."""\n\n'
        "from ._leafrefs import LEAFREFS, LeafrefConstraint\n"
        "from ._schemas import TABLE_MODELS\n\n"
        '__all__ = ["LEAFREFS", "LeafrefConstraint", "TABLE_MODELS"]\n'
    )

    print(f"Wrote {len(registry)} table models -> {out_file}")
    print(f"Wrote {len(leafrefs)} leafref constraints -> {leafrefs_file}")
    if skipped:
        print(f"Skipped {len(skipped)} containers:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    format_with_black(out_file, leafrefs_file, init_file)
    return 0


def render_leafrefs_module(constraints: List[LeafrefConstraint]) -> str:
    """Render the auto-generated `_leafrefs.py` module.

    Constraints that share `(source_table, source_field)` — typically because
    a table declares multiple `list` siblings with the same leafref leaf, e.g.
    INTERFACE_LIST and INTERFACE_IPPREFIX_LIST both having `name` →
    PORT/name — are merged: targets and plain arms are unioned and the
    is_leaf_list / source_is_simple_key flags become true if any contributing
    constraint had them set.

    Constraints left unenforceable by a plain arm that admits any string are
    dropped, so the module carries no rule that cannot fail. Merging happens
    first: a sibling list that widens the leaf to a bare string widens it for
    the merged constraint too.
    """
    merged: Dict[Tuple[str, str], LeafrefConstraint] = {}
    for c in constraints:
        key = (c.source_table, c.source_field)
        if key not in merged:
            merged[key] = c
            continue
        existing = merged[key]
        seen: set = set()
        new_targets: List[Tuple[str, str]] = []
        for t in (*existing.targets, *c.targets):
            if t not in seen:
                seen.add(t)
                new_targets.append(t)
        seen_arms: set = set()
        new_arms: List[Tuple[str, ...]] = []
        for arm in (*existing.plain_arms, *c.plain_arms):
            if arm not in seen_arms:
                seen_arms.add(arm)
                new_arms.append(arm)
        merged[key] = LeafrefConstraint(
            source_table=c.source_table,
            source_field=c.source_field,
            targets=tuple(new_targets),
            is_leaf_list=existing.is_leaf_list or c.is_leaf_list,
            source_is_simple_key=existing.source_is_simple_key
            or c.source_is_simple_key,
            plain_arms=tuple(new_arms),
        )

    sorted_constraints = sorted(
        (c for c in merged.values() if not c.is_vacuous),
        key=lambda c: (c.source_table, c.source_field),
    )
    lines: List[str] = []
    lines.append("# SPDX-License-Identifier: Apache-2.0")
    lines.append("# AUTO-GENERATED — DO NOT EDIT BY HAND.")
    lines.append("# Regenerate with: python tools/sonic_yang_to_pydantic.py")
    lines.append("# flake8: noqa: E501")
    lines.append('"""SONiC ConfigDB cross-table leafref constraints."""')
    lines.append("")
    lines.append("from dataclasses import dataclass")
    lines.append("from typing import Tuple")
    lines.append("")
    lines.append("")
    lines.append("@dataclass(frozen=True)")
    lines.append("class LeafrefConstraint:")
    lines.append(
        '    """A leafref from ``source_table.source_field`` to one of ``targets``.'
    )
    lines.append("")
    lines.append(
        "    ``plain_arms`` holds the non-leafref arms of a YANG union, as anchored"
    )
    lines.append(
        "    regexes. A union accepts a value if any arm does, so a value matching"
    )
    lines.append(
        "    one of these is legal without resolving to a target; an arm matches"
    )
    lines.append("    when every pattern in it matches.")
    lines.append('    """')
    lines.append("")
    lines.append("    source_table: str")
    lines.append("    source_field: str")
    lines.append("    targets: Tuple[Tuple[str, str], ...]")
    lines.append("    is_leaf_list: bool = False")
    lines.append("    source_is_simple_key: bool = False")
    lines.append("    plain_arms: Tuple[Tuple[str, ...], ...] = ()")
    lines.append("")
    lines.append("")
    lines.append("LEAFREFS: Tuple[LeafrefConstraint, ...] = (")
    for c in sorted_constraints:
        targets_repr = ", ".join(f"({t[0]!r}, {t[1]!r})" for t in c.targets)
        if len(c.targets) == 1:
            targets_repr += ","
        lines.append("    LeafrefConstraint(")
        lines.append(f"        source_table={c.source_table!r},")
        lines.append(f"        source_field={c.source_field!r},")
        lines.append(f"        targets=({targets_repr}),")
        if c.is_leaf_list:
            lines.append("        is_leaf_list=True,")
        if c.source_is_simple_key:
            lines.append("        source_is_simple_key=True,")
        if c.plain_arms:
            arms_repr = ", ".join(
                "("
                + ", ".join(repr(p) for p in arm)
                + ("," if len(arm) == 1 else "")
                + ")"
                for arm in c.plain_arms
            )
            if len(c.plain_arms) == 1:
                arms_repr += ","
            lines.append(f"        plain_arms=({arms_repr}),")
        lines.append("    ),")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def format_with_black(*paths: Path) -> None:
    """Run `black` on the generated files so the diff stays small and readable."""
    cmd = [sys.executable, "-m", "black", "--quiet", *(str(p) for p in paths)]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "black is required to format generated schemas. "
            "Install it with `pip install black` and re-run."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"black failed on generated schemas: {exc}") from exc
    print(f"Formatted {len(paths)} file(s) with black")


if __name__ == "__main__":
    sys.exit(main())
