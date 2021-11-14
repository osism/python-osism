import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('type', nargs=1, type=str, help='Type of the worker')
        return parser

    def take_action(self, parsed_args):
        # NOTE: use python interface in the future, works for the moment
        p = subprocess.Popen("celery -A osism.tasks.ansible worker --loglevel=INFO -Q ansible", shell=True)
        p.wait()
