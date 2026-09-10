# SPDX-License-Identifier: Apache-2.0

from osism.data.releases import format_release, parse_release


class Role:
    """
    Represents a role with optional dependencies in a hierarchical structure.

    Args:
        name: The name of the role (string)
        dependencies: Optional list of dependent Role objects
        since: Earliest OpenStack release, inclusive, on which a collection
            should deploy this role (string, e.g. "2025.2")
        until: Latest such release, inclusive (string, e.g. "2025.1")

    ``since`` and ``until`` govern **collection membership only**: whether a
    collection should deploy this role on a given release. They are NOT a
    statement that the role's playbook exists, or that the role may be applied,
    on those releases. ``valkey`` is the illustration -- its play ships from
    OpenStack 2025.1, but collections deploy it only from 2025.2, because
    ``osism/defaults`` leaves ``enable_valkey`` off until then. Reading the
    bound as availability would wrongly reject ``osism apply valkey`` on 2025.1.

    Only collection expansion consults these bounds. ``osism apply <role>``
    never does.

    Example:
        >>> role = Role("keystone", dependencies=[Role("glance"), Role("cinder")])
        >>> role.name
        'keystone'
        >>> len(role.dependencies)
        2
    """

    def __init__(self, name, dependencies=None, since=None, until=None):
        """Initialize a Role with a name, optional dependencies and bounds."""
        self.name = name
        self.dependencies = dependencies or []
        # Parsed eagerly, unlike the deployed release: these are literals in
        # this file, so a bad value is a bug here that should surface at once
        # rather than on the one deployment whose release happens to test it.
        self.since = parse_release(since) if since else None
        self.until = parse_release(until) if until else None

    @property
    def release_bounded(self):
        """Whether collection membership depends on the OpenStack release."""
        return self.since is not None or self.until is not None

    def deployed_in(self, release):
        """Whether a collection should deploy this role on ``release``.

        ``release`` is a ``(year, minor)`` tuple from ``osism.data.releases``.
        """
        if self.since is not None and release < self.since:
            return False

        if self.until is not None and release > self.until:
            return False

        return True

    def bound_description(self):
        """Render the bounds for log and error text, e.g. "from 2025.2".

        Only meaningful for a release-bounded role; raises ``ValueError`` on
        one with neither bound, rather than silently rendering nonsense.
        """
        if self.since is not None and self.until is not None:
            return f"from {format_release(self.since)} to {format_release(self.until)}"

        if self.since is not None:
            return f"from {format_release(self.since)}"

        if self.until is not None:
            return f"up to {format_release(self.until)}"

        raise ValueError(f"{self.name!r} has no release bounds to describe")


def bounded_roles(roles):
    """Yield every release-bounded Role reachable from ``roles``.

    Used to decide whether expanding a collection needs the release at all: a
    collection with no bounded roles never triggers the lookup, and so can never
    fail on it.
    """
    for role in roles:
        if role.release_bounded:
            yield role

        yield from bounded_roles(role.dependencies)


