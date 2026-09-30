# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field

import pytest

from osism.data.enums import (
    MAP_ROLE2ROLE as COLLECTION_PLANS,
    VALIDATE_PLAYBOOKS,
)

from osism.data.plans import (
    Parallel,
    Run,
    Select,
    Sequence,
    resolve,
    selections_for_openstack,
)


@dataclass
class Role:
    """Test-only tree view for the existing catalog topology assertions."""

    name: str
    dependencies: list = field(default_factory=list)


def tree_view(plan):
    if isinstance(plan, Run):
        return [Role(plan.name)]
    if isinstance(plan, Select):
        return [
            role
            for alternative in plan.alternatives.values()
            for role in tree_view(alternative)
        ]
    if isinstance(plan, Parallel):
        return [role for step in plan.steps for role in tree_view(step)]
    root = tree_view(plan.steps[0])
    remaining = plan.steps[1:]
    if remaining:
        root[0].dependencies = tree_view(
            remaining[0] if len(remaining) == 1 else Sequence(*remaining)
        )
    return root


MAP_ROLE2ROLE = {name: tree_view(plan) for name, plan in COLLECTION_PLANS.items()}


def walk(roles, _seen=None):
    """Yield every Role reachable from ``roles`` via the dependency tree.

    Cycles are guarded against with a visited set; each Role object is
    yielded at most once even if a future change introduces a back-edge.
    """
    if _seen is None:
        _seen = set()
    for role in roles:
        if id(role) in _seen:
            continue
        _seen.add(id(role))
        yield role
        yield from walk(role.dependencies, _seen)


def find_role(roles, name):
    """Return the first Role with ``name`` reachable from ``roles``, or None."""
    for role in walk(roles):
        if role.name == name:
            return role
    return None


def reachable_names(roles):
    """Return the set of role names reachable from ``roles``."""
    return {role.name for role in walk(roles)}


# ---------------------------------------------------------------------------
# VALIDATE_PLAYBOOKS
# ---------------------------------------------------------------------------


def test_validate_playbooks_is_non_empty_dict():
    assert isinstance(VALIDATE_PLAYBOOKS, dict)
    assert VALIDATE_PLAYBOOKS


def test_validate_playbooks_keys_are_non_empty_strings():
    for key in VALIDATE_PLAYBOOKS:
        assert isinstance(key, str)
        assert key


def test_validate_playbooks_values_are_dicts_with_runtime():
    for key, value in VALIDATE_PLAYBOOKS.items():
        assert isinstance(value, dict), key
        assert "runtime" in value, key
        assert isinstance(value["runtime"], str), key
        assert value["runtime"], key


def test_validate_playbooks_kolla_ansible_entries_have_playbook():
    kolla_entries = {
        k: v for k, v in VALIDATE_PLAYBOOKS.items() if v["runtime"] == "kolla-ansible"
    }

    assert kolla_entries

    for key, value in kolla_entries.items():
        assert "playbook" in value, key
        assert isinstance(value["playbook"], str), key
        assert value["playbook"], key


def test_validate_playbooks_osism_ansible_entries_have_environment():
    osism_entries = {
        k: v for k, v in VALIDATE_PLAYBOOKS.items() if v["runtime"] == "osism-ansible"
    }

    assert osism_entries

    for key, value in osism_entries.items():
        assert "environment" in value, key
        assert isinstance(value["environment"], str), key
        assert value["environment"], key


def test_validate_playbooks_ceph_config_is_rewritten_to_validate():
    entry = VALIDATE_PLAYBOOKS["ceph-config"]

    assert entry["runtime"] == "ceph-ansible"
    assert entry["playbook"] == "validate"


def test_validate_playbooks_runtimes_limited_to_known_set():
    known = {"kolla-ansible", "osism-ansible", "ceph-ansible"}

    for key, value in VALIDATE_PLAYBOOKS.items():
        assert value["runtime"] in known, key


# ---------------------------------------------------------------------------
# MAP_ROLE2ROLE
# ---------------------------------------------------------------------------


EXPECTED_COLLECTIONS = {
    "nutshell",
    "collection-infrastructure",
    "collection-kubernetes",
    "collection-openstack",
    "collection-openstack-core",
    "collection-ceph",
    "collection-monitoring",
    "collection-bootstrap",
    "cloudpod-infrastructure",
    "cloudpod-openstack",
    "cloudpod-ceph",
}


def test_map_role2role_keys_are_non_empty_strings():
    for key in MAP_ROLE2ROLE:
        assert isinstance(key, str)
        assert key


def test_map_role2role_values_are_non_empty_role_lists():
    for key, value in MAP_ROLE2ROLE.items():
        assert isinstance(value, list), key
        assert value, key
        for item in value:
            assert isinstance(item, Role), key


def test_map_role2role_known_collections_present():
    assert EXPECTED_COLLECTIONS.issubset(MAP_ROLE2ROLE.keys())


