import argparse
import subprocess

from cliff.command import Command


class Ansible(Command):
    def get_parser(self, prog_name):
        parser = super(Ansible, self).get_parser(prog_name)
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the ara command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        parameters = " ".join(parsed_args.parameter)
        subprocess.call(
            f"/usr/local/bin/ara {parameters}",
            shell=True,
        )


class Container(Command):
    def get_parser(self, prog_name):
        parser = super(Container, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        parser.add_argument(
            "container", nargs=1, type=str, help="Name of the container"
        )
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the docker logs command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        container_name = parsed_args.container[0]
        parameters = " ".join(parsed_args.parameter)

        ssh_command = f"docker logs {parameters} {container_name}"
        ssh_options = "-o StrictHostKeyChecking=no -o LogLevel=ERROR"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(
            f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{host} {ssh_command}",
            shell=True,
        )


class File(Command):
    def get_parser(self, prog_name):
        parser = super(File, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        return parser

    def take_action(self, parsed_args):
        print("NOT YET IMPLEMENTED")
