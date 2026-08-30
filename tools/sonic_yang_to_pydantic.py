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
import textwrap
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

# ConfigDB carries most YANG leaf-lists as a JSON array, but a handful as a
# single delimited string. Upstream sonic-yang-mgmt keeps the exhaustive table
# of those exceptions and splits on it before handing a config to libyang; this
# mirrors it, so the generated schema accepts what ConfigDB actually holds.
#
# Kept verbatim from LEAF_LIST_WITH_STRING_VALUE_DICT in
# src/sonic-yang-mgmt/sonic_yang_ext.py (sonic-net/sonic-buildimage), including
# the one field that separates on ';' rather than ',': re-check it when the
# vendored YANG models are refreshed. Pairs that are a plain `leaf` in the
# vendored models rather than a `leaf-list` are simply never applied.
LEAF_LIST_STRING_DELIMITERS = {
    ("MIRROR_SESSION", "src_ip"): ",",
    ("NTP", "src_intf"): ";",
    ("BGP_ALLOWED_PREFIXES", "prefixes_v4"): ",",
    ("BGP_ALLOWED_PREFIXES", "prefixes_v6"): ",",
    ("BUFFER_PORT_EGRESS_PROFILE_LIST", "profile_list"): ",",
    ("BUFFER_PORT_INGRESS_PROFILE_LIST", "profile_list"): ",",
    ("PORT", "adv_speeds"): ",",
    ("PORT", "adv_interface_types"): ",",
}

# Tables the vendored models describe differently from the platform OSISM
# targets, and which are therefore left unvalidated rather than validated
# against a model the devices do not implement.
#
# `files/sonic/yang_models/` is vendored from sonic-net/sonic-buildimage —
# community SONiC — while the supported HWSKUs run Enterprise SONiC builds
# (Broadcom lineage, via `frrcfgd` and a translib-derived schema). Most tables
# agree between the two. These do not, and validating them only manufactures
# errors about values the platform considers correct.
#
# Add a table here only with the divergence established against the platform,
# not inferred from our own generated artifacts — the config generator's output
# is not evidence about what the device expects.
PLATFORM_DIVERGENT_TABLES = {
    "SYSLOG_SERVER": (
        "the platform models this table with different field names "
        "(message-type, remote-port, vrf_name) and an uppercase "
        "TCP/UDP/TLS protocol enum"
    ),
    "MGMT_PORT": ("the platform models autoneg as a boolean, not as `on`/`off`"),
}

# Individual leaves the vendored models type differently from the platform,
# where opting the whole table out via PLATFORM_DIVERGENT_TABLES would give up
# too much. Maps (table, leaf) to the annotation the platform actually accepts
# plus the reason, which is emitted as a comment beside the generated field.
#
# Same evidentiary bar as PLATFORM_DIVERGENT_TABLES, and the same trap: our own
# generated configs are not evidence. Each entry needs the platform's own
# schema or its consumer, and a note on what would let it be dropped again.
PLATFORM_DIVERGENT_FIELDS = {
    ("BGP_NEIGHBOR_AF", "admin_status"): (
        'Optional[Literal["true", "false"]] = None',
        "the frr-mgmt-framework CONFIG_DB schema types this leaf true/false, "
        "and frrcfgd only activates the address family for those two tokens; "
        "see docs/sonic-config-validation.md",
    ),
}

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

    ``element_delimiter`` is set when ConfigDB carries this leaf-list as one
    delimited string rather than a JSON array, so the references inside it can
    be resolved separately instead of as one long value.

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
    element_delimiter: Optional[str] = None

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


def collect_table_key_fields(table_container) -> List[Tuple[str, ...]]:
    """Return the key-leaf names of every `list` under one table container.

    ConfigDB joins a list's key values into the row key with `|`, so
    ``BGP_NEIGHBOR_AF|default|10.0.0.2|ipv4_unicast`` carries `vrf_name`,
    `neighbor` and `afi_safi` in that order. Emitting the key leaves lets the
    validator recover those values positionally, which is the only way most
    leafrefs are reachable at all — the referring leaf is usually a key
    component and never appears as a field in the row dict.

    One entry per list, because a table may declare several with different key
    arities (`INTERFACE` has one keyed by name and one by name plus prefix).
    Splitting on `|` and matching on the number of parts tells them apart; no
    table in the vendored models declares two lists of the same arity.
    """
    out: List[Tuple[str, ...]] = []
    for node in iter_resolved_children(table_container):
        if node.keyword != "list":
            continue
        keys = tuple(list_keys(node))
        if keys and keys not in out:
            out.append(keys)
    return out


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
        delimiter = (
            LEAF_LIST_STRING_DELIMITERS.get((table_name, leaf.arg))
            if leaf.keyword == "leaf-list"
            else None
        )
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
                element_delimiter=delimiter,
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


