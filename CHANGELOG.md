# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- YANG validation module for SONiC configurations before Netbox transfer
- `validate_sonic_config()` function using yanglint subprocess for config validation
- `ValidationResult` dataclass for structured validation output
- Automatic YANG model discovery from `files/sonic/yang_models/` directory
- Clear error messages for validation failures and missing dependencies
