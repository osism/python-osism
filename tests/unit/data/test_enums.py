# SPDX-License-Identifier: Apache-2.0

from osism.data.enums import (
    LOADBALANCER_PLAYBOOKS,
    MAP_ROLE2ROLE,
    VALIDATE_PLAYBOOKS,
    Role,
)


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
# Role
# ---------------------------------------------------------------------------


def test_role_default_dependencies_is_empty_list():
    role = Role("keystone")

    assert role.name == "keystone"
    assert role.dependencies == []


def test_role_none_dependencies_normalized_to_empty_list():
    role = Role("keystone", dependencies=None)

    assert role.dependencies == []


def test_role_empty_list_dependencies_kept():
    role = Role("keystone", dependencies=[])

    assert role.dependencies == []


def test_role_with_dependencies_keeps_passed_list():
    deps = [Role("glance")]
    role = Role("keystone", dependencies=deps)

    assert len(role.dependencies) == 1
    assert role.dependencies is deps
    assert role.dependencies[0].name == "glance"


def test_role_instances_with_same_name_are_independent():
    role_a = Role("keystone")
    role_b = Role("keystone")

    role_a.dependencies.append(Role("glance"))

    assert role_b.dependencies == []
    assert role_a is not role_b


def test_role_default_dependencies_not_shared_between_instances():
    role_a = Role("keystone")
    role_b = Role("keystone")

    assert role_a.dependencies is not role_b.dependencies


def test_role_accepts_nested_dependencies():
    role = Role(
        "keystone",
        dependencies=[Role("neutron", dependencies=[Role("nova")])],
    )

    assert role.dependencies[0].name == "neutron"
    assert role.dependencies[0].dependencies[0].name == "nova"


# ---------------------------------------------------------------------------
# LOADBALANCER_PLAYBOOKS
# ---------------------------------------------------------------------------


def test_loadbalancer_playbooks_is_non_empty_list():
    assert isinstance(LOADBALANCER_PLAYBOOKS, list)
    assert LOADBALANCER_PLAYBOOKS


def test_loadbalancer_playbooks_entries_are_non_empty_strings():
    for entry in LOADBALANCER_PLAYBOOKS:
        assert isinstance(entry, str)
        assert entry


def test_loadbalancer_playbooks_entries_share_prefix():
    for entry in LOADBALANCER_PLAYBOOKS:
        assert entry.startswith("loadbalancer-")


def test_loadbalancer_playbooks_entries_have_service_suffix():
    for entry in LOADBALANCER_PLAYBOOKS:
        suffix = entry.removeprefix("loadbalancer-")
        assert suffix
        assert not suffix.startswith("-")


def test_loadbalancer_playbooks_has_no_duplicates():
    assert len(LOADBALANCER_PLAYBOOKS) == len(set(LOADBALANCER_PLAYBOOKS))


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
