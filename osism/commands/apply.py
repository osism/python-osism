import argparse
import logging

from cliff.command import Command
from redis import Redis

from osism.tasks import ansible, ceph, kolla

redis = Redis(host="redis", port="6379")


# NOTE: Can be made more elegant later
MAP_ROLE2ENVIRONMENT = {

    # MONITORING

    "netdata": "monitoring",
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
    "sshconfig": "infrastructure",
    "tailscale": "infrastructure",
    "traefik": "infrastructure",
    "virtualbmc": "infrastructure",
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
    "ceph-purge-container-cluster": "ceph",
    "ceph-purge-dashboard": "ceph",
    "ceph-purge-iscsi-gateways": "ceph",
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
    "ceph-testbed": "ceph",

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

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('--environment', type=str, help='Environment that is to be used explicitly')
        parser.add_argument('role', nargs=1, type=str, help='Role to be applied')
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Ansible')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the role has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        environment = parsed_args.environment
        role = parsed_args.role[0]
        wait = not parsed_args.no_wait

        if not environment:
            try:
                environment = MAP_ROLE2ENVIRONMENT[role]
            except:  # noqa: E722
                environment = "custom"

        if environment == "ceph":
            if role.startswith("ceph-"):
                ceph.run.delay(role[5:], arguments)
            else:
                ceph.run.delay(role, arguments)
        elif environment == "kolla":
            if role.startswith("kolla-"):
                kolla.run.delay(role[6:], arguments)
            else:
                kolla.run.delay(role, arguments)
        else:
            ansible.run.delay(environment, role, arguments)

        if wait:
            p = redis.pubsub()

            # NOTE: use task_id or request_id in future
            if environment == "ceph":
                p.subscribe(f"{role}")
            else:
                p.subscribe(f"{environment}-{role}")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            redis.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")
