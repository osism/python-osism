from cliff.command import Command
import docker
import tabulate


class VersionsManager(Command):
    def get_parser(self, prog_name):
        parser = super(VersionsManager, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        client = docker.from_env()

        data = []

        for cname in ["osism-ansible", "ceph-ansible", "kolla-ansible"]:
            try:
                container = client.containers.get(cname)
                version = container.labels["org.opencontainers.image.version"]

                if cname == "ceph-ansible":
                    mrelease = container.labels["de.osism.release.ceph"]
                elif cname == "kolla-ansible":
                    mrelease = container.labels["de.osism.release.openstack"]
                else:
                    mrelease = ""

                data.append([cname, version, mrelease])
            except docker.errors.NotFound:
                pass

        result = tabulate.tabulate(
            data, headers=["Module", "OSISM version", "Module release"], tablefmt="psql"
        )
        print(result)
