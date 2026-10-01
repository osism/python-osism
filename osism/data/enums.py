# SPDX-License-Identifier: Apache-2.0

from osism.data.plans import Parallel, Run, Select, Sequence

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
    "ceph-rgws": {"environment": "ceph", "runtime": "osism-ansible"},
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

# Explicit execution plans: siblings run concurrently; sequences impose barriers.
MAP_ROLE2ROLE = {
    "nutshell": Parallel(
        Run("dotfiles"),
        Run("homer"),
        Run("netdata"),
        Run("openstackclient"),
        Run("phpmyadmin"),
        Sequence(
            Run("common"),
            Parallel(
                Sequence(
                    Run("loadbalancer"),
                    Parallel(
                        Run("opensearch"),
                        Sequence(
                            Run("mariadb"),
                            Parallel(
                                Run("horizon"),
                                Sequence(
                                    Run("keystone"),
                                    Parallel(
                                        Sequence(
                                            Run("neutron"),
                                            Parallel(
                                                Sequence(
                                                    Run("wait-for-nova"),
                                                    Parallel(Run("octavia")),
                                                )
                                            ),
                                        ),
                                        Run("barbican"),
                                        Run("designate"),
                                        Run("ironic"),
                                        Run("placement"),
                                        Run("magnum"),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Sequence(Run("openvswitch"), Parallel(Run("ovn"))),
                Run("memcached"),
                Select("kvs_backend", {"redis": Run("redis"), "valkey": Run("valkey")}),
                Run("rabbitmq"),
            ),
        ),
        Sequence(
            Run("kubernetes"), Parallel(Run("kubeconfig"), Run("copy-kubeconfig"))
        ),
        Sequence(
            Run("ceph"),
            Parallel(
                Sequence(
                    Run("ceph-pools"),
                    Parallel(
                        Sequence(
                            Run("copy-ceph-keys"),
                            Parallel(
                                Sequence(
                                    Run("cephclient"),
                                    Parallel(
                                        Run("ceph-bootstrap-dashboard"),
                                        Sequence(
                                            Run("wait-for-keystone"),
                                            Parallel(
                                                Run("kolla-ceph-rgw"),
                                                Run("glance"),
                                                Run("cinder"),
                                                Run("nova"),
                                            ),
                                        ),
                                        Sequence(
                                            Run("prometheus"), Parallel(Run("grafana"))
                                        ),
                                    ),
                                )
                            ),
                        )
                    ),
                )
            ),
        ),
    ),
    "collection-infrastructure": Parallel(
        Run("openstackclient"),
        Run("phpmyadmin"),
        Sequence(
            Run("common"),
            Parallel(
                Sequence(
                    Run("loadbalancer"),
                    Parallel(Run("letsencrypt"), Run("opensearch"), Run("mariadb")),
                ),
                Sequence(Run("openvswitch"), Parallel(Run("ovn"))),
                Run("memcached"),
                Select("kvs_backend", {"redis": Run("redis"), "valkey": Run("valkey")}),
                Run("rabbitmq"),
            ),
        ),
    ),
    "collection-kubernetes": Parallel(
        Sequence(Run("kubernetes"), Parallel(Run("kubeconfig"), Run("copy-kubeconfig")))
    ),
    "collection-openstack-core": Parallel(
        Run("horizon"),
        Sequence(
            Run("keystone"),
            Parallel(
                Run("glance"),
                Run("cinder"),
                Sequence(
                    Run("neutron"),
                    Parallel(Sequence(Run("wait-for-nova"), Parallel(Run("octavia")))),
                ),
                Run("designate"),
                Sequence(Run("placement"), Parallel(Run("nova"))),
            ),
        ),
    ),
    "collection-openstack": Parallel(
        Run("horizon"),
        Sequence(
            Run("keystone"),
            Parallel(
                Run("glance"),
                Run("cinder"),
                Run("barbican"),
                Run("designate"),
                Sequence(
                    Run("neutron"),
                    Parallel(Sequence(Run("wait-for-nova"), Parallel(Run("octavia")))),
                ),
                Run("ironic"),
                Run("kolla-ceph-rgw"),
                Run("magnum"),
                Sequence(Run("placement"), Parallel(Run("nova"))),
            ),
        ),
    ),
    "collection-ceph": Parallel(
        Sequence(
            Run("ceph"),
            Parallel(
                Sequence(
                    Run("ceph-pools"),
                    Parallel(
                        Sequence(
                            Run("copy-ceph-keys"),
                            Parallel(
                                Sequence(
                                    Run("cephclient"),
                                    Parallel(Run("ceph-bootstrap-dashboard")),
                                )
                            ),
                        )
                    ),
                )
            ),
        )
    ),
    "collection-monitoring": Parallel(
        Sequence(Run("prometheus"), Parallel(Run("grafana"))), Run("netdata")
    ),
    "collection-bootstrap": Parallel(
        Sequence(
            Run("gather-facts"),
            Parallel(
                Sequence(
                    Run("hostname"),
                    Parallel(
                        Sequence(
                            Run("hosts"),
                            Parallel(
                                Sequence(
                                    Run("proxy"),
                                    Parallel(
                                        Sequence(
                                            Run("resolvconf"),
                                            Parallel(
                                                Sequence(
                                                    Run("repository"),
                                                    Parallel(
                                                        Run("rsyslog"),
                                                        Run("journald"),
                                                        Run("systohc"),
                                                        Run("configfs"),
                                                        Run("packages"),
                                                        Run("sysctl"),
                                                        Run("limits"),
                                                        Run("services"),
                                                        Run("motd"),
                                                        Run("rng"),
                                                        Run("smartd"),
                                                        Run("cleanup"),
                                                        Run("timezone"),
                                                        Run("docker"),
                                                        Run("docker-compose"),
                                                        Run("chrony"),
                                                        Run("lldpd"),
                                                    ),
                                                )
                                            ),
                                        )
                                    ),
                                )
                            ),
                        )
                    ),
                )
            ),
        )
    ),
    "cloudpod-infrastructure": Parallel(
        Run("openstackclient"),
        Run("phpmyadmin"),
        Sequence(
            Run("common"),
            Parallel(
                Sequence(
                    Run("loadbalancer"),
                    Parallel(Run("letsencrypt"), Run("opensearch"), Run("mariadb")),
                ),
                Sequence(Run("openvswitch"), Parallel(Run("ovn"))),
                Run("memcached"),
                Select("kvs_backend", {"redis": Run("redis"), "valkey": Run("valkey")}),
                Run("rabbitmq"),
            ),
        ),
    ),
    "cloudpod-openstack": Parallel(
        Run("horizon"),
        Sequence(
            Run("keystone"),
            Parallel(
                Run("glance"),
                Run("cinder"),
                Sequence(
                    Run("neutron"),
                    Parallel(Sequence(Run("wait-for-nova"), Parallel(Run("octavia")))),
                ),
                Sequence(Run("placement"), Parallel(Run("nova"))),
                Run("designate"),
                Run("skyline"),
                Run("kolla-ceph-rgw"),
            ),
        ),
    ),
    "cloudpod-ceph": Parallel(
        Sequence(
            Run("ceph-create-lvm-devices"),
            Parallel(
                Run("facts"),
                Sequence(
                    Run("ceph"),
                    Parallel(
                        Sequence(
                            Run("ceph-pools"),
                            Parallel(
                                Sequence(
                                    Run("copy-ceph-keys"),
                                    Parallel(
                                        Sequence(
                                            Run("cephclient"),
                                            Parallel(Run("ceph-bootstrap-dashboard")),
                                        )
                                    ),
                                )
                            ),
                        )
                    ),
                ),
            ),
        )
    ),
}
