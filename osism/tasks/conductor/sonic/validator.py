# SPDX-License-Identifier: Apache-2.0

"""SONiC ConfigDB validation against generated Pydantic schemas.

The schemas in `_generated/` are produced offline from the SONiC YANG models
in `files/sonic/yang_models/` by `tools/sonic_yang_to_pydantic.py`. This
validator does not depend on libyang or sonic-yang-mgmt at runtime — only on
pydantic.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any, Dict, Iterable, List, Optional, Tuple

from pydantic import StringConstraints, TypeAdapter
from pydantic import ValidationError as PydValidationError

from osism.tasks.conductor.sonic._generated import (
    LEAFREFS,
    LeafrefConstraint,
    PLATFORM_DIVERGENT_TABLES,
    TABLE_KEY_FIELDS,
    TABLE_MODELS,
)


@dataclass
class ValidationError:
    message: str
    path: Optional[str] = None
    table: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [
                {"message": e.message, "path": e.path, "table": e.table}
                for e in self.errors
            ],
            "warnings": list(self.warnings),
        }


def validate_config(config: Dict[str, Any]) -> ValidationResult:
    """Validate a SONiC ConfigDB JSON dict against the generated schemas.

    Tables that have a schema in :data:`TABLE_MODELS` are validated strictly.
    Tables not present in the schema registry — typically ones SONiC has not
    yet modelled in upstream YANG — are reported as warnings rather than
    errors, so the validator does not reject otherwise-valid configurations
    just because YANG coverage lags.

    A few tables are absent on purpose rather than for lack of coverage: the
    vendored models are community SONiC while these configs run on an
    Enterprise build, and where the two disagree a model exists but describes
    a different table. Those are listed in
    :data:`PLATFORM_DIVERGENT_TABLES` and warn with the reason, so the
    difference reads as a deliberate gap rather than as missing upstream work.
    """
    errors: List[ValidationError] = []
    warnings: List[str] = []

    for table_name, table_data in config.items():
        model = TABLE_MODELS.get(table_name)
        if model is None:
            reason = PLATFORM_DIVERGENT_TABLES.get(table_name)
            if reason is not None:
                warnings.append(
                    f"Table {table_name!r} is not validated: the vendored YANG "
                    f"disagrees with the target platform — {reason}"
                )
            else:
                warnings.append(
                    f"No YANG schema for table {table_name!r} (validation skipped)"
                )
            continue

        try:
            model.model_validate(table_data)
        except PydValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", ()))
                errors.append(
                    ValidationError(
                        message=err.get("msg", str(err)),
                        path=loc or None,
                        table=table_name,
                    )
                )
        except Exception as exc:
            errors.append(
                ValidationError(
                    message=f"Unexpected validator error: {exc}",
                    table=table_name,
                )
            )

    for pattern in _unusable_patterns():
        # Not a defect in the config: the committed schemas and the installed
        # pydantic disagree. Reported as an error all the same, because the
        # alternative is reporting success while quietly checking less.
        errors.append(
            ValidationError(
                message=(
                    "generated schema is not usable with the installed pydantic: "
                    f"pattern {pattern!r} does not compile"
                )
            )
        )

    leafref_errors, leafref_warnings = _check_leafrefs(config)
    errors.extend(leafref_errors)
    warnings.extend(leafref_warnings)

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def _check_leafrefs(
    config: Dict[str, Any],
) -> Tuple[List[ValidationError], List[str]]:
    """Verify every cross-table leafref reference resolves to an existing key.

    YANG `leafref` semantics say a leaf must point at an existing value in a
    target path. In SONiC ConfigDB the row dict key carries the target list's
    key value, so a missing reference is "value not in
    ``config[target_table]``". Multi-target (union-of-leafref) succeeds if
    *any* target accepts the value.

    A union may also offer non-leafref arms — ``BGP_NEIGHBOR.local_addr``
    takes a literal address as readily as an interface name. Those arms carry
    no reference to resolve, so a value one of them admits is legal as it
    stands and is exempt from the leafref check.

    Most referring values reach ConfigDB only inside the `|`-joined row key
    rather than as a field of the row, so the key is split using the key
    leaves the generator records in :data:`TABLE_KEY_FIELDS`. A row key whose
    part count matches no declared list is left alone rather than mapped
    positionally, which would invent values.

    A reference is only judged against the targets the config actually
    carries. A generated config is a fragment, layered onto the device's own
    base config, so it can name an `MGMT_PORT` it does not itself hold — and a
    union leafref can name a `PORTCHANNEL` while the fragment carries only
    `PORT`. A value that resolves nowhere is therefore an error only when every
    target table is present; otherwise it is reported as unjudged, naming the
    tables that were missing. A target that is present but empty is a different
    matter: the config does model it, so a value missing from it is dangling.
    """
    errors: List[ValidationError] = []
    warnings: List[str] = []
    for constraint in LEAFREFS:
        rows = config.get(constraint.source_table)
        if not isinstance(rows, dict):
            continue
        target_keysets = _collect_target_keysets(config, constraint)
        absent = [
            table
            for table, _ in constraint.targets
            if not isinstance(config.get(table), dict)
        ]
        for row_key, row in rows.items():
            for value in _iter_leafref_values(constraint, row_key, row):
                if _matches_plain_arm(constraint, value):
                    continue
                if _value_in_any_target(value, target_keysets):
                    continue
                if absent:
                    # The value resolves in none of the targets this config
                    # carries, but it may well name a row of one it does not.
                    # Report it as unjudged rather than as dangling — and say
                    # so, rather than dropping it silently, since a genuine
                    # typo lands here too.
                    warnings.append(
                        f"{constraint.source_table}.{constraint.source_field}"
                        f"={value!r} is not checked: this config does not carry "
                        f"{', '.join(absent)}"
                    )
                    continue
                errors.append(
                    ValidationError(
                        message=_format_missing_message(constraint, value),
                        path=f"{row_key}.{constraint.source_field}",
                        table=constraint.source_table,
                    )
                )
    return errors, warnings


def _collect_target_keysets(
    config: Dict[str, Any], constraint: LeafrefConstraint
) -> List[set]:
    """Return one set of legal values per target. ``target_field == "name"``
    (the list key) is the common case and corresponds to row keys; for
    non-key targets we also accept matching values inside the rows."""
    keysets: List[set] = []
    for target_table, target_field in constraint.targets:
        rows = config.get(target_table)
        keys: set = set()
        if isinstance(rows, dict):
            for k, v in rows.items():
                keys.add(k)
                if isinstance(v, dict):
                    inner = v.get(target_field)
                    if isinstance(inner, str):
                        keys.add(inner)
                    elif isinstance(inner, list):
                        for item in inner:
                            if isinstance(item, str):
                                keys.add(item)
        keysets.append(keys)
    return keysets


def _iter_leafref_values(
    constraint: LeafrefConstraint, row_key: str, row: Any
) -> Iterable[str]:
    """Yield the values from one row that this constraint should validate."""
    raw: Any = None
    if isinstance(row, dict) and constraint.source_field in row:
        raw = row[constraint.source_field]
    elif not isinstance(row_key, str):
        # ConfigDB JSON always keys rows by string, but validate_config is a
        # library call and a caller can hand us a dict that does not.
        raw = None
    elif constraint.source_is_simple_key and "|" not in row_key:
        # Single-key list: row key directly carries the leaf value.
        raw = row_key
    else:
        raw = _value_from_row_key(constraint, row_key)

    if raw is None:
        return
    if constraint.is_leaf_list:
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    yield item
        elif isinstance(raw, str):
            # A few leaf-lists reach ConfigDB as one delimited string. The
            # schema splits those; resolving the whole string as a single
            # reference would report every multi-element value as dangling.
            if constraint.element_delimiter:
                for item in raw.split(constraint.element_delimiter):
                    yield item.strip()
            else:
                yield raw
    else:
        if isinstance(raw, str):
            yield raw


def _value_from_row_key(constraint: LeafrefConstraint, row_key: str) -> Optional[str]:
    """Recover this constraint's value from a `|`-joined ConfigDB row key.

    ConfigDB stores a list's key values joined with `|` in that list's key
    order, so the leaf names recorded for the table map onto the parts
    positionally. A table may declare several lists; they are told apart by
    how many parts the key has, and a key matching none of them — or matching
    more than one, which the vendored models never produce — yields nothing,
    because guessing would fabricate a reference to check.
    """
    variants = TABLE_KEY_FIELDS.get(constraint.source_table)
    if not variants:
        return None
    parts = row_key.split("|")
    matching = [v for v in variants if len(v) == len(parts)]
    if len(matching) != 1:
        return None
    for name, value in zip(matching[0], parts):
        if name == constraint.source_field:
            return value
    return None


def _value_in_any_target(value: str, keysets: List[set]) -> bool:
    return any(value in ks for ks in keysets)


@lru_cache(maxsize=None)
def _pattern_adapter(pattern: str) -> Optional[TypeAdapter]:
    """Compile one generated arm pattern, or ``None`` if it will not compile.

    Failing here should be impossible: the generator matches every pattern it
    emits against both a conformant XSD engine and this one before committing
    it. If it happens anyway, the generated schemas and the installed pydantic
    disagree — an environment fault rather than anything about the config —
    and :func:`_unusable_patterns` reports it. The matcher then treats the arm
    as matching, so one bad pattern cannot also manufacture dangling-reference
    errors on top of the incompatibility.
    """
    try:
        return TypeAdapter(Annotated[str, StringConstraints(pattern=pattern)])
    except Exception:
        return None


def _matches_plain_arm(constraint: LeafrefConstraint, value: str) -> bool:
    """True when a non-leafref arm of the union already admits ``value``.

    Arms are alternatives, so one matching arm is enough; within an arm YANG
    requires every pattern to match.
    """
    for arm in constraint.plain_arms:
        if all(_matches_pattern(pattern, value) for pattern in arm):
            return True
    return False


def _matches_pattern(pattern: str, value: str) -> bool:
    adapter = _pattern_adapter(pattern)
    if adapter is None:
        return True
    try:
        adapter.validate_python(value)
    except PydValidationError:
        return False
    return True


def _unusable_patterns() -> List[str]:
    """Generated arm patterns this pydantic cannot compile.

    Keyed on the committed schemas rather than on the config, so this reports
    the same thing for every input: an incompatibility is surfaced once, and
    never as noise proportional to the configuration.
    """
    unusable: List[str] = []
    for constraint in LEAFREFS:
        for arm in constraint.plain_arms:
            for pattern in arm:
                if _pattern_adapter(pattern) is None and pattern not in unusable:
                    unusable.append(pattern)
    return unusable


def _format_missing_message(constraint: LeafrefConstraint, value: str) -> str:
    targets = ", ".join(f"{t}.{f}" for t, f in constraint.targets)
    return (
        f"leafref {constraint.source_field}={value!r} does not resolve to "
        f"an existing entry in {targets}"
    )
