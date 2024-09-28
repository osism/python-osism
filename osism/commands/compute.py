# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
import keystoneauth1
import openstack
from tabulate import tabulate


def get_cloud_connection():
    try:
        conn = openstack.connect(cloud="admin")
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass

    return conn


class ComputeList(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeList, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host on that all running instances are to be listed",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        conn = get_cloud_connection()
        result = []

        for server in conn.compute.servers(all_projects=True, node=host):
            result.append([server.id, server.name, server.status])

        print(
            tabulate(
                result,
                headers=["ID", "Name", "Status"],
                tablefmt="psql",
            )
        )
