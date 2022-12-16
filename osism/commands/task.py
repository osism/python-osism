from celery.task.control import revoke
from cliff.command import Command
from redis import Redis

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


class Revoke(Command):
    def get_parser(self, prog_name):
        parser = super(Revoke, self).get_parser(prog_name)
        parser.add_argument("task", nargs=1, type=str, help="Task to revoke")
        return parser

    def take_action(self, parsed_args):
        task = parsed_args.role[0]

        revoke(task, terminate=True)
