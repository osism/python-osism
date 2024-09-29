# SPDX-License-Identifier: Apache-2.0

import time

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


class ComputeEnable(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeEnable, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host to be enabled",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        conn = get_cloud_connection()

        services = conn.compute.services(**{"host": host, "binary": "nova-compute"})
        service = next(services)
        logger.info(f"Enabling nova-compute binary @ {host} ({service.id})")
        conn.compute.enable_service(
            service=service.id,
            host=host,
            binary="nova-compute",
        )


class ComputeDisable(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeDisable, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host to be disabled",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        conn = get_cloud_connection()

        services = conn.compute.services(**{"host": host, "binary": "nova-compute"})
        service = next(services)
        logger.info(f"Disabling nova-compute binary @ {host} ({service.id})")
        conn.compute.disable_service(
            service=service.id,
            host=host,
            binary="nova-compute",
            disabled_reason="MAINTENANCE",
        )


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


class ComputeMigrate(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeMigrate, self).get_parser(prog_name)
        parser.add_argument(
            "--yes",
            default=False,
            help="Always say yes",
            action="store_true",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait for completion of migration",
            action="store_true",
        )
        parser.add_argument(
            "--force",
            default=False,
            help="Force a live-migration by not verifying the provided destination host by the scheduler. ",
            action="store_true",
        )
        parser.add_argument(
            "--target",
            default=None,
            type=str,
            help="Host to which all running instances are to be migrated",
        )
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Host on that all running instances are to be migrated",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        target = parsed_args.target
        force = parsed_args.force
        no_wait = parsed_args.no_wait
        yes = parsed_args.yes
        conn = get_cloud_connection()

        result = []
        for server in conn.compute.servers(all_projects=True, node=host):
            result.append([server.id, server.name, server.status])

        for server in result:
            if server[2] not in ["ACTIVE"]:
                logger.info(
                    f"{server[0]} ({server[1]}) in status {server[2]} cannot be live migrated"
                )
                continue

            if yes:
                answer = "yes"
            else:
                answer = prompt(
                    f"Live migrate server {server[0]} ({server[1]}) [yes/no]: "
                )

            if answer in ["yes", "y"]:
                logger.info(f"Live migrating server {server[0]}")
                conn.compute.live_migrate_server(
                    server[0], host=target, block_migration="auto", force=force
                )

                if not no_wait:
                    inner_wait = True
                    while inner_wait:
                        time.sleep(2)
                        s = conn.compute.get_server(server[0])
                        if s.status in ["MIGRATING"]:
                            logger.info(
                                f"Live migration of {server[0]} ({server[1]}) is still in progress"
                            )
                            inner_wait = True
                        else:
                            inner_wait = False


class ComputeStart(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeStart, self).get_parser(prog_name)
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
            help="Host on that all running instances are to be started",
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
            if server[2] not in ["SHUTOFF"]:
                logger.info(
                    f"{server[0]} ({server[1]}) in status {server[2]} cannot be started"
                )
                continue

            if yes:
                answer = "yes"
            else:
                answer = prompt(f"Start server {server[0]} ({server[1]}) [yes/no]: ")

            if answer in ["yes", "y"]:
                logger.info(f"Starting server {server[0]}")
                conn.compute.start_server(server[0])


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

            if yes:
                answer = "yes"
            else:
                answer = prompt(f"Stop server {server[0]} ({server[1]}) [yes/no]: ")

            if answer in ["yes", "y"]:
                logger.info(f"Stopping server {server[0]}")
                conn.compute.stop_server(server[0])
