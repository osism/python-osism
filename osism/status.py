import logging

from celery import Celery
from cliff.command import Command
from tabulate import tabulate

from osism.tasks import Config


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('type', nargs=1, type=str, help='Type of resource from which the status is to be displayed')
        return parser

    def take_action(self, parsed_args):
        type_of_resource = parsed_args.type[0]

        app = Celery('status')
        app.config_from_object(Config)

        if type_of_resource == "workers":
            table = []
            i = app.control.inspect()
            s = i.stats()
            for node, nodestats in s.items():
                table.append([
                    node,
                    s["uptime"]
                ])

            print(tabulate(table, headers=["Name", "Uptime"], tablefmt="psql"))
        else:
            logging.error(f"Unknown resource type '{type_of_resource}'")
