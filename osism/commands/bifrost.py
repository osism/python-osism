import argparse
import logging

from cliff.command import Command

from osism.tasks import ansible


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Arguments for Bifrost')
        return parser

    def take_action(self, parsed_args):
        task = ansible.run.delay("manager", "bifrost-command", parsed_args.arguments)
        task.wait(timeout=None, interval=0.5)
        result = task.get()
        print(result)
