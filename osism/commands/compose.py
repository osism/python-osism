import argparse
import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Docker compose')
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        docker_compose_command = "/usr/bin/docker compose"

        subprocess.call(f"{docker_compose_command} {arguments}", shell=True)
