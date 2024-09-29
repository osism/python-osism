# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone

from cliff.command import Command
import dateutil
import keystoneauth1
from loguru import logger
import openstack
from tabulate import tabulate

# from prompt_toolkit import prompt


def get_cloud_connection():
    try:
        conn = openstack.connect(cloud="admin")
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass

    return conn


class ServerList(Command):
    def get_parser(self, prog_name):
        parser = super(ServerList, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        conn = get_cloud_connection()

        result = []
        for server in conn.compute.servers(all_projects=True, status="build"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                server.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Server {server.id} hangs in BUILD status for more than 2 hours"
                )
                result.append([server.id, server.name, server.status])

        for server in conn.compute.servers(all_projects=True, status="error"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                server.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Server {server.id} hangs in ERRORstatus for more than 2 hours"
                )
                result.append([server.id, server.name, server.status])

        print(
            tabulate(
                result,
                headers=["ID", "Name", "Status"],
                tablefmt="psql",
            )
        )
