# SPDX-License-Identifier: Apache-2.0

"""SONiC configuration validation using YANG models."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import subprocess
import tempfile
from typing import List
from loguru import logger


@dataclass
class ValidationResult:
    """Structured validation result from YANG validation.

    Attributes:
        is_valid: True if configuration passed validation
        errors: List of error messages from validation
        warnings: List of warning messages from validation
    """

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Generate human-readable validation summary.

        Returns:
            str: Summary message with validation status
        """
        if self.is_valid:
            return "✓ Validation successful"
        error_count = len(self.errors)
        warning_count = len(self.warnings)
        parts = [f"✗ Validation failed with {error_count} error{'s' if error_count != 1 else ''}"]
        if warning_count > 0:
            parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
        return ", ".join(parts)


def discover_yang_models(yang_models_dir: str) -> List[Path]:
    """Discover all YANG model files in directory.

    Recursively searches the specified directory for all .yang files.

    Args:
        yang_models_dir: Path to YANG models directory (relative or absolute)

    Returns:
        List of Path objects for discovered .yang files

    Raises:
        ValueError: If YANG models directory does not exist
    """
    yang_dir = Path(yang_models_dir)

    if not yang_dir.exists():
        raise ValueError(f"YANG models directory not found: {yang_models_dir}")

    if not yang_dir.is_dir():
        raise ValueError(f"YANG models path is not a directory: {yang_models_dir}")

    # Discover all .yang files recursively
    yang_files = list(yang_dir.rglob("*.yang"))

    logger.debug(f"Discovered {len(yang_files)} YANG model files in {yang_models_dir}")

    return yang_files


def validate_sonic_config(
    config: dict,
    yang_models_dir: str = "files/sonic/yang_models"
) -> ValidationResult:
    """Validate SONiC config_db.json against YANG models using yanglint.

    This function validates a generated SONiC configuration dictionary against
    the official SONiC YANG models using the yanglint command-line tool.

    The validation process:
    1. Discovers all YANG model files in the specified directory
    2. Writes the configuration to a temporary JSON file
    3. Executes yanglint with all YANG models and the config file
    4. Parses validation errors from stderr
    5. Returns structured validation result

    Args:
        config: Generated SONiC configuration dictionary (config_db.json format)
        yang_models_dir: Path to YANG models directory (default: files/sonic/yang_models)

    Returns:
        ValidationResult: Structured validation result with success status and any errors

    Raises:
        FileNotFoundError: If yanglint is not installed or not in PATH
        ValueError: If YANG models directory does not exist

    Example:
        >>> config = generate_sonic_config(device, hwsku)
        >>> result = validate_sonic_config(config)
        >>> if not result.is_valid:
        ...     logger.error(f"Validation failed: {result.errors}")
    """
    # Validate that YANG models directory exists
    try:
        yang_files = discover_yang_models(yang_models_dir)
    except ValueError as e:
        logger.error(f"YANG model discovery failed: {e}")
        raise

    if not yang_files:
        logger.warning(f"No YANG model files found in {yang_models_dir}")
        return ValidationResult(
            is_valid=False,
            errors=[f"No YANG model files found in {yang_models_dir}"]
        )

    # Check if yanglint is available
    try:
        subprocess.run(
            ["yanglint", "--version"],
            capture_output=True,
            check=True,
            timeout=5
        )
    except FileNotFoundError:
        error_msg = (
            "yanglint not found. Please install libyang tools:\n"
            "  - Debian/Ubuntu: apt-get install libyang2-tools\n"
            "  - macOS: brew install libyang"
        )
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    except subprocess.TimeoutExpired:
        logger.warning("yanglint --version timed out, but proceeding with validation")
    except subprocess.CalledProcessError as e:
        logger.warning(f"yanglint --version returned error: {e}, but proceeding with validation")

    # Write config to temporary JSON file
    temp_config_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False,
            encoding='utf-8'
        ) as f:
            json.dump(config, f, indent=2)
            temp_config_file = f.name
            logger.debug(f"Wrote configuration to temporary file: {temp_config_file}")

        # Build yanglint command
        # yanglint -p <yang_models_dir> -t config <yang_file_1> <yang_file_2> ... <config.json>
        yang_dir = Path(yang_models_dir).resolve()
        cmd = [
            "yanglint",
            "-p", str(yang_dir),  # Path for imports
            "-t", "config",       # Validate as configuration data
        ]

        # Add all YANG model files
        for yang_file in yang_files:
            cmd.append(str(yang_file))

        # Add config file
        cmd.append(temp_config_file)

        logger.debug(f"Executing yanglint with {len(yang_files)} YANG models")

        # Execute yanglint
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                check=False  # Don't raise exception on non-zero exit
            )

            # Parse validation results
            errors = []
            warnings = []

            # yanglint writes errors to stderr
            if result.stderr:
                stderr_lines = result.stderr.strip().split('\n')
                for line in stderr_lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Categorize messages
                    if 'err :' in line.lower() or 'error' in line.lower():
                        errors.append(line)
                    elif 'warn' in line.lower():
                        warnings.append(line)
                    else:
                        # Treat unknown messages as errors
                        errors.append(line)

            # Check exit code
            is_valid = result.returncode == 0

            if is_valid:
                logger.info("SONiC configuration validated successfully against YANG models")
            else:
                logger.warning(
                    f"SONiC configuration validation failed with {len(errors)} errors"
                )

            return ValidationResult(
                is_valid=is_valid,
                errors=errors,
                warnings=warnings
            )

        except subprocess.TimeoutExpired:
            error_msg = "Validation timed out after 30 seconds"
            logger.error(error_msg)
            return ValidationResult(
                is_valid=False,
                errors=[error_msg]
            )
        except Exception as e:
            error_msg = f"Validation subprocess failed: {e}"
            logger.error(error_msg)
            return ValidationResult(
                is_valid=False,
                errors=[error_msg]
            )

    finally:
        # Clean up temporary file
        if temp_config_file and Path(temp_config_file).exists():
            try:
                Path(temp_config_file).unlink()
                logger.debug(f"Cleaned up temporary file: {temp_config_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file {temp_config_file}: {e}")
