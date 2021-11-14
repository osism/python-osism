import logging

from cliff.command import Command

from osism.tasks import ansible


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('environment', nargs=1, type=str, help='Enviornment in which the playbook is to be run')
        parser.add_argument('playbook', nargs=1, type=str, help='Playbook to be executed')
        parser.add_argument('arguments', nargs='*', help='Other arguments for Ansible')
        return parser

    def take_action(self, parsed_args):
        environment = parsed_args.environment[0]
        playbook = parsed_args.playbook[0]
        arguments = parsed_args.arguments
        ansible.run.delay(environment, playbook, arguments)
