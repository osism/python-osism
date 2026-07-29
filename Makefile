NETBOX_MANAGER_DIR ?= $(abspath ../netbox-manager)

# SONiC config-generation E2E golden test (see tests/e2e/run.sh).

# Full cycle: start the NetBox compose stack (an existing stack is reused
# and left in place), seed, generate, compare against tests/e2e/golden/.
sonic-e2e:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) tests/e2e/run.sh

# Regenerate the golden files after an intentional generator change,
# then review and commit the diff.
sonic-e2e-regen:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) tests/e2e/run.sh --regenerate

# Start the NetBox stack and leave it running for debugging. Export a
# NETBOX_TOKEN beforehand to get a known API token minted.
sonic-e2e-up:
	tests/e2e/deploy_netbox.sh

# Stop the NetBox stack and remove its volumes.
sonic-e2e-down:
	docker compose -f tests/e2e/compose.yaml down --volumes --remove-orphans

.PHONY: sonic-e2e sonic-e2e-regen sonic-e2e-up sonic-e2e-down
