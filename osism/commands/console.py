import logging

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('--type', default="ssh", help='Type of the console')
        parser.add_argument('target', nargs=1, type=str, help='Hostname or address of the console to connect')
        return parser

    def take_action(self, parsed_args):
        console_type = parsed_args.type
        console_target = parsed_args.target[0]

        print(console_target)
        print(console_type)
