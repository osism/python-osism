#!/usr/bin/env bash
#
# SONiC config-generation E2E golden test:
#
#   1. start NetBox with docker compose (tests/e2e/deploy_netbox.sh; an
#      existing stack is reused and left in place)
#   2. seed it with the fixtures in tests/e2e/scenario/ (netbox-manager is
#      the seeding tool; its example/ data is deliberately not used)
#   3. run sync_sonic() via tests/e2e/generate.py
#   4. compare the exported config_db files against tests/e2e/golden/
#      (or rewrite the goldens with --regenerate)
#
# Requirements: docker (with the compose plugin), openssl, a netbox-manager
# checkout (sibling directory or NETBOX_MANAGER_DIR) for the seeding CLI, and
# this repo's pipenv environment (pipenv install --dev).
#
# Phase 2 seeds every file under tests/e2e/scenario/resources/ regardless of
# git status -- a stray untracked file in that directory joins the fixture
# set and gets seeded too. This has broken a run twice; keep that directory
# clean (git status --ignored) before regenerating or debugging a mismatch.
#
# Environment overrides:
#   NETBOX_MANAGER_DIR    netbox-manager checkout (default: ../netbox-manager)
#   NETBOX_TOKEN          API token (default: random; also minted in NetBox)
#   NETBOX_PORT           host port for the NetBox API (default: 8080)
#   KEEP_STACK=1          leave a stack created by this run running
#   SEED_PARALLEL         files seeded concurrently per group (default: 1;
#                         >1 deadlocks intermittently -- see Phase 2)
#   ALLOW_WARM_REGEN=1    let --regenerate run against a reused stack (see
#                         the CREATED_STACK check below; off by default
#                         because it can produce goldens CI cannot reproduce)
#
# Usage: sonic_golden_test.sh [--regenerate [--allow-coverage-loss]]
#   --regenerate            rewrite the golden files from a fresh export
#   --allow-coverage-loss   with --regenerate, accept a table/device going
#                           from populated to empty/removed instead of
#                           failing (forwarded to tests.e2e.compare)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

REGENERATE=0
ALLOW_COVERAGE_LOSS=0
for arg in "$@"; do
  case "${arg}" in
    --regenerate) REGENERATE=1 ;;
    --allow-coverage-loss) ALLOW_COVERAGE_LOSS=1 ;;
    *)
      echo "usage: $0 [--regenerate [--allow-coverage-loss]]" >&2
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

# Regenerating against a reused stack applies each fixture as an UPDATE over
# whatever is already in the database, where a fresh stack creates every
# object cleanly -- the two can produce different goldens with no warning.
# Refuse by default; ALLOW_WARM_REGEN=1 is the escape hatch for someone who
# knows the reused stack still matches the fixtures (e.g. iterating with
# KEEP_STACK=1 and only editing generator code, not the fixtures).
if [[ "${REGENERATE}" == "1" && "${CREATED_STACK}" == "0" && "${ALLOW_WARM_REGEN:-0}" != "1" ]]; then
  echo "error: --regenerate refuses to run against a reused NetBox stack." >&2
  echo "       Applying fixtures as an UPDATE over a stale database can" >&2
  echo "       produce goldens a fresh stack (as CI always uses) would not" >&2
  echo "       reproduce. Run 'make sonic-e2e-down' first, or set" >&2
  echo "       ALLOW_WARM_REGEN=1 if you know the reused stack still" >&2
  echo "       matches the fixtures being regenerated." >&2
  exit 2
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
export NETBOX_MANAGER_IGNORE_SSL_ERRORS=true

# Seeding is serial by default because concurrent seeding DEADLOCKS.
#
# netbox-manager sorts resource files by leading number, runs the groups in
# order, and parallelises only within a group. The synthetic fixtures under
# tests/e2e/scenario/ follow the same numeric-group layout the retired example
# data used, so the same parallelism opportunity applies here too.
#
# That object-level analysis was not sufficient. The files share *foreign key
# parents*: every node file creates cables terminating on the shared switches,
# and inserting a row that references a device takes a KEY SHARE lock on that
# device's row for the FK check. Two transactions acquiring those parent locks
# in opposite orders deadlock:
#
#   deadlock detected ... while locking tuple (1,3) in relation "dcim_device"
#   SELECT 1 FROM ONLY "dcim_device" x WHERE "id" = $1 FOR KEY SHARE OF x
#
# Observed intermittently: two CI runs passed, the third failed this way, so
# roughly a one-in-three flake rate -- unusable as a default. It fails loudly
# rather than corrupting anything: the goldens are never at risk, because a
# deadlock aborts the run instead of silently reordering writes.
#
# The hazard has not gone away with the synthetic fixtures: 200-fabric.yml
# cables both leaves to a shared spine, so files in one numeric group still
# take KEY SHARE locks on the same parent dcim_device rows. Set
# SEED_PARALLEL=4 to opt back in -- worth revisiting only if netbox-manager
# gains deadlock retry.
SEED_PARALLEL="${SEED_PARALLEL:-1}"

echo ">>> Seeding NetBox with the E2E fixtures (parallel: ${SEED_PARALLEL})"
export NETBOX_MANAGER_DEVICETYPE_LIBRARY="${REPO_ROOT}/tests/e2e/scenario/devicetypes"
export NETBOX_MANAGER_RESOURCES="${REPO_ROOT}/tests/e2e/scenario/resources"
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
  COMPARE_ARGS=(--golden "${GOLDEN_DIR}" --export "${EXPORT_DIR}" --regenerate)
  if [[ "${ALLOW_COVERAGE_LOSS}" == "1" ]]; then
    COMPARE_ARGS+=(--allow-coverage-loss)
  fi
  pipenv run python -m tests.e2e.compare "${COMPARE_ARGS[@]}"
  echo ">>> Golden files regenerated; review and commit the diff."
else
  echo ">>> Comparing exports against ${GOLDEN_DIR}"
  pipenv run python -m tests.e2e.compare \
    --golden "${GOLDEN_DIR}" --export "${EXPORT_DIR}"
  echo ">>> SONiC E2E golden test passed."
fi