def leaf_field_decl(leaf_stmt, table_name: Optional[str] = None) -> str:
    field_name, alias = safe_field_name(leaf_stmt.arg)

    override = (
        PLATFORM_DIVERGENT_FIELDS.get((table_name, leaf_stmt.arg))
        if table_name is not None
        else None
    )
    if override is not None:
        annotation, reason = override
        if alias:
            raise NotImplementedError(
                f"platform-divergent field {table_name}.{leaf_stmt.arg} needs an "
                "alias, which the override does not carry"
            )
        comment = "\n".join(
            f"    # {line}"
            for line in textwrap.wrap(f"Platform divergence: {reason}", width=74)
        )
        return f"{comment}\n    {field_name}: {annotation}"

    py = (
        yang_type_to_py(leaf_stmt.search_one("type"))
        if leaf_stmt.search_one("type")
        else PyType("Any")
    )
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


def leaf_list_field_decl(stmt, table_name: Optional[str] = None) -> str:
    py = (
        yang_type_to_py(stmt.search_one("type"))
        if stmt.search_one("type")
        else PyType("Any")
    )
    field_name, alias = safe_field_name(stmt.arg)
    inner = f"List[{py.annotation}]"
    delimiter = (
        LEAF_LIST_STRING_DELIMITERS.get((table_name, stmt.arg))
        if table_name is not None
        else None
    )
    if delimiter is not None:
        # The elements are still validated; only the container shape is widened.
        inner = f"Annotated[{inner}, BeforeValidator(_split_delimited({delimiter!r}))]"
    annotation = f"Optional[{inner}]"
    if alias:
        return (
            f"    {field_name}: {annotation} = " f"Field(default=None, alias={alias!r})"
        )
    return f"    {field_name}: {annotation} = None"


# Emitted into the generated schema module when any field needs it.
SPLIT_HELPER = '''
def _split_delimited(delimiter: str):
    """Accept a ConfigDB leaf-list written as one delimited string.

    A few leaf-lists reach ConfigDB as `"100000,50000"` rather than as a JSON
    array; see LEAF_LIST_WITH_STRING_VALUE_DICT in upstream sonic-yang-mgmt.
    Splitting mirrors what SONiC does before validating, down to stripping
    each element, so an empty string yields one empty element and is rejected
    here exactly as SONiC would reject it. Values already in array form are
    passed through untouched.
    """

    def split(value):
        if isinstance(value, str):
            return [element.strip() for element in value.split(delimiter)]
        return value

    return split

'''


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