VALIDATE_PLAYBOOKS = {
    "barbican-config": {
        "runtime": "kolla-ansible",
        "playbook": "barbican",
    },
    "blazar-config": {
        "runtime": "kolla-ansible",
        "playbook": "blazar",
    },
    "designate-config": {
        "runtime": "kolla-ansible",
        "playbook": "designate",
    },
    "keystone-config": {
        "runtime": "kolla-ansible",
        "playbook": "keystone",
    },
    "glance-config": {
        "runtime": "kolla-ansible",
        "playbook": "glance",
    },
    "heat-config": {
        "runtime": "kolla-ansible",
        "playbook": "heat",
    },
    "octavia-config": {
        "runtime": "kolla-ansible",
        "playbook": "octavia",
    },
    "nova-config": {
        "runtime": "kolla-ansible",
        "playbook": "nova",
    },
    "neutron-config": {
        "runtime": "kolla-ansible",
        "playbook": "neutron",
    },
    "placement-config": {
        "runtime": "kolla-ansible",
        "playbook": "placement",
    },
    "aodh-config": {
        "runtime": "kolla-ansible",
        "playbook": "aodh",
    },
    "ceilometer-config": {
        "runtime": "kolla-ansible",
        "playbook": "ceilometer",
    },
    "ironic-config": {
        "runtime": "kolla-ansible",
        "playbook": "ironic",
    },
    "manila-config": {
        "runtime": "kolla-ansible",
        "playbook": "manila",
    },
    # NOTE: The command should be "osism validate ceph-config". However,
    # the corresponding playbook is called ceph-validate because ceph-config
    # deploys the Ceph configuration itself. So this is rewritten from
    # ceph-config to ceph-validate.
    "ceph-config": {
        "runtime": "ceph-ansible",
        "playbook": "validate",
    },
    # NOTE: The playbooks for validating the Ceph deployment are currently
    # in osism/ansible-playbooks. Therefore, they are not executed in
    # ceph-ansible but in osism-ansible.
    "ceph-connectivity": {"environment": "ceph", "runtime": "osism-ansible"},
    "ceph-mgrs": {"environment": "ceph", "runtime": "osism-ansible"},
    "ceph-mons": {"environment": "ceph", "runtime": "osism-ansible"},
    "ceph-osds": {"environment": "ceph", "runtime": "osism-ansible"},
    "container-status": {"environment": "generic", "runtime": "osism-ansible"},
    "kernel-version": {"environment": "generic", "runtime": "osism-ansible"},
    "docker-version": {"environment": "generic", "runtime": "osism-ansible"},
    "kolla-connectivity": {"environment": "kolla", "runtime": "osism-ansible"},
    "mysql-open-files-limit": {"environment": "generic", "runtime": "osism-ansible"},
    "ntp": {"environment": "generic", "runtime": "osism-ansible"},
    "system-encoding": {"environment": "generic", "runtime": "osism-ansible"},
    "ulimits": {"environment": "generic", "runtime": "osism-ansible"},
    "stress": {"environment": "generic", "runtime": "osism-ansible"},
}

