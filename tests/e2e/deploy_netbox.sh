#!/usr/bin/env bash
#
# Provision NetBox for the SONiC E2E golden test (phase 1), using docker
# compose. See docs/superpowers/specs/2026-07-29-sonic-e2e-compose-design.md.
#
# This script starts the stack and mints the API token. It deliberately
# installs NO teardown trap: sonic_golden_test.sh owns the lifecycle, and a trap here
# would fire when this script exits -- before seeding and generation.
#
# Safe to run standalone for debugging (`make sonic-e2e-up`), which leaves
# the stack running.
#
# The NetBox secret key and superuser password are fixed literals in
# compose.yaml (ephemeral loopback-only fixture); only the API token and the
# published port are parameterised here.
#
# Environment overrides:
#   NETBOX_TOKEN            v1 API token to mint (default: random)
#   NETBOX_PORT             host port for the NetBox API (default: 8080)
#   PRINT_NETBOX_TOKEN=0    suppress echoing the token (set by sonic_golden_test.sh)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${HERE}/compose.yaml"

# Only generated when unset, so sonic_golden_test.sh's value wins when it calls us.
export NETBOX_TOKEN="${NETBOX_TOKEN:-$(openssl rand -hex 20)}"
# Guard against two failure modes of a caller-supplied token: it is
# interpolated into a Python string literal in the heredoc below, so a
# quote or newline would break out of that literal; and a token that is
# not 40 hex characters is otherwise accepted here but silently rejected
# by NetBox much later, far from this, the actual cause.
[[ "${NETBOX_TOKEN}" =~ ^[0-9a-f]{40}$ ]] || {
  echo "error: NETBOX_TOKEN must be 40 hex characters" >&2
  exit 2
}
export NETBOX_PORT="${NETBOX_PORT:-8080}"

compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

echo ">>> Starting the NetBox stack (postgres, valkey, netbox)"
# --wait blocks until every service is healthy. First boot runs the full
# NetBox migration set, hence the generous timeout.
compose up --detach --wait --wait-timeout 900

# Mint a deterministic v1 API token for the superuser. NetBox 4.5 introduced
# peppered "v2" API tokens; the image's bootstrap only ever creates a v2 one,
# and only when API_TOKEN_PEPPERS is set (compose.yaml leaves it unset, so it
# creates none). pynetbox / netbox.netbox authenticate with
# `Authorization: Token <key>`, i.e. a v1 token, which NetBox accepts through
# v4.6 -- legacy v1 support is removed in v4.7, so re-check this on a bump.
#
# The delete-then-create makes this idempotent: re-running against a reused
# stack replaces the old token instead of colliding with it. Keep the delete.
#
# The script is fed over stdin (not `shell -c`) so the token never lands on a
# command line inside the container.
echo ">>> Creating a deterministic v1 API token for the superuser"
compose exec -T netbox /opt/netbox/netbox/manage.py shell --interface python <<PYEOF
from django.contrib.auth import get_user_model
from users.models import Token
from users.choices import TokenVersionChoices
user = get_user_model().objects.get(username="admin")
Token.objects.filter(user=user).delete()
Token.objects.create(user=user, version=TokenVersionChoices.V1, token="${NETBOX_TOKEN}")
print("Created v1 token for", user.username)
PYEOF

echo
echo "NetBox is deployed."
echo
echo "  API       : http://127.0.0.1:${NETBOX_PORT}"
# Echo the token only for the standalone debug workflow; sonic_golden_test.sh sets
# PRINT_NETBOX_TOKEN=0 to keep it out of CI logs that may be retained.
if [[ "${PRINT_NETBOX_TOKEN:-1}" != "0" ]]; then
  echo "  API token : ${NETBOX_TOKEN}"
fi
echo