def generate_row_class(
    class_name: str, leaves, table_name: Optional[str] = None
) -> str:
    rows = []
    for leaf in leaves:
        if leaf.keyword == "leaf":
            rows.append(leaf_field_decl(leaf, table_name))
        elif leaf.keyword == "leaf-list":
            rows.append(leaf_list_field_decl(leaf, table_name))
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
            parts.append(generate_row_class(row_class, leaves, table_name))
            row_classes.append(row_class)
            constraints.extend(collect_leafref_constraints(table_name, lst, leaves))
    elif sub_containers:
        for sc in sub_containers:
            row_class = base + to_class_name(sc.arg) + "Row"
            leaves = collect_leaves(sc)
            parts.append(generate_row_class(row_class, leaves, table_name))
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
    divergent: List[str] = []
    key_fields: Dict[str, List[Tuple[str, ...]]] = {}
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

        if table_name in PLATFORM_DIVERGENT_TABLES:
            # No model and no constraints sourced here: both would describe a
            # table the target platform implements differently. The table stays
            # usable as a leafref *target*, since ConfigDB row keys carry the
            # referenced value whichever flavour named the key leaf.
            divergent.append(table_name)
            continue

        code_blocks.append(f"\n# {path.name} :: {module.arg} :: {table_name}\n{code}")
        registry.append((table_name, table_class))
        leafrefs.extend(table_leafrefs)
        keys = collect_table_key_fields(container)
        if keys:
            key_fields[table_name] = keys

    body = "".join(code_blocks)
    body += "\n\nTABLE_MODELS: Dict[str, type[BaseModel]] = {\n"
    for table_name, table_class in sorted(registry):
        body += f'    "{table_name}": {table_class},\n'
    body += "}\n"

    body += (
        "\n# Tables deliberately left unvalidated: the vendored models describe\n"
        "# them differently from the platform these configs run on.\n"
        "PLATFORM_DIVERGENT_TABLES: Dict[str, str] = {\n"
    )
    for table_name in sorted(divergent):
        body += f"    {table_name!r}: {PLATFORM_DIVERGENT_TABLES[table_name]!r},\n"
    body += "}\n"

    used_typing = [n for n in TYPING_NAMES if re.search(rf"\b{n}\b", body)]
    typing_import = (
        f"from typing import {', '.join(used_typing)}\n\n" if used_typing else ""
    )
    pydantic_names = ["BaseModel", "ConfigDict", "Field", "RootModel"]
    if "BeforeValidator" in body:
        pydantic_names.append("BeforeValidator")
    pydantic_names.append("StringConstraints")
    pydantic_import = f"from pydantic import {', '.join(sorted(pydantic_names))}\n\n"
    helper = SPLIT_HELPER if "_split_delimited" in body else ""
    schema_code = HEADER_PREFIX + typing_import + pydantic_import + helper + body

    out_file = output / "_schemas.py"
    out_file.write_text(schema_code)

    leafrefs_file = output / "_leafrefs.py"
    leafrefs_file.write_text(render_leafrefs_module(leafrefs, key_fields))

    init_file = output / "__init__.py"
    init_file.write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# AUTO-GENERATED — DO NOT EDIT BY HAND.\n"
        '"""Generated SONiC ConfigDB schemas."""\n\n'
        "from ._leafrefs import LEAFREFS, TABLE_KEY_FIELDS, LeafrefConstraint\n"
        "from ._schemas import PLATFORM_DIVERGENT_TABLES, TABLE_MODELS\n\n"
        "__all__ = [\n"
        '    "LEAFREFS",\n'
        '    "LeafrefConstraint",\n'
        '    "PLATFORM_DIVERGENT_TABLES",\n'
        '    "TABLE_KEY_FIELDS",\n'
        '    "TABLE_MODELS",\n'
        "]\n"
    )

    print(f"Wrote {len(registry)} table models -> {out_file}")
    if divergent:
        print(f"Left {len(divergent)} table(s) unvalidated (platform divergence):")
        for name in sorted(divergent):
            print(f"  - {name}: {PLATFORM_DIVERGENT_TABLES[name]}")
    print(f"Wrote {len(leafrefs)} leafref constraints -> {leafrefs_file}")
    print(f"Wrote key fields for {len(key_fields)} tables")
    if skipped:
        print(f"Skipped {len(skipped)} containers:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    format_with_black(out_file, leafrefs_file, init_file)
    return 0


def render_leafrefs_module(
    constraints: List[LeafrefConstraint],
    key_fields: Optional[Dict[str, List[Tuple[str, ...]]]] = None,
) -> str:
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
            element_delimiter=existing.element_delimiter or c.element_delimiter,
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
    lines.append("from typing import Dict, Optional, Tuple")
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
    lines.append("    element_delimiter: Optional[str] = None")
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
        if c.element_delimiter is not None:
            lines.append(f"        element_delimiter={c.element_delimiter!r},")
        lines.append("    ),")
    lines.append(")")
    lines.append("")
    lines.append("")
    lines.append("# Key leaves of every `list` in a table, in the order ConfigDB joins")
    lines.append("# them into the row key with `|`. Lists are told apart by how many")
    lines.append("# parts they have; no table declares two of the same length.")
    lines.append("TABLE_KEY_FIELDS: Dict[str, Tuple[Tuple[str, ...], ...]] = {")
    all_key_fields = key_fields or {}
    for table_name in sorted(all_key_fields):
        variants = all_key_fields[table_name]
        rendered = ", ".join(
            "(" + ", ".join(repr(k) for k in v) + ("," if len(v) == 1 else "") + ")"
            for v in variants
        )
        if len(variants) == 1:
            rendered += ","
        lines.append(f"    {table_name!r}: ({rendered}),")
    lines.append("}")
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
