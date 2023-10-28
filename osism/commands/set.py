# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger

from osism.tasks import ansible


class Maintenance(Command):
    def get_parser(self, prog_name):
        parser = super(Maintenance, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host to be set to maintenance",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]

        logger.info(f"Set maintenance state on host {host}")

        arguments = [
            "-e status=True",
            f"-l {host}",
        ]

        ansible.run.delay(
            "generic",
            "state-maintenance",
            arguments,
        )


class Bootstrap(Command):
    def get_parser(self, prog_name):
        parser = super(Bootstrap, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host to be set to bootstrapped",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]

        logger.info(f"Set bootstraped state on host {host}")

        arguments = [
            "-e status=True",
            f"-l {host}",
        ]

        ansible.run.delay(
            "generic",
            "state-bootstrap",
            arguments,
        )
