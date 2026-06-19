# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the inventory-facts API endpoints.

``GET /v1/inventory/hosts/{host}/facts`` and ``.../facts/{fact}`` read the
Ansible facts cache straight from Redis (key ``ansible_facts<host>``). Driving
them through ``fastapi.testclient.TestClient`` against the live Redis exercises
the API-to-Redis read path end-to-end. The suite is skipped automatically when
Redis is not reachable (see ``conftest.py``).
"""

import json
import uuid

import pytest

from osism import utils

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    """A ``TestClient`` bound to the FastAPI app.

    ``osism.api`` is imported lazily here because importing it wires the event
    bridge to Redis at module load -- safe only in the integration environment
    where Redis is up.
    """
    from fastapi.testclient import TestClient

    from osism import api

    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def seed_facts():
    """Seed ``ansible_facts<host>`` keys and remove them after the test."""
    keys = []

    def _seed(host, value):
        key = f"ansible_facts{host}"
        utils.redis.set(key, value)
        keys.append(key)

    yield _seed

    for key in keys:
        utils.redis.delete(key)


def test_get_all_facts_returns_parsed_facts_and_count(client, seed_facts):
    """All facts are returned parsed, with the correct count and cache flag."""
    host = f"itest-{uuid.uuid4()}"
    facts = {
        "ansible_hostname": "node-1",
        "ansible_processor_count": 4,
        "ansible_default_ipv4": {"address": "10.0.0.1", "gateway": "10.0.0.254"},
    }
    seed_facts(host, json.dumps(facts))

    response = client.get(f"/v1/inventory/hosts/{host}/facts")

    assert response.status_code == 200
    body = response.json()
    assert body["host"] == host
    assert body["count"] == len(facts)
    assert body["from_cache"] is True
    assert {entry["name"]: entry["value"] for entry in body["facts"]} == facts


def test_get_single_fact_returns_value(client, seed_facts):
    """A single fact is returned with its exact value and cache flag."""
    host = f"itest-{uuid.uuid4()}"
    facts = {"ansible_processor_count": 4, "ansible_hostname": "node-1"}
    seed_facts(host, json.dumps(facts))

    response = client.get(f"/v1/inventory/hosts/{host}/facts/ansible_processor_count")

    assert response.status_code == 200
    body = response.json()
    assert body["host"] == host
    assert body["name"] == "ansible_processor_count"
    assert body["value"] == 4
    assert body["from_cache"] is True


def test_get_unknown_fact_returns_404(client, seed_facts):
    """Requesting a fact absent from the cached set returns 404."""
    host = f"itest-{uuid.uuid4()}"
    seed_facts(host, json.dumps({"ansible_hostname": "node-1"}))

    response = client.get(f"/v1/inventory/hosts/{host}/facts/does_not_exist")

    assert response.status_code == 404


def test_get_all_facts_unknown_host_returns_404(client):
    """Requesting facts for a host with no cache key returns 404."""
    host = f"itest-{uuid.uuid4()}"

    response = client.get(f"/v1/inventory/hosts/{host}/facts")

    assert response.status_code == 404


def test_get_single_fact_unknown_host_returns_404(client):
    """Requesting a single fact for a host with no cache key returns 404."""
    host = f"itest-{uuid.uuid4()}"

    response = client.get(f"/v1/inventory/hosts/{host}/facts/ansible_hostname")

    assert response.status_code == 404


def test_get_all_facts_malformed_json_returns_500(client, seed_facts):
    """Non-JSON data in the cache key surfaces as a 500."""
    host = f"itest-{uuid.uuid4()}"
    seed_facts(host, "{ not valid json")

    response = client.get(f"/v1/inventory/hosts/{host}/facts")

    assert response.status_code == 500