# Role dependency collections
#
# The MAP_ROLE2ROLE dictionary defines collections of roles with their dependencies.
# All roles are defined using Role objects for consistency and type safety.
#
# Format:
#   - Role("name", dependencies=[...]): A role with Role object dependencies
#   - Role("name"): A role with no dependencies (empty dependencies list)
#
MAP_ROLE2ROLE = {
    "nutshell": [
        Role("dotfiles"),
        Role("homer"),
        Role("netdata"),
        Role("openstackclient"),
        Role("phpmyadmin"),
        Role(
            "common",
            dependencies=[
                Role(
                    "loadbalancer",
                    dependencies=[
                        Role("opensearch"),
                        Role(
                            "mariadb",
                            dependencies=[
                                Role("horizon"),
                                Role(
                                    "keystone",
                                    dependencies=[
                                        Role(
                                            "neutron",
                                            dependencies=[
                                                Role(
                                                    "wait-for-nova",
                                                    dependencies=[Role("octavia")],
                                                )
                                            ],
                                        ),
                                        Role("barbican"),
                                        Role("designate"),
                                        Role("ironic"),
                                        Role("placement"),
                                        Role("magnum"),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                Role("openvswitch", dependencies=[Role("ovn")]),
                Role("memcached"),
                # kolla replaced redis with valkey at OpenStack 2025.2; on 2025.1
                # both plays exist but osism/defaults leaves enable_valkey off.
                Role("redis", until="2025.1"),
                Role("valkey", since="2025.2"),
                Role("rabbitmq"),
            ],
        ),
        Role(
            "kubernetes",
            dependencies=[
                Role("kubeconfig"),
                Role("copy-kubeconfig"),
            ],
        ),
        Role(
            "ceph",
            dependencies=[
                Role(
                    "ceph-pools",
                    dependencies=[
                        Role(
                            "copy-ceph-keys",
                            dependencies=[
                                Role(
                                    "cephclient",
                                    dependencies=[
                                        Role("ceph-bootstrap-dashboard"),
                                        Role(
                                            "wait-for-keystone",
                                            dependencies=[
                                                Role("kolla-ceph-rgw"),
                                                Role("glance"),
                                                Role("cinder"),
                                                Role("nova"),
                                            ],
                                        ),
                                        Role(
                                            "prometheus", dependencies=[Role("grafana")]
                                        ),
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        ),
    ],
    "collection-infrastructure": [
        Role("openstackclient"),
        Role("phpmyadmin"),
        Role(
            "common",
            dependencies=[
                Role(
                    "loadbalancer",
                    dependencies=[
                        Role("letsencrypt"),
                        Role("opensearch"),
                        Role("mariadb"),
                    ],
                ),
                Role("openvswitch", dependencies=[Role("ovn")]),
                Role("memcached"),
                Role("redis", until="2025.1"),
                Role("valkey", since="2025.2"),
                Role("rabbitmq"),
            ],
        ),
    ],
    "collection-kubernetes": [
        Role(
            "kubernetes",
            dependencies=[
                Role("kubeconfig"),
                Role("copy-kubeconfig"),
            ],
        ),
    ],
    "collection-openstack-core": [
        Role("horizon"),
        Role(
            "keystone",
            dependencies=[
                Role("glance"),
                Role("cinder"),
                Role(
                    "neutron",
                    dependencies=[
                        Role("wait-for-nova", dependencies=[Role("octavia")]),
                    ],
                ),
                Role("designate"),
                Role("placement", dependencies=[Role("nova")]),
            ],
        ),
    ],
    "collection-openstack": [
        Role("horizon"),
        Role(
            "keystone",
            dependencies=[
                Role("glance"),
                Role("cinder"),
                Role("barbican"),
                Role("designate"),
                Role(
                    "neutron",
                    dependencies=[
                        Role("wait-for-nova", dependencies=[Role("octavia")]),
                    ],
                ),
                Role("ironic"),
                Role("kolla-ceph-rgw"),
                Role("magnum"),
                Role("placement", dependencies=[Role("nova")]),
            ],
        ),
    ],
    "collection-ceph": [
        Role(
            "ceph",
            dependencies=[
                Role(
                    "ceph-pools",
                    dependencies=[
                        Role(
                            "copy-ceph-keys",
                            dependencies=[
                                Role(
                                    "cephclient",
                                    dependencies=[Role("ceph-bootstrap-dashboard")],
                                )
                            ],
                        )
                    ],
                )
            ],
        ),
    ],
    "collection-monitoring": [
        Role("prometheus", dependencies=[Role("grafana")]),
        Role("netdata"),
    ],
    "collection-bootstrap": [
        Role(
            "gather-facts",
            dependencies=[
                Role(
                    "hostname",
                    dependencies=[
                        Role(
                            "hosts",
                            dependencies=[
                                Role(
                                    "proxy",
                                    dependencies=[
                                        Role(
                                            "resolvconf",
                                            dependencies=[
                                                Role(
                                                    "repository",
                                                    dependencies=[
                                                        Role("rsyslog"),
                                                        Role("journald"),
                                                        Role("systohc"),
                                                        Role("configfs"),
                                                        Role("packages"),
                                                        Role("sysctl"),
                                                        Role("limits"),
                                                        Role("services"),
                                                        Role("motd"),
                                                        Role("rng"),
                                                        Role("smartd"),
                                                        Role("cleanup"),
                                                        Role("timezone"),
                                                        Role("docker"),
                                                        Role("docker-compose"),
                                                        Role("chrony"),
                                                        Role("lldpd"),
                                                    ],
                                                )
                                            ],
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        ),
    ],
    "cloudpod-infrastructure": [
        Role("openstackclient"),
        Role("phpmyadmin"),
        Role(
            "common",
            dependencies=[
                Role(
                    "loadbalancer",
                    dependencies=[
                        Role("letsencrypt"),
                        Role("opensearch"),
                        Role("mariadb"),
                    ],
                ),
                Role("openvswitch", dependencies=[Role("ovn")]),
                Role("memcached"),
                Role("redis", until="2025.1"),
                Role("valkey", since="2025.2"),
                Role("rabbitmq"),
            ],
        ),
    ],
    "cloudpod-openstack": [
        Role("horizon"),
        Role(
            "keystone",
            dependencies=[
                Role("glance"),
                Role("cinder"),
                Role(
                    "neutron",
                    dependencies=[
                        Role("wait-for-nova", dependencies=[Role("octavia")]),
                    ],
                ),
                Role("placement", dependencies=[Role("nova")]),
                Role("designate"),
                Role("skyline"),
                Role("kolla-ceph-rgw"),
            ],
        ),
    ],
    "cloudpod-ceph": [
        Role(
            "ceph-create-lvm-devices",
            dependencies=[
                Role("facts"),
                Role(
                    "ceph",
                    dependencies=[
                        Role(
                            "ceph-pools",
                            dependencies=[
                                Role(
                                    "copy-ceph-keys",
                                    dependencies=[
                                        Role(
                                            "cephclient",
                                            dependencies=[
                                                Role("ceph-bootstrap-dashboard")
                                            ],
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                ),
            ],
        ),
    ],
}
