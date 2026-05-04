# SPDX-License-Identifier: Apache-2.0

"""SONiC ConfigDB validation against generated Pydantic schemas.

The schemas in `_generated/` are produced offline from the SONiC YANG models
in `files/sonic/yang_models/` by `tools/sonic_yang_to_pydantic.py`. This
validator does not depend on libyang or sonic-yang-mgmt at runtime — only on
pydantic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from pydantic import ValidationError as PydValidationError

from osism.tasks.conductor.sonic._generated import (
    LEAFREFS,
    LeafrefConstraint,
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
    """
    errors: List[ValidationError] = []
    warnings: List[str] = []

    for table_name, table_data in config.items():
        model = TABLE_MODELS.get(table_name)
        if model is None:
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

    errors.extend(_check_leafrefs(config))

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def _check_leafrefs(config: Dict[str, Any]) -> List[ValidationError]:
    """Verify every cross-table leafref reference resolves to an existing key.

    YANG `leafref` semantics say a leaf must point at an existing value in a
    target path. In SONiC ConfigDB the row dict key carries the target list's
    key value, so a missing reference is "value not in
    ``config[target_table]``". Multi-target (union-of-leafref) succeeds if
    *any* target accepts the value.

    Composite-key parsing is intentionally skipped — when the source field is
    encoded only inside a `|`-separated row key, we can't safely split without
    YANG key metadata, so we only check explicit row-dict fields plus the
    ``source_is_simple_key`` shortcut where the row key alone is the value.
    """
    errors: List[ValidationError] = []
    for constraint in LEAFREFS:
        rows = config.get(constraint.source_table)
        if not isinstance(rows, dict):
            continue
        target_keysets = _collect_target_keysets(config, constraint)
        # If the config does not declare any of the target tables, the
        # references are unresolvable — flag them.
        for row_key, row in rows.items():
            for value in _iter_leafref_values(constraint, row_key, row):
                if not _value_in_any_target(value, target_keysets):
                    errors.append(
                        ValidationError(
                            message=_format_missing_message(constraint, value),
                            path=f"{row_key}.{constraint.source_field}",
                            table=constraint.source_table,
                        )
                    )
    return errors


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
    elif constraint.source_is_simple_key and "|" not in row_key:
        # Single-key list: row key directly carries the leaf value.
        raw = row_key

    if raw is None:
        return
    if constraint.is_leaf_list:
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    yield item
        elif isinstance(raw, str):
            yield raw
    else:
        if isinstance(raw, str):
            yield raw


def _value_in_any_target(value: str, keysets: List[set]) -> bool:
    return any(value in ks for ks in keysets)


def _format_missing_message(constraint: LeafrefConstraint, value: str) -> str:
    targets = ", ".join(f"{t}.{f}" for t, f in constraint.targets)
    return (
        f"leafref {constraint.source_field}={value!r} does not resolve to "
        f"an existing entry in {targets}"
    )
