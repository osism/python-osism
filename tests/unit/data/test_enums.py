# SPDX-License-Identifier: Apache-2.0

import pytest

from osism.data.enums import (
    MAP_ROLE2ROLE,
    VALIDATE_PLAYBOOKS,
    Role,
    bounded_roles,
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
# Role release bounds
# ---------------------------------------------------------------------------


def test_role_bounds_default_to_none():
    role = Role("keystone")

    assert role.since is None
    assert role.until is None
    assert role.release_bounded is False


def test_role_bounds_parsed_to_tuples():
    role = Role("valkey", since="2025.2", until="2026.1")

    assert role.since == (2025, 2)
    assert role.until == (2026, 1)
    assert role.release_bounded is True


def test_role_rejects_unparseable_bound():
    """Catalog literals are parsed eagerly so a typo fails loudly, at once."""
    from osism.data.releases import ReleaseUnparseable

    with pytest.raises(ReleaseUnparseable):
        Role("valkey", since="master")


def test_role_without_bounds_is_in_every_release():
    role = Role("keystone")

    assert role.deployed_in((2024, 1)) is True
    assert role.deployed_in((2026, 1)) is True


def test_role_since_is_inclusive():
    role = Role("valkey", since="2025.2")

    assert role.deployed_in((2025, 1)) is False
    assert role.deployed_in((2025, 2)) is True
    assert role.deployed_in((2026, 1)) is True


def test_role_until_is_inclusive():
    role = Role("redis", until="2025.1")

    assert role.deployed_in((2024, 2)) is True
    assert role.deployed_in((2025, 1)) is True
    assert role.deployed_in((2025, 2)) is False


def test_role_both_bounds_form_a_closed_range():
    role = Role("interim", since="2025.2", until="2026.1")

    assert role.deployed_in((2025, 1)) is False
    assert role.deployed_in((2025, 2)) is True
    assert role.deployed_in((2026, 1)) is True
    assert role.deployed_in((2026, 2)) is False


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"since": "2025.2"}, "from 2025.2"),
        ({"until": "2025.1"}, "up to 2025.1"),
        ({"since": "2025.2", "until": "2026.1"}, "from 2025.2 to 2026.1"),
    ],
)
def test_role_bound_description(kwargs, expected):
    assert Role("role", **kwargs).bound_description() == expected


def test_role_bound_description_raises_on_unbounded_role():
    """Nothing to describe on an unbounded Role; fail loud, not with nonsense."""
    with pytest.raises(ValueError):
        Role("keystone").bound_description()


# ---------------------------------------------------------------------------
# bounded_roles
# ---------------------------------------------------------------------------


def test_bounded_roles_finds_nothing_when_unbounded():
    roles = [Role("a", dependencies=[Role("b")]), Role("c")]

    assert list(bounded_roles(roles)) == []


def test_bounded_roles_finds_nested_bounds():
    valkey = Role("valkey", since="2025.2")
    roles = [Role("a", dependencies=[Role("b", dependencies=[valkey])]), Role("c")]

    assert list(bounded_roles(roles)) == [valkey]


def test_bounded_roles_includes_a_bounded_parent_and_its_bounded_child():
    child = Role("child", since="2026.1")
    parent = Role("parent", until="2025.1", dependencies=[child])

    assert list(bounded_roles([parent])) == [parent, child]


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
def test_kvs_backends_are_bounded_and_disjoint(collection):
    roles = MAP_ROLE2ROLE[collection]
    redis = find_role(roles, "redis")
    valkey = find_role(roles, "valkey")

    assert redis.until == (2025, 1)
    assert redis.since is None
    assert valkey.since == (2025, 2)
    assert valkey.until is None


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
    roles = MAP_ROLE2ROLE[collection]
    selected = [
        name
        for name in ("redis", "valkey")
        if find_role(roles, name).deployed_in(release)
    ]

    assert selected == [expected]


def test_only_the_kvs_roles_carry_bounds():
    """A bound anywhere else is new and wants its own test above."""
    bounded = {
        role.name for roles in MAP_ROLE2ROLE.values() for role in bounded_roles(roles)
    }

    assert bounded == {"redis", "valkey"}


def test_no_bounded_role_has_dependencies():
    """A release-bounded role must be a leaf, until someone settles ordering.

    Excluding a role promotes its dependencies into the surrounding group so
    the subtree survives. That keeps the subtree and its position among
    retained siblings, but not what the excluded role supplied to it:
    ``chain(pt, st)`` runs a role BEFORE its ``dependencies``, so they are its
    dependents and it is their prerequisite. Promote them past an excluded
    parent and they run with no predecessor -- a well-formed task graph that
    may be ordered wrongly, which is worse than an error because it looks
    intentional. Nothing at expansion time can know which retained or
    replacement role belongs in that place.

    So the decision is forced here, in CI, in the change that introduces such
    a role -- not at deploy time, and not only for whoever reads the design
    document. The case this exists for is the kolla 2026.1 split of ``common``
    into ``logs``, ``kolla_toolbox``, ``cron`` and ``fluentd``: ``common`` has
    six dependents, so bounding it trips this test.

    If you are here because you added one: decide what runs in the excluded
    role's place on each release, encode that, and replace this test with one
    that pins the ordering you chose.
    """
    offenders = {
        role.name: [dependency.name for dependency in role.dependencies]
        for roles in MAP_ROLE2ROLE.values()
        for role in bounded_roles(roles)
        if role.dependencies
    }

    assert not offenders, (
        f"release-bounded roles with dependencies: {offenders}. "
        "Excluding one promotes its dependents but not the prerequisite it "
        "was; settle the ordering and replace this test. See the docstring."
    )


def test_valkey_absent_from_collections_that_never_had_redis():
    """The cut-over touches exactly the three collections that listed redis."""
    for name, roles in MAP_ROLE2ROLE.items():
        if name in KVS_COLLECTIONS:
            continue

        assert find_role(roles, "valkey") is None, name
        assert find_role(roles, "redis") is None, name
