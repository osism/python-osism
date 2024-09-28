# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
import keystoneauth1
from loguru import logger
import openstack
from tabulate import tabulate
from prompt_toolkit import prompt


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


class ComputeStop(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeStop, self).get_parser(prog_name)
        parser.add_argument(
            "--yes",
            default=False,
            help="Always say yes",
            action="store_true",
        )
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host on that all running instances are to be stopped",
        )
        return parser

    def take_action(self, parsed_args):
        yes = parsed_args.yes
        host = parsed_args.host[0]
        conn = get_cloud_connection()
        result = []

        for server in conn.compute.servers(all_projects=True, node=host):
            result.append([server.id, server.name, server.status])

        for server in result:
            if server[2] not in ["ACTIVE"]:
                logger.info(
                    f"{server[0]} ({server[1]}) in status {server[2]} cannot be stopped"
                )
                continue

            if not yes:
                answer = prompt(f"Stop server {server[0]} ({server[1]}) [yes/no]: ")

            if answer in ["yes", "y"]:
                logger.info(f"Stopping server {server[0]}")
                conn.compute.stop_server(server[0])
