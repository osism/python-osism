# SPDX-License-Identifier: Apache-2.0

"""YANG-based validation for SONiC config_db.json configurations.

Uses sonic-yang-mgmt (which wraps libyang) to validate that a generated
SONiC ConfigDB JSON conforms to the bundled SONiC YANG models. The library
performs the ConfigDB-table → YANG-tree translation internally and then
runs full schema validation including types, leafrefs, must/when constraints
and mandatory leaves.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from osism import settings


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


class ValidatorUnavailable(RuntimeError):
    """Raised when the underlying sonic-yang-mgmt library cannot be imported."""


def _import_sonic_yang():
    try:
        import sonic_yang  # type: ignore
    except ImportError as exc:
        raise ValidatorUnavailable(
            "sonic-yang-mgmt is not importable. It is pinned in "
            "requirements.sonic.txt as a VCS install from sonic-buildimage; "
            "ensure pip installed it and that the libyang C library plus its "
            "Python binding (apt: libyang-dev + python3-yang) are present on "
            "the system."
        ) from exc
    return sonic_yang


def load_yang_context(yang_dir: Optional[str] = None):
    """Load all SONiC YANG models from yang_dir into a SonicYang context.

    Args:
        yang_dir: Directory containing sonic-*.yang files. Defaults to
            settings.SONIC_YANG_MODELS_DIR.

    Returns:
        sonic_yang.SonicYang: a context with all models loaded.
    """
    sonic_yang = _import_sonic_yang()

    yang_dir = yang_dir or settings.SONIC_YANG_MODELS_DIR
    logger.debug(f"Loading SONiC YANG models from {yang_dir}")

    ctx = sonic_yang.SonicYang(yang_dir, print_log_enabled=False)
    ctx.loadYangModel()
    return ctx


def validate_config(
    config: Dict[str, Any], ctx=None, yang_dir: Optional[str] = None
) -> ValidationResult:
    """Validate a SONiC config_db.json dict against the SONiC YANG models.

    Args:
        config: The ConfigDB JSON as a dict (top-level keys are tables).
        ctx: Optional pre-loaded SonicYang context (reuse for batches).
        yang_dir: Override the YANG model directory; ignored when ctx is given.

    Returns:
        ValidationResult with valid flag and any collected errors.
    """
    sonic_yang = _import_sonic_yang()

    if ctx is None:
        ctx = load_yang_context(yang_dir)

    try:
        ctx.loadData(configdbJson=config)
        ctx.validate_data_tree()
    except sonic_yang.SonicYangException as exc:
        message = str(exc)
        errors = _split_libyang_errors(message)
        if not errors:
            errors = [ValidationError(message=message)]
        return ValidationResult(valid=False, errors=errors)
    except Exception as exc:
        return ValidationResult(
            valid=False,
            errors=[ValidationError(message=f"Unexpected validator error: {exc}")],
        )

    return ValidationResult(valid=True)


def _split_libyang_errors(raw: str) -> List[ValidationError]:
    """Best-effort parse of the multi-line error blob returned by libyang.

    libyang concatenates multiple errors into one string via SonicYangException;
    we split on newlines and try to extract a path hint when present.
    """
    errors: List[ValidationError] = []
    for line in (line.strip() for line in raw.splitlines()):
        if not line:
            continue
        path: Optional[str] = None
        message = line
        marker = "Schema location:"
        if marker in line:
            head, tail = line.split(marker, 1)
            message = head.strip().rstrip(",;.")
            path = tail.strip().split(",", 1)[0].strip()
        errors.append(ValidationError(message=message, path=path))
    return errors
