# SPDX-License-Identifier: Apache-2.0

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

MAP_ROLE2ROLE = {
    "nutshell": [
        "dotfiles",
        "homer",
        "netdata",
        "openstackclient",
        "phpmyadmin",
        [
            "common",
            [
                [
                    "loadbalancer",
                    [
                        "opensearch",
                        [
                            "mariadb-ng",
                            [
                                "horizon",
                                [
                                    "keystone",
                                    [
                                        ["neutron", ["wait-for-nova", ["octavia"]]],
                                        "barbican",
                                        "designate",
                                        "ironic",
                                        "placement",
                                        "magnum",
                                    ],
                                ],
                            ],
                        ],
                    ],
                ],
                ["openvswitch", ["ovn"]],
                "memcached",
                "redis",
                "rabbitmq-ng",
            ],
        ],
        ["kubernetes", ["kubeconfig", ["copy-kubeconfig"]]],
        [
            "ceph",
            [
                [
                    "ceph-pools",
                    [
                        [
                            "copy-ceph-keys",
                            [
                                [
                                    "cephclient",
                                    [
                                        "ceph-bootstrap-dashboard",
                                        [
                                            "wait-for-keystone",
                                            [
                                                "kolla-ceph-rgw",
                                                "glance",
                                                "cinder",
                                                "nova",
                                            ],
                                        ],
                                        ["prometheus", ["grafana"]],
                                    ],
                                ],
                            ],
                        ],
                    ],
                ],
            ],
        ],
    ],
    "collection-infrastructure": [
        "openstackclient",
        "phpmyadmin",
        [
            "common",
            [
                ["loadbalancer", ["letsencrypt", "opensearch", "mariadb-ng"]],
                ["openvswitch", ["ovn"]],
                "memcached",
                "redis",
                "rabbitmq-ng",
            ],
        ],
    ],
    "collection-kubernetes": [
        ["kubernetes", ["kubeconfig", ["copy-kubeconfig"]]],
    ],
    "collection-openstack-core": [
        "horizon",
        [
            "keystone",
            [
                "glance",
                "cinder",
                ["neutron", ["octavia"]],
                "designate",
                ["placement", ["nova"]],
            ],
        ],
    ],
    "collection-openstack": [
        "horizon",
        [
            "keystone",
            [
                "glance",
                "cinder",
                "neutron",
                "barbican",
                "designate",
                "octavia",
                "ironic",
                "kolla-ceph-rgw",
                "magnum",
                ["placement", ["nova"]],
            ],
        ],
    ],
    "collection-ceph": [
        [
            "ceph",
            [
                [
                    "ceph-pools",
                    [
                        [
                            "copy-ceph-keys",
                            [["cephclient", ["ceph-bootstrap-dashboard"]]],
                        ]
                    ],
                ],
            ],
        ],
    ],
    "collection-monitoring": [
        ["prometheus", ["grafana"]],
        "netdata",
    ],
    "collection-bootstrap": [
        [
            "gather-facts",
            [
                [
                    "hostname",
                    [
                        [
                            "hosts",
                            [
                                [
                                    "proxy",
                                    [
                                        [
                                            "resolvconf",
                                            [
                                                [
                                                    "repository",
                                                    [
                                                        "rsyslog",
                                                        "journald",
                                                        "systohc",
                                                        "configfs",
                                                        "packages",
                                                        "sysctl",
                                                        "limits",
                                                        "services",
                                                        "motd",
                                                        "rng",
                                                        "smartd",
                                                        "cleanup",
                                                        "timezone",
                                                        "docker",
                                                        "docker-compose",
                                                        "chrony",
                                                        "lldpd",
                                                    ],
                                                ],
                                            ],
                                        ],
                                    ],
                                ],
                            ],
                        ],
                    ],
                ],
            ],
        ],
    ],
}
