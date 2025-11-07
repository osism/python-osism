# SPDX-License-Identifier: Apache-2.0


class Role:
    """
    Represents a role with optional dependencies in a hierarchical structure.

    Args:
        name: The name of the role (string)
        dependencies: Optional list of dependent Role objects

    Example:
        >>> role = Role("keystone", dependencies=[Role("glance"), Role("cinder")])
        >>> role.name
        'keystone'
        >>> len(role.dependencies)
        2
    """

    def __init__(self, name, dependencies=None):
        """Initialize a Role with a name and optional dependencies."""
        self.name = name
        self.dependencies = dependencies or []


LOADBALANCER_PLAYBOOKS = [
    "loadbalancer-aodh",
    "loadbalancer-barbican",
    "loadbalancer-blazar",
    "loadbalancer-ceph-rgw",
    "loadbalancer-cinder",
    "loadbalancer-designate",
    "loadbalancer-glance",
    "loadbalancer-gnocchi",
    "loadbalancer-grafana",
    "loadbalancer-heat",
    "loadbalancer-horizon",
    "loadbalancer-ironic",
    "loadbalancer-keystone",
    "loadbalancer-magnum",
    "loadbalancer-manila",
    "loadbalancer-mariadb",
    "loadbalancer-memcached",
    "loadbalancer-neutron",
    "loadbalancer-nova",
    "loadbalancer-octavia",
    "loadbalancer-opensearch",
    "loadbalancer-placement",
    "loadbalancer-prometheus",
    "loadbalancer-rabbitmq",
    "loadbalancer-skydive",
]

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
                            "mariadb-ng",
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
                Role("redis"),
                Role("rabbitmq-ng"),
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
                        Role("mariadb-ng"),
                    ],
                ),
                Role("openvswitch", dependencies=[Role("ovn")]),
                Role("memcached"),
                Role("redis"),
                Role("rabbitmq-ng"),
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
                        Role("mariadb-ng"),
                    ],
                ),
                Role("openvswitch", dependencies=[Role("ovn")]),
                Role("memcached"),
                Role("redis"),
                Role("rabbitmq-ng"),
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
