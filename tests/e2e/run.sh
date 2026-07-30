#!/usr/bin/env bash
#
# SONiC config-generation E2E golden test:
#
#   1. start NetBox with docker compose (tests/e2e/deploy_netbox.sh; an
#      existing stack is reused and left in place)
#   2. seed it with netbox-manager and the bundled example/ data
#   3. run sync_sonic() via tests/e2e/generate.py
#   4. compare the exported config_db files against tests/e2e/golden/
#      (or rewrite the goldens with --regenerate)
#
# Requirements: docker (with the compose plugin), openssl, a netbox-manager
# checkout (sibling directory or NETBOX_MANAGER_DIR) for the seeding CLI and
# its example data, and this repo's pipenv environment (pipenv install --dev).
#
# Environment overrides:
#   NETBOX_MANAGER_DIR  netbox-manager checkout (default: ../netbox-manager)
#   NETBOX_TOKEN        API token (default: random; also minted in NetBox)
#   NETBOX_PORT         host port for the NetBox API (default: 8080)
#   KEEP_STACK=1        leave a stack created by this run running
#   SEED_PARALLEL       files seeded concurrently per group (default: 4;
#                       set to 1 to serialise -- see Phase 2)

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

NETBOX_TOKEN="${NETBOX_TOKEN:-$(openssl rand -hex 20)}"
NETBOX_PORT="${NETBOX_PORT:-8080}"
GOLDEN_DIR="${REPO_ROOT}/tests/e2e/golden"
COMPOSE_FILE="${REPO_ROOT}/tests/e2e/compose.yaml"
export NETBOX_TOKEN NETBOX_PORT

compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

# Only tear down a stack this run actually created -- never a reused debug
# stack (make sonic-e2e-up). --all so a stopped stack still counts as
# pre-existing.
CREATED_STACK=0
if [[ -z "$(compose ps --all --quiet 2>/dev/null)" ]]; then
  CREATED_STACK=1
fi

EXPORT_DIR=""
dump_diagnostics() {
  echo "==================== NetBox stack diagnostics ===================="
  compose ps --all 2>&1 || true
  # The application log is what actually explains a failed start; the stack
  # is torn down below, taking it with it, so snapshot it first. Capped to
  # the last 200 lines: this fires on any non-zero exit, including the most
  # common failure (a golden mismatch in phase 4, where compare.py has
  # already printed the useful diff), and an uncapped dump buries that diff
  # under megabytes of NetBox first-boot migration and postgres logs. 200
  # lines still covers a genuine boot failure.
  compose logs --no-color --timestamps --tail 200 2>&1 || true
  echo "================================================================="
}
cleanup() {
  rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    echo ">>> E2E run failed (exit ${rc}); dumping stack diagnostics"
    dump_diagnostics || true
  fi
  if [[ -n "${EXPORT_DIR}" ]]; then
    rm -rf "${EXPORT_DIR}"
  fi
  if [[ "${CREATED_STACK}" == "1" && "${KEEP_STACK:-0}" != "1" ]]; then
    echo ">>> Stopping the NetBox stack"
    compose down --volumes --remove-orphans || true
  else
    echo ">>> Leaving the NetBox stack in place"
  fi
}
trap cleanup EXIT

# --- Phase 1: provision NetBox with docker compose --------------------------
# The stack publishes the API on 127.0.0.1:${NETBOX_PORT} directly, so there
# is no port-forward to supervise, and `up --wait` has already established
# readiness via the services' healthchecks. A port clash fails at `up`.
PRINT_NETBOX_TOKEN=0 "${REPO_ROOT}/tests/e2e/deploy_netbox.sh"

# --- Phase 2: seed with netbox-manager -------------------------------------
# The CLI is installed from the checkout so a Zuul Depends-On on a
# netbox-manager change is honored for code and data alike. It goes into a
# dedicated venv: netbox-manager pins different versions of packages that
# python-osism also pins (e.g. pynetbox), and installing it into the
# project venv would silently mutate those pins.
SEED_VENV="${SEED_VENV:-${REPO_ROOT}/.venv-sonic-e2e}"
if [[ ! -x "${SEED_VENV}/bin/pip" ]]; then
  echo ">>> Creating seeding venv ${SEED_VENV}"
  python3 -m venv "${SEED_VENV}"
