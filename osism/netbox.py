import logging

from cliff.command import Command

from osism.tasks import reconciler


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('action', nargs=1, type=str, help='Action to be applied')
        return parser

    def take_action(self, parsed_args):
        action = parsed_args.action[0]
        if action == "sync":
            reconciler.sync_inventory_with_netbox.delay()
