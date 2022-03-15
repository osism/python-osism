import logging

from celery.task.control import revoke
from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('task', nargs=1, type=str, help='Task to revoke')
        return parser

    def take_action(self, parsed_args):
        task = parsed_args.role[0]

        revoke(task, terminate=True)
