#!/usr/bin/env bash
#
# SONiC config-generation E2E golden test:
#
#   1. provision NetBox on a local kind cluster (reuses netbox-manager's
#      tests/e2e/deploy_netbox.sh; an existing cluster of the same name
#      is reused and left in place)
#   2. seed it with netbox-manager and the bundled example/ data
#   3. run sync_sonic() via tests/e2e/generate.py
#   4. compare the exported config_db files against tests/e2e/golden/
#      (or rewrite the goldens with --regenerate)
#
# Requirements: docker, kind, kubectl, helm, openssl, a netbox-manager
# checkout (sibling directory or NETBOX_MANAGER_DIR), and this repo's
# pipenv environment (pipenv install --dev).
#
# Environment overrides:
#   NETBOX_MANAGER_DIR  netbox-manager checkout (default: ../netbox-manager)
#   CLUSTER_NAME        kind cluster name (default: sonic-e2e)
#   NAMESPACE           NetBox namespace (default: netbox)
#   NETBOX_TOKEN        API token (default: random; also minted in NetBox)
#   NETBOX_PORT         local port-forward port (default: 8080)
#   KEEP_CLUSTER=1      leave a cluster created by this run in place

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

REGENERATE=0
for arg in "$@"; do
  case "${arg}" in
    --regenerate) REGENERATE=1 ;;
    *)
      echo "usage: $0 [--regenerate]" >&2
      exit 2
      ;;
  esac
done

NETBOX_MANAGER_DIR="${NETBOX_MANAGER_DIR:-${REPO_ROOT}/../netbox-manager}"
NETBOX_MANAGER_DIR="$(cd "${NETBOX_MANAGER_DIR}" 2>/dev/null && pwd)" || {
  echo "error: netbox-manager checkout not found; set NETBOX_MANAGER_DIR" >&2
  exit 2
}

CLUSTER_NAME="${CLUSTER_NAME:-sonic-e2e}"
NAMESPACE="${NAMESPACE:-netbox}"
NETBOX_TOKEN="${NETBOX_TOKEN:-$(openssl rand -hex 20)}"
NETBOX_PORT="${NETBOX_PORT:-8080}"
GOLDEN_DIR="${REPO_ROOT}/tests/e2e/golden"
export CLUSTER_NAME NAMESPACE NETBOX_TOKEN

# Only tear down a cluster this run actually created -- never a reused
# debug cluster (make sonic-e2e-up) that happens to share the name.
CREATED_CLUSTER=0
if ! kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  CREATED_CLUSTER=1
fi

PF_PID=""
EXPORT_DIR=""
dump_diagnostics() {
  echo "==================== kind / NetBox diagnostics ===================="
  kubectl get nodes -o wide 2>&1 || true
  kubectl get pods -A -o wide 2>&1 || true
  kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp 2>&1 | tail -n 40 || true
  echo "=================================================================="
}
cleanup() {
  rc=$?
  if [[ -n "${PF_PID}" ]]; then
    kill "${PF_PID}" 2>/dev/null || true
  fi
  if [[ "${rc}" -ne 0 ]]; then
    echo ">>> E2E run failed (exit ${rc}); dumping cluster diagnostics"
    dump_diagnostics || true
  fi
  if [[ -n "${EXPORT_DIR}" ]]; then
    rm -rf "${EXPORT_DIR}"
  fi
  if [[ "${CREATED_CLUSTER}" == "1" && "${KEEP_CLUSTER:-0}" != "1" ]]; then
    echo ">>> Deleting kind cluster '${CLUSTER_NAME}'"
    kind delete cluster --name "${CLUSTER_NAME}" || true
  else
    echo ">>> Leaving kind cluster '${CLUSTER_NAME}' in place"
  fi
}
trap cleanup EXIT

# --- Phase 1: provision NetBox on kind -------------------------------------
PRINT_NETBOX_TOKEN=0 "${NETBOX_MANAGER_DIR}/tests/e2e/deploy_netbox.sh"

echo ">>> Port-forwarding svc/netbox -> 127.0.0.1:${NETBOX_PORT}"
kubectl -n "${NAMESPACE}" port-forward "svc/netbox" "${NETBOX_PORT}:80" &
PF_PID=$!

ready=0
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${NETBOX_PORT}/api/" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  echo "error: NetBox API not reachable on 127.0.0.1:${NETBOX_PORT} after 30s" >&2
  exit 1
fi
if ! kill -0 "${PF_PID}" 2>/dev/null; then
  echo "error: port-forward exited early (is 127.0.0.1:${NETBOX_PORT} already in use?)" >&2
  exit 1
fi

# --- Phase 2: seed with netbox-manager -------------------------------------
# The CLI is installed from the checkout so a Zuul Depends-On on a
# netbox-manager change is honored for code and data alike.
echo ">>> Installing netbox-manager from ${NETBOX_MANAGER_DIR}"
pipenv run pip install --quiet "${NETBOX_MANAGER_DIR}"

echo ">>> Installing the netbox.netbox Ansible collection"
pipenv run ansible-galaxy collection install -r "${NETBOX_MANAGER_DIR}/requirements.yml"

export NETBOX_MANAGER_URL="http://127.0.0.1:${NETBOX_PORT}"
export NETBOX_MANAGER_TOKEN="${NETBOX_TOKEN}"
export NETBOX_MANAGER_DEVICETYPE_LIBRARY="${NETBOX_MANAGER_DIR}/example/devicetypes"
export NETBOX_MANAGER_MODULETYPE_LIBRARY="${NETBOX_MANAGER_DIR}/example/moduletypes"
export NETBOX_MANAGER_RESOURCES="${NETBOX_MANAGER_DIR}/example/resources"
export NETBOX_MANAGER_IGNORE_SSL_ERRORS=true

echo ">>> Seeding NetBox with the netbox-manager example data"
pipenv run netbox-manager run --fail-fast

# Scenario overlay (spec phase 4): a second run with
# NETBOX_MANAGER_RESOURCES=${REPO_ROOT}/tests/e2e/resources goes here once
# the regression-scenario seed data exists.

# --- Phase 3: generate SONiC configurations ---------------------------------
EXPORT_DIR="$(mktemp -d)"
export NETBOX_API="http://127.0.0.1:${NETBOX_PORT}"
export SONIC_EXPORT_DIR="${EXPORT_DIR}"
export SONIC_EXPORT_IDENTIFIER="hostname"
export SONIC_PORT_CONFIG_PATH="${REPO_ROOT}/files/sonic/port_config"

echo ">>> Generating SONiC configurations (tests/e2e/generate.py)"
if [[ "${REGENERATE}" == "1" ]]; then
  pipenv run python -m tests.e2e.generate --no-expect
else
  pipenv run python -m tests.e2e.generate --golden "${GOLDEN_DIR}"
fi

# --- Phase 4: compare against (or regenerate) the golden files -------------
if [[ "${REGENERATE}" == "1" ]]; then
  echo ">>> Regenerating golden files in ${GOLDEN_DIR}"
  pipenv run python -m tests.e2e.compare \
    --golden "${GOLDEN_DIR}" --export "${EXPORT_DIR}" --regenerate
  echo ">>> Golden files regenerated; review and commit the diff."
else
  echo ">>> Comparing exports against ${GOLDEN_DIR}"
  pipenv run python -m tests.e2e.compare \
    --golden "${GOLDEN_DIR}" --export "${EXPORT_DIR}"
  echo ">>> SONiC E2E golden test passed."
fi
