# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command

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

        arguments = [
            "-e status=True",
            "-l {host}",
        ]

        ansible.run.delay(
            "state",
            "maintenance",
            arguments,
            publish=False,
            locking=False,
        )
