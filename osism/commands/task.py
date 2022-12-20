from datetime import datetime

from celery import Celery
from cliff.command import Command
from redis import Redis
from tabulate import tabulate

from osism.tasks import Config


class List(Command):
    def get_parser(self, prog_name):
        parser = super(List, self).get_parser(prog_name)
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


class Revoke(Command):
    def get_parser(self, prog_name):
        parser = super(Revoke, self).get_parser(prog_name)
        parser.add_argument("task", nargs=1, type=str, help="Task to revoke")
        return parser

    def take_action(self, parsed_args):
        task = parsed_args.task

        app = Celery("task")
        app.config_from_object(Config)
        app.control.revoke(task, terminate=True)
