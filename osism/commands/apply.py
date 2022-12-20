import argparse
import time

from celery import group
from celery.result import GroupResult
from cliff.command import Command
from loguru import logger

from osism.core import enums
from osism.tasks import ansible, ceph, kolla
from osism.utils import redis

MAP_ROLE2ROLE = {
    "ceph-basic": [
        "ceph-mons",
        "ceph-mgrs",
        "ceph-osds",
        "ceph-crash",
    ],
    "infrastructure-basic": [
        "openstackclient",
        "common",
        "loadbalancer",
        "elasticsearch",
        "kibana",
        "openvswitch",
        "memcached",
        "redis",
        "mariadb",
        "rabbitmq",
        "phpmyadmin",
    ],
    "openstack-basic": [
        "keystone",
        "horizon",
        "placement",
        "glance",
        "cinder",
        "neutron",
        "nova",
        "barbican",
        "designate",
        "heat",
        "octavia",
    ],
    "openstack-extended": ["gnocchi", "ceilometer", "aodh", "senlin"],
}

# NOTE: Can be made more elegant later
MAP_ROLE2ENVIRONMENT = {
    # MONITORING
    "netdata": "monitoring",
    "remove-netdata": "monitoring",
    "remove-zabbix-agent": "monitoring",
    "openstack-health-monitor": "monitoring",
    # GENERIC
    "auditd": "generic",
    "backup-mariadb": "generic",
    "bootstrap": "generic",
    "check-reboot": "generic",
    "chrony": "generic",
    "chrony-force-sync": "generic",
    "clamav": "generic",
    "cleanup": "generic",
    "cleanup-backup-mariadb": "generic",
    "cleanup-databases": "generic",
    "cleanup-docker": "generic",
    "cleanup-docker-images": "generic",
    "cleanup-elasticsearch": "generic",
    "cleanup-queues": "generic",
    "cleanup-sosreport": "generic",
    "cockpit": "generic",
    "configfs": "generic",
    "docker": "generic",
    "docker-compose": "generic",
    "dotfiles": "generic",
    "dump-facts": "generic",
    "facts": "generic",
    "fail2ban": "generic",
    "falco": "generic",
    "firewall": "generic",
    "grub": "generic",
    "halt": "generic",
    "hardening": "generic",
    "hddtemp": "generic",
    "hostname": "generic",
    "hosts": "generic",
    "ipmitool": "generic",
    "journald": "generic",
    "kernel-modules": "generic",
    "known-hosts": "generic",
    "kompose": "generic",
    "lldpd": "generic",
    "lynis": "generic",
    "maintenance": "generic",
    "manage-container": "generic",
    "manage-service": "generic",
    "microcode": "generic",
    "motd": "generic",
    "network": "generic",
    "operator": "generic",
    "osquery": "generic",
    "packages": "generic",
    "patchman-client": "generic",
    "ping": "generic",
    "podman": "generic",
    "proxy": "generic",
    "python": "generic",
    "python3": "generic",
    "reboot": "generic",
    "remove-deploy-user": "generic",
    "repository": "generic",
    "resolvconf": "generic",
    "rng": "generic",
    "rsyslog": "generic",
    "services": "generic",
    "smartd": "generic",
    "sosreport": "generic",
    "state": "generic",
    "sysctl": "generic",
    "sysdig": "generic",
    "systohc": "generic",
    "timezone": "generic",
    "trivy": "generic",
    "upgrade-packages": "generic",
    "utilities": "generic",
    "wait-for-connection": "generic",
    "write-facts": "generic",
    # INFRASTRUCTURE
    "adminer": "infrastructure",
    "cephclient": "infrastructure",
    "cgit": "infrastructure",
    "clevis": "infrastructure",
    "dnsdist": "infrastructure",
    "helper": "infrastructure",
    "homer": "infrastructure",
    "jenkins": "infrastructure",
    "keycloak": "infrastructure",
    "kubectl": "infrastructure",
    "minikube": "infrastructure",
    "mirror": "infrastructure",
    "mirror-images": "infrastructure",
    "netbox": "infrastructure",
    "nexus": "infrastructure",
    "openldap": "infrastructure",
    "openstackclient": "infrastructure",
    "patchman": "infrastructure",
    "phpmyadmin": "infrastructure",
    "rundeck": "infrastructure",
    "squid": "infrastructure",
    "sshconfig": "infrastructure",
    "tailscale": "infrastructure",
    "tang": "infrastructure",
    "traefik": "infrastructure",
    "virtualbmc": "infrastructure",
    "wireguard": "infrastructure",
    "zuul": "infrastructure",
    # MANAGER
    "configuration": "manager",
    "copy-ceph-keys": "manager",
    "manager-network": "manager",
    "manager-operator": "manager",
    "vault-import": "manager",
    "vault-init": "manager",
    "vault-seal": "manager",
    "vault-unseal": "manager",
    # CEPH
    "ceph-add-mon": "ceph",
    "ceph-bootstrap-dashboard": "ceph",
    "ceph-ceph-keys": "ceph",
    "ceph-cephadm-adopt": "ceph",
    "ceph-cephadm": "ceph",
    "ceph-clients": "ceph",
    "ceph-config": "ceph",
    "ceph-crash": "ceph",
    "ceph-docker-to-podman": "ceph",
    "ceph-facts": "ceph",
    "ceph-fetch-keys": "ceph",
    "ceph-filestore-to-bluestore": "ceph",
    "ceph-gather-ceph-logs": "ceph",
    "ceph-iscsigws": "ceph",
    "ceph-lv-create": "ceph",
    "ceph-lv-teardown": "ceph",
    "ceph-mdss": "ceph",
    "ceph-mgrs": "ceph",
    "ceph-mons": "ceph",
    "ceph-nfss": "ceph",
    "ceph-osds": "ceph",
    "ceph-purge-cluster": "ceph",
    "ceph-purge-storage-node": "ceph",
    "ceph-rbd-mirrors": "ceph",
    "ceph-restapis": "ceph",
    "ceph-rgw-add-users-buckets": "ceph",
    "ceph-rgws": "ceph",
    "ceph-rolling_update": "ceph",
    "ceph-shrink-mds": "ceph",
    "ceph-shrink-mgr": "ceph",
    "ceph-shrink-mon": "ceph",
    "ceph-shrink-osd": "ceph",
    "ceph-shrink-rbdmirror": "ceph",
    "ceph-shrink-rgw": "ceph",
    "ceph-site": "ceph",
    "ceph-storage-inventory": "ceph",
    "ceph-switch-from-non-containerized-to-containerized-ceph-daemons": "ceph",
    "ceph-take-over-existing-cluster": "ceph",
    "ceph-base": "ceph",
    # KOLLA
    "aodh": "kolla",
    "barbican": "kolla",
    "bifrost-keypair": "kolla",
    "bifrost": "kolla",
    "blazar": "kolla",
    "ceilometer": "kolla",
    "certificates": "kolla",
    "chrony-cleanup": "kolla",
    # "chrony": "kolla",
    "cinder": "kolla",
    "cloudkitty": "kolla",
    "collectd": "kolla",
    "common": "kolla",
    "cyborg": "kolla",
    "designate": "kolla",
    "kolla-destroy": "kolla",
    "elasticsearch": "kolla",
    "etcd": "kolla",
    "kolla-facts": "kolla",
    "freezer": "kolla",
    "kolla-gather-facts": "kolla",
    "glance": "kolla",
    "gnocchi": "kolla",
    "grafana": "kolla",
    "hacluster": "kolla",
    "haproxy": "kolla",
    "heat": "kolla",
    "horizon": "kolla",
    "influxdb": "kolla",
    "ironic": "kolla",
    "iscsi": "kolla",
    "kafka": "kolla",
    "keystone": "kolla",
    "kibana": "kolla",
    "kuryr": "kolla",
    "loadbalancer": "kolla",
    "magnum": "kolla",
    "manila": "kolla",
    "mariadb-dynamic-rows": "kolla",
    "mariadb": "kolla",
    "mariadb_backup": "kolla",
    "mariadb_recovery": "kolla",
    "masakari": "kolla",
    "memcached": "kolla",
    "mistral": "kolla",
    "monasca": "kolla",
    "monasca_cleanup": "kolla",
    "multipathd": "kolla",
    "murano": "kolla",
    "neutron": "kolla",
    "nova-compute": "kolla",
    "nova": "kolla",
    "octavia-certificates": "kolla",
    "octavia": "kolla",
    "openvswitch": "kolla",
    "ovn": "kolla",
    "ovs-dpdk": "kolla",
    "panko": "kolla",
    "placement": "kolla",
    "prechecks": "kolla",
    "prometheus": "kolla",
    "kolla-prune-images": "kolla",
    "kolla-purge": "kolla",
    "qdrouterd": "kolla",
    "rabbitmq-outward": "kolla",
    "rabbitmq": "kolla",
    "rally": "kolla",
    "redis": "kolla",
    "kolla-rgw-endpoint": "kolla",
    "sahara": "kolla",
    "senlin": "kolla",
    "kolla-site": "kolla",
    "skydive": "kolla",
    "solum": "kolla",
    "storm": "kolla",
    "swift": "kolla",
    "tacker": "kolla",
    "telegraf": "kolla",
    "tempest": "kolla",
    "kolla-testbed-identity": "kolla",
    "kolla-testbed": "kolla",
    "trove": "kolla",
    "vitrage": "kolla",
    "vmtp": "kolla",
    "watcher": "kolla",
    "zookeeper": "kolla",
    "zun": "kolla",
}


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--environment", type=str, help="Environment that is to be used explicitly"
        )
        parser.add_argument("role", nargs=1, type=str, help="Role to be applied")
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        ),
        parser.add_argument(
            "--timeout",
            default=300,
            type=int,
            help="Timeout to end if there is no output",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def _handle_loadbalancer(self, t, wait, format, timeout):
        # process the parent task
        rc = self._handle_task(t.parent, wait, format, timeout)

        # It is necessary to wait for all task even if this is not excpected by the
        # user because of the following exception thrown by the garbage collector.
        #
        # Exception ignored in: <function AsyncResult.__del__ at 0x7f8c91ac74c0>
        # Traceback (most recent call last):
        # [...]
        # ImportError: sys.meta_path is None, Python is likely shutting down

        if not wait:
            t.parent.get()

        # process the child tasks
        if format == "log":
            for c in t.children:
                logger.info(
                    f"Task {c.task_id} is running in background. No more output. Check ARA for logs."
                )

        # As explained above, it is neceesary to wait for all tasks.
        t.get()

        return rc

    def _handle_task(self, t, wait, format, timeout):
        rc = 0
        if wait:
            p = redis.pubsub()
            p.subscribe(f"{t.task_id}")

            stoptime = time.time() + timeout
            while time.time() < stoptime:
                m = p.get_message(timeout=stoptime - time.time())
                if m:
                    stoptime = time.time() + timeout
                    if type(m["data"]) == bytes:
                        line = m["data"].decode("utf-8")
                        if line.startswith("RC: "):
                            rc = int(line[4:])
                            continue
                        if line == "QUIT":
                            redis.close()
                            # NOTE: Use better solution
                            return rc
                        print(line, end="")
                else:
                    logger.info(
                        f"No further output after {timeout} seconds. Therefore finish."
                    )
                    return rc

        else:
            if format == "log":
                logger.info(
                    f"Task {t.task_id} is running in background. No more output. Check ARA for logs."
                )
            elif format == "script":
                print(f"{t.task_id}")

            return rc

    def handle_role(self, arguments, environment, role, wait, format, timeout):
        if not environment:
            try:
                environment = MAP_ROLE2ENVIRONMENT[role]
            except:  # noqa: E722
                environment = "custom"

        if environment == "ceph":
            if role.startswith("ceph-"):
                t = ceph.run.delay(role[5:], arguments)
            else:
                t = ceph.run.delay(role, arguments)
        elif environment == "kolla":
            if role.startswith("kolla-"):
                t = kolla.run.delay(role[6:], arguments)
            else:
                t = kolla.run.delay(role, arguments)
        elif role == "loadbalancer-ng":
            g = group(
                kolla.run.si(playbook, arguments)
                for playbook in enums.LOADBALANCER_PLAYBOOKS
            )
            t = (kolla.run.s("loadbalancer-ng", arguments) | g).apply_async()
        else:
            t = ansible.run.delay(environment, role, arguments)

        if isinstance(t, GroupResult):
            rc = self._handle_loadbalancer(t, wait, format, timeout)
        else:
            rc = self._handle_task(t, wait, format, timeout)

        return rc

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        environment = parsed_args.environment
        format = parsed_args.format
        role = parsed_args.role[0]
        timeout = parsed_args.timeout
        wait = not parsed_args.no_wait

        if role in MAP_ROLE2ROLE:
            for r in MAP_ROLE2ROLE[role]:
                rc = self.handle_role(arguments, environment, r, wait, format, timeout)
                if rc != 0:
                    break
        else:
            rc = self.handle_role(arguments, environment, role, wait, format, timeout)

        return rc
