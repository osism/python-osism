from celery import Celery
from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.tasks import Config

# https://stackoverflow.com/questions/4048651/python-function-to-convert-seconds-into-minutes-hours-and-days/4048773

INTERVALS = (
    ("weeks", 604800),  # 60 * 60 * 24 * 7
    ("days", 86400),  # 60 * 60 * 24
    ("hours", 3600),  # 60 * 60
    ("minutes", 60),
    ("seconds", 1),
)


def display_time(seconds, granularity=2):
    result = []

    for name, count in INTERVALS:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip("s")
            result.append("{} {}".format(value, name))
    return ", ".join(result[:granularity])


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            nargs=1,
            type=str,
            choices=["workers"],
            help="Type of resource from which the status is to be displayed",
        )
        return parser

    def take_action(self, parsed_args):
        type_of_resource = parsed_args.type[0]

        app = Celery("status")
        app.config_from_object(Config)

        if type_of_resource == "workers":
            table = []
            i = app.control.inspect()
            s = i.stats()
            for node in sorted(s.keys()):
                ping = i.ping(destination=[node])
                if not ping:
                    health_status = "NOT REACHABLE"
                else:
                    health_status = "REACHABLE"
                table.append([node, display_time(s[node]["uptime"]), health_status])

            print(
                tabulate(table, headers=["Name", "Uptime", "Status"], tablefmt="psql")
            )
        else:
            logger.error(f"Unknown resource type '{type_of_resource}'")
