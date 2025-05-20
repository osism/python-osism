# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command

from tabulate import tabulate

from osism.commands import get_cloud_connection


class BaremetalList(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalList, self).get_parser(prog_name)
        parser.add_argument(
            "--provision-state",
            default=None,
            choices=["enroll", "managable", "available", "active", "error"],
            type=str,
            help="Only list nodes with the given provision state",
        )
        parser.add_argument(
            "--maintenance",
            default=False,
            action="store_true",
            help="Only list baremetal nodes in maintenance mode",
        )
        return parser

    def take_action(self, parsed_args):
        provision_state = parsed_args.provision_state
        maintenance = parsed_args.maintenance

        conn = get_cloud_connection()

        query = {}
        if provision_state:
            query.update(dict(provision_state=provision_state))
        if maintenance:
            query.update(dict(maintenance=maintenance))

        baremetal = conn.baremetal.nodes(**query)

        result = [
            [
                b["name"],
                b["power_state"],
                b["provision_state"],
                b["maintenance"],
            ]
            for b in baremetal
        ]

        print(
            tabulate(
                result,
                headers=[
                    "Name",
                    "Power State",
                    "Provision State",
                    "Maintenance",
                ],
                tablefmt="psql",
            )
        )
