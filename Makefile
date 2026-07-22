CLUSTER_NAME ?= sonic-e2e
NETBOX_MANAGER_DIR ?= $(abspath ../netbox-manager)

# SONiC config-generation E2E golden test (see tests/e2e/run.sh).

# Full cycle: provision kind + NetBox (an existing cluster is reused and
# left in place), seed, generate, compare against tests/e2e/golden/.
sonic-e2e:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) CLUSTER_NAME=$(CLUSTER_NAME) tests/e2e/run.sh

# Regenerate the golden files after an intentional generator change,
# then review and commit the diff.
sonic-e2e-regen:
	NETBOX_MANAGER_DIR=$(NETBOX_MANAGER_DIR) CLUSTER_NAME=$(CLUSTER_NAME) tests/e2e/run.sh --regenerate

# Provision kind + NetBox and leave it running for debugging. Export a
# NETBOX_TOKEN beforehand to get a known API token minted.
sonic-e2e-up:
	CLUSTER_NAME=$(CLUSTER_NAME) $(NETBOX_MANAGER_DIR)/tests/e2e/deploy_netbox.sh

# Delete the kind cluster created for the E2E test.
sonic-e2e-down:
	kind delete cluster --name $(CLUSTER_NAME)

.PHONY: sonic-e2e sonic-e2e-regen sonic-e2e-up sonic-e2e-down