def test_map_role2role_recursion_yields_only_roles():
    for key, roles in MAP_ROLE2ROLE.items():
        for role in walk(roles):
            assert isinstance(role, Role), key
            assert isinstance(role.name, str), key
            assert role.name, key
            assert isinstance(role.dependencies, list), key


def test_map_role2role_collection_openstack_core_has_keystone_root():
    roots = MAP_ROLE2ROLE["collection-openstack-core"]

    assert any(role.name == "keystone" for role in roots)


def test_map_role2role_collection_openstack_core_includes_core_services():
    names = reachable_names(MAP_ROLE2ROLE["collection-openstack-core"])

    # Core services that must remain reachable from the openstack-core collection.
    # The exact dependency wiring is an implementation detail and not asserted here.
    assert {"keystone", "neutron", "nova", "glance", "cinder", "placement"} <= names


def test_map_role2role_collection_openstack_core_chain_keystone_to_octavia():
    roots = MAP_ROLE2ROLE["collection-openstack-core"]
    keystone = find_role(roots, "keystone")
    assert keystone is not None and isinstance(keystone, Role)
    neutron = find_role(keystone.dependencies, "neutron")
    assert neutron is not None and isinstance(neutron, Role)
    wait_for_nova = find_role(neutron.dependencies, "wait-for-nova")
    assert wait_for_nova is not None and isinstance(wait_for_nova, Role)
    octavia = find_role(wait_for_nova.dependencies, "octavia")
    assert octavia is not None and isinstance(octavia, Role)


def test_map_role2role_collection_monitoring_grafana_depends_on_prometheus():
    prometheus = find_role(MAP_ROLE2ROLE["collection-monitoring"], "prometheus")

    assert prometheus is not None
    assert any(dep.name == "grafana" for dep in prometheus.dependencies)


def test_map_role2role_collection_bootstrap_root_is_gather_facts():
    roots = MAP_ROLE2ROLE["collection-bootstrap"]

    assert len(roots) == 1
    assert roots[0].name == "gather-facts"


def test_map_role2role_collection_bootstrap_includes_essential_roles():
    names = reachable_names(MAP_ROLE2ROLE["collection-bootstrap"])

    # These roles must remain part of the bootstrap collection regardless of how
    # the dependency chain between them is wired.
    assert {"gather-facts", "hostname", "hosts", "repository"} <= names


def test_map_role2role_collection_kubernetes_root_is_kubernetes():
    roots = MAP_ROLE2ROLE["collection-kubernetes"]

    assert len(roots) == 1
    assert roots[0].name == "kubernetes"


def test_map_role2role_collection_kubernetes_provides_kubeconfig():
    names = reachable_names(MAP_ROLE2ROLE["collection-kubernetes"])

    assert {"kubernetes", "kubeconfig", "copy-kubeconfig"} <= names


def test_map_role2role_collection_ceph_includes_dashboard_bootstrap():
    names = reachable_names(MAP_ROLE2ROLE["collection-ceph"])

    assert "ceph-bootstrap-dashboard" in names


def test_map_role2role_walk_handles_cycles():
    a = Role("a")
    b = Role("b")
    a.dependencies.append(b)
    b.dependencies.append(a)

    visited = list(walk([a]))

    assert {role.name for role in visited} == {"a", "b"}
    assert len(visited) == 2


# ---------------------------------------------------------------------------
# The key-value store cut-over
# ---------------------------------------------------------------------------


KVS_COLLECTIONS = ["nutshell", "collection-infrastructure", "cloudpod-infrastructure"]


@pytest.mark.parametrize("collection", KVS_COLLECTIONS)
def test_kvs_collections_carry_both_backends(collection):
    roles = MAP_ROLE2ROLE[collection]

    assert find_role(roles, "redis") is not None
    assert find_role(roles, "valkey") is not None


@pytest.mark.parametrize("collection", KVS_COLLECTIONS)
@pytest.mark.parametrize(
    "release,expected",
    [
        ((2024, 2), "redis"),
        ((2025, 1), "redis"),
        ((2025, 2), "valkey"),
        ((2026, 1), "valkey"),
    ],
)
def test_exactly_one_backend_per_release(collection, release, expected):
    """Never both, never neither -- on any release, past or future."""
    roles = tree_view(
        resolve(
            COLLECTION_PLANS[collection],
            {**selections_for_openstack(release), "ceph_backend": "ceph-ansible"},
        )
    )
    selected = [name for name in ("redis", "valkey") if find_role(roles, name)]
    assert selected == [expected]


def test_valkey_absent_from_collections_that_never_had_redis():
    """The cut-over touches exactly the three collections that listed redis."""
    for name, roles in MAP_ROLE2ROLE.items():
        if name in KVS_COLLECTIONS:
            continue

        assert find_role(roles, "valkey") is None, name
        assert find_role(roles, "redis") is None, name
