# SPDX-License-Identifier: Apache-2.0

"""SONiC ConfigDB validation against generated Pydantic schemas.

The schemas in `_generated/` are produced offline from the SONiC YANG models
in `files/sonic/yang_models/` by `tools/sonic_yang_to_pydantic.py`. This
validator does not depend on libyang or sonic-yang-mgmt at runtime — only on
pydantic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import ValidationError as PydValidationError

from osism.tasks.conductor.sonic._generated import TABLE_MODELS


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

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
