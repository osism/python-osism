import argparse
import subprocess

from cliff.command import Command


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument("target", nargs=1, type=str, help="Hostname or address")
        parser.add_argument(
            "command",
            nargs=argparse.REMAINDER,
            type=str,
            help="Command to run",
        )
        return parser

    def take_action(self, parsed_args):
        target_hostname = parsed_args.target[0]
        command = " ".join(parsed_args.command)

        ssh_command = f"docker {command}"
        ssh_options = "-o StrictHostKeyChecking=no -o LogLevel=ERROR"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(
            f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{target_hostname} {ssh_command}",
            shell=True,
        )