fi
# netbox-manager drives Ansible through ansible-runner, which resolves
# ansible-playbook via PATH -- the venv's bin must therefore be on PATH,
# not merely used for the netbox-manager entry point itself.
export PATH="${SEED_VENV}/bin:${PATH}"
echo ">>> Installing netbox-manager from ${NETBOX_MANAGER_DIR}"
"${SEED_VENV}/bin/pip" install --quiet "${NETBOX_MANAGER_DIR}"

echo ">>> Installing the netbox.netbox Ansible collection"
"${SEED_VENV}/bin/ansible-galaxy" collection install -r "${NETBOX_MANAGER_DIR}/requirements.yml"

export NETBOX_MANAGER_URL="http://127.0.0.1:${NETBOX_PORT}"
export NETBOX_MANAGER_TOKEN="${NETBOX_TOKEN}"
export NETBOX_MANAGER_DEVICETYPE_LIBRARY="${NETBOX_MANAGER_DIR}/example/devicetypes"
export NETBOX_MANAGER_MODULETYPE_LIBRARY="${NETBOX_MANAGER_DIR}/example/moduletypes"
export NETBOX_MANAGER_RESOURCES="${NETBOX_MANAGER_DIR}/example/resources"
export NETBOX_MANAGER_IGNORE_SSL_ERRORS=true

# netbox-manager sorts resource files by their leading number, runs the groups
# in order, and parallelises only WITHIN a group, so the 000 -> 100 -> 200 ->
# 300 ordering still holds. The 300- group is 16 per-device files and dominates
# the seeding time: measured in CI, --parallel 4 took it from 555s to 250s.
#
# ESCAPE HATCH: set SEED_PARALLEL=1 to seed strictly serially. If a run ever
# fails in a way that looks like a seeding race, re-run with SEED_PARALLEL=1
# and compare -- that reproduces the original sequential behaviour exactly.
# A race is far more likely to surface as a spurious failure than as a false
# pass, because interleaving would change the generated configs and the golden
# comparison would then catch it.
SEED_PARALLEL="${SEED_PARALLEL:-4}"

echo ">>> Seeding NetBox with the netbox-manager example data (parallel: ${SEED_PARALLEL})"
"${SEED_VENV}/bin/netbox-manager" run --fail-fast --parallel "${SEED_PARALLEL}"

# Scenario overlay: a second seeding pass adds the breakout / speed-unit
# regression devices that the base example does not cover. It reuses the
# site / tenant / roles created above and brings its own device type.
echo ">>> Seeding NetBox with the E2E scenario overlay"
export NETBOX_MANAGER_DEVICETYPE_LIBRARY="${REPO_ROOT}/tests/e2e/scenario/devicetypes"
export NETBOX_MANAGER_RESOURCES="${REPO_ROOT}/tests/e2e/scenario/resources"
# Passed for consistency, but expect no gain: the overlay's files sit in
# distinct numeric groups (500-, 600-, 700-) and only files within one group
# run concurrently, so they serialise regardless. Confirmed in CI -- this pass
# measured 49.8s with --parallel 4 against 47.4s serial.
"${SEED_VENV}/bin/netbox-manager" run --fail-fast --skipmtl --parallel "${SEED_PARALLEL}"

# --- Phase 3: generate SONiC configurations ---------------------------------
# The conductor import chain needs ansible-core, which lives in the
# project's optional [ansible] extra (the container image installs it via
# requirements.ansible.txt). The unit tests stub it out in conftest.py, so
# a venv that runs the unit suite does not necessarily satisfy this import.
echo ">>> Ensuring the osism[ansible] extra is installed"
pipenv run pip install --quiet ".[ansible]"

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
