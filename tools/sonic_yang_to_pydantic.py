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
from typing import List, Optional, Tuple

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


def generate_table(table_container) -> Tuple[str, str, str]:
    """Generate code for one ConfigDB table container.
    Returns (table_name, table_class, code_block).

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

    if lists:
        for lst in lists:
            row_class = to_class_name(lst.arg) + "Row"
            parts.append(generate_row_class(row_class, collect_leaves(lst)))
            row_classes.append(row_class)
    elif sub_containers:
        for sc in sub_containers:
            row_class = base + to_class_name(sc.arg) + "Row"
            parts.append(generate_row_class(row_class, collect_leaves(sc)))
            row_classes.append(row_class)
    else:
        raise ValueError(f"table {table_name} has neither list nor container children")

    table_class = f"{base}Table"
    if len(row_classes) == 1:
        row_type = row_classes[0]
    else:
        row_type = f"Union[{', '.join(row_classes)}]"
    parts.append(f"class {table_class}(RootModel[Dict[str, {row_type}]]):\n    pass\n")

    return table_name, table_class, "\n".join(parts)


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
    skipped: List[Tuple[str, str]] = []
    seen_tables: set = set()

    for path, module, container in find_table_containers(modules):
        try:
            table_name, table_class, code = generate_table(container)
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

    init_file = output / "__init__.py"
    init_file.write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# AUTO-GENERATED — DO NOT EDIT BY HAND.\n"
        '"""Generated SONiC ConfigDB schemas."""\n\n'
        "from ._schemas import TABLE_MODELS\n\n"
        '__all__ = ["TABLE_MODELS"]\n'
    )

    print(f"Wrote {len(registry)} table models -> {out_file}")
    if skipped:
        print(f"Skipped {len(skipped)} containers:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    format_with_black(out_file, init_file)
    return 0


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
