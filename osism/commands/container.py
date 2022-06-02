import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('target', nargs=1, type=str, help='Hostname or address')
        return parser

    def take_action(self, parsed_args):
        target_hostname = parsed_args.target[0]

        ssh_command = "docker ps"
        ssh_options = "-o StrictHostKeyChecking=no"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{target_hostname} {ssh_command}", shell=True)
