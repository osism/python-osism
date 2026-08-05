NETBOX_MANAGER_DIR ?= $(abspath ../netbox-manager)

# SONiC config-generation E2E golden test (see tests/e2e/sonic_golden_test.sh).

# Full cycle: start the NetBox compose stack (an existing stack is reused
# and left in place), seed, generate, compare against tests/e2e/golden/.
sonic-e2e:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) tests/e2e/sonic_golden_test.sh

# Regenerate the golden files after an intentional generator change,
# then review and commit the diff.
sonic-e2e-regen:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) tests/e2e/sonic_golden_test.sh --regenerate

# Start the NetBox stack and leave it running for debugging. Export a
# NETBOX_TOKEN beforehand to get a known API token minted.
sonic-e2e-up:
	tests/e2e/deploy_netbox.sh

# Stop the NetBox stack and remove its volumes.
sonic-e2e-down:
	docker compose -f tests/e2e/compose.yaml down --volumes --remove-orphans

# Report config_db table coverage of the golden set (tests/e2e/coverage.py).
# A reporting tool only -- not part of the gating check, which stays the
# golden comparison run by sonic-e2e above.
sonic-e2e-coverage:
	pipenv run python -m tests.e2e.coverage

.PHONY: sonic-e2e sonic-e2e-regen sonic-e2e-up sonic-e2e-down sonic-e2e-coverage
