# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger

from osism.tasks import ansible


class NoMaintenance(Command):
    def get_parser(self, prog_name):
        parser = super(NoMaintenance, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host that should no longer be set to maintenance",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]

        logger.info(f"Set no maintenance state on host {host}")

        arguments = [
            "-e status=False",
            f"-l {host}",
        ]

        ansible.run.delay(
            "generic",
            "state-maintenance",
            arguments,
        )


class NoBootstrap(Command):
    def get_parser(self, prog_name):
        parser = super(NoBootstrap, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host that should no longer be set to bootstrapped",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]

        logger.info(f"Set not bootstrapped state on host {host}")

        arguments = [
            "-e status=False",
            f"-l {host}",
        ]

        ansible.run.delay(
            "generic",
            "state-bootstrap",
            arguments,
        )
