# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
import time

from cliff.command import Command
import dateutil
from loguru import logger
from tabulate import tabulate
from prompt_toolkit import prompt

from osism.commands import get_cloud_connection


class ServerMigrate(Command):
    def get_parser(self, prog_name):
        parser = super(ServerMigrate, self).get_parser(prog_name)
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
            help="Host to which the rinstance is to be migrated",
        )
        parser.add_argument(
            "instance",
            nargs=1,
            type=str,
            help="Instance to be migrated (specify ID)",
        )
        return parser

    def take_action(self, parsed_args):
        yes = parsed_args.yes
        instance = parsed_args.instance[0]
        target = parsed_args.target
        force = parsed_args.force
        no_wait = parsed_args.no_wait

        conn = get_cloud_connection()

        result = conn.compute.get_server(instance)
        server = [result.id, result.name, result.status]

        if server[2] not in ["ACTIVE", "PAUSED"]:
            logger.info(
                f"{server[0]} ({server[1]}) in status {server[2]} cannot be live migrated"
            )
            return

        if yes:
            answer = "yes"
        else:
            answer = prompt(f"Live migrate server {server[0]} ({server[1]}) [yes/no]: ")

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


class ServerList(Command):
    def get_parser(self, prog_name):
        parser = super(ServerList, self).get_parser(prog_name)
        parser.add_argument(
            "--domain",
            help="List all servers of a specific domain",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--project",
            help="List all servers of a specific project",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--project-domain", help="Domain of the project", type=str, default=None
        )
        return parser

    def take_action(self, parsed_args):
        conn = get_cloud_connection()
        domain = parsed_args.domain
        project = parsed_args.project
        project_domain = parsed_args.project_domain

        result = []
        if domain:
            _domain = conn.identity.find_domain(domain)
            if not _domain:
                logger.error(f"Domain {domain} not found")
                return
            projects = list(conn.identity.projects(domain_id=_domain.id))

            for project in projects:
                query = {"project_id": project.id}
                for server in conn.compute.servers(all_projects=True, **query):
                    result.append(
                        [
                            project.name,
                            project.id,
                            server.id,
                            server.name,
                            server.flavor["original_name"],
                            server.status,
                        ]
                    )

            print(
                tabulate(
                    result,
                    headers=["Project", "Project ID", "ID", "Name", "Flavor", "Status"],
                    tablefmt="psql",
                )
            )

        elif project:
            if project_domain:
                _project_domain = conn.identity.find_domain(project_domain)
                if not _project_domain:
                    logger.error(f"Project domain {project_domain} not found")
                    return
                query = {"domain_id": _project_domain.id}
                _project = conn.identity.find_project(project, **query)
            else:
                _project = conn.identity.find_project(project)
            if not _project:
                logger.error(f"Project {project} not found")
                return
            query = {"project_id": _project.id}

            for server in conn.compute.servers(all_projects=True, **query):
                result.append(
                    [
                        server.id,
                        server.name,
                        server.flavor["original_name"],
                        server.status,
                    ]
                )

            print(
                tabulate(
                    result,
                    headers=["ID", "Name", "Flavor", "Status"],
                    tablefmt="psql",
                )
            )

        else:
            for server in conn.compute.servers(all_projects=True, status="build"):
                duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                    server.created_at
                )
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Server {server.id} hangs in BUILD status for more than 2 hours"
                    )
                    result.append(
                        [
                            server.id,
                            server.name,
                            server.flavor["original_name"],
                            server.status,
                        ]
                    )

            for server in conn.compute.servers(all_projects=True, status="error"):
                duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                    server.created_at
                )
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Server {server.id} hangs in ERRORstatus for more than 2 hours"
                    )
                    result.append(
                        [
                            server.id,
                            server.name,
                            server.flavor["original_name"],
                            server.status,
                        ]
                    )

            print(
                tabulate(
                    result,
                    headers=["ID", "Name", "Flavor", "Status"],
                    tablefmt="psql",
                )
            )
