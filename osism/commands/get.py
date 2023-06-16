from datetime import datetime

from celery import Celery
from cliff.command import Command
from redis import Redis
from tabulate import tabulate

from osism.tasks import Config


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

        result = tabulate(
            data, headers=["Module", "OSISM version", "Module release"], tablefmt="psql"
        )
        print(result)


class Tasks(Command):
    def get_parser(self, prog_name):
        parser = super(Tasks, self).get_parser(prog_name)
        parser.add_argument(
            "--status", default="all", help="Status of the tasks to list"
        )
        return parser

    def take_action(self, parsed_args):
        status = parsed_args.status
        redis = Redis(host="redis", port="6379")

        app = Celery("task")
        app.config_from_object(Config)

        i = app.control.inspect()

        table = []

        task_status = "ACTIVE"
        for worker, tasks in i.active().items():
            for task in tasks:
                time_start = datetime.fromtimestamp(task["time_start"])
                table.append(
                    [
                        worker,
                        task["id"],
                        task["name"],
                        task_status,
                        time_start,
                        task["args"],
                    ]
                )

        task_status = "SCHEDULED"
        for worker, tasks in i.scheduled().items():
            for task in tasks:
                time_start = datetime.fromtimestamp(task["time_start"])
                table.append(
                    [
                        worker,
                        task["id"],
                        task["name"],
                        task_status,
                        time_start,
                        task["args"],
                    ]
                )

        print(
            tabulate(
                table,
                headers=["Worker", "ID", "Name", "Status", "Start time", "Arguments"],
                tablefmt="psql",
            )
        )
