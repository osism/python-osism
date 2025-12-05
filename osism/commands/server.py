# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
import time

from cliff.command import Command
import dateutil
from loguru import logger
import openstack
from prompt_toolkit import prompt
from tabulate import tabulate

from osism.tasks.openstack import cleanup_cloud_environment, setup_cloud_environment


class ServerMigrate(Command):
    def get_parser(self, prog_name):
        parser = super(ServerMigrate, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
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
        cloud = parsed_args.cloud
        yes = parsed_args.yes
        instance = parsed_args.instance[0]
        target = parsed_args.target
        force = parsed_args.force
        no_wait = parsed_args.no_wait

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

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
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class ServerList(Command):
    def get_parser(self, prog_name):
        parser = super(ServerList, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
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
        parser.add_argument(
            "--user",
            default=None,
            type=str,
            help="Only list servers for the given user (name or ID)",
        )
        parser.add_argument(
            "--user-domain",
            default=None,
            type=str,
            help="Domain the user belongs to (name or ID)",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        domain = parsed_args.domain
        project = parsed_args.project
        project_domain = parsed_args.project_domain
        user = parsed_args.user
        user_domain = parsed_args.user_domain

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            result = []

            # Handle user lookup if --user is specified
            user_id = None
            if user:
                user_query = {}

                if user_domain:
                    u_d = conn.identity.find_domain(user_domain, ignore_missing=True)
                    if u_d and "id" in u_d:
                        user_query = dict(domain_id=u_d.id)
                    else:
                        logger.error(f"No domain found for {user_domain}")
                        return

                u = conn.identity.find_user(user, ignore_missing=True, **user_query)
                if u and "id" in u:
                    user_id = u.id
                else:
                    logger.error(f"No user found for {user}")
                    return

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
                                server.user_id if hasattr(server, "user_id") else None,
                                server.id,
                                server.name,
                                server.flavor["original_name"],
                                server.status,
                            ]
                        )

                print(
                    tabulate(
                        result,
                        headers=[
                            "Project",
                            "Project ID",
                            "User ID",
                            "ID",
                            "Name",
                            "Flavor",
                            "Status",
                        ],
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

                # Get domain name from project
                domain_name = None
                if hasattr(_project, "domain_id") and _project.domain_id:
                    try:
                        _domain = conn.identity.get_domain(_project.domain_id)
                        domain_name = _domain.name if _domain else _project.domain_id
                    except Exception:
                        domain_name = _project.domain_id

                for server in conn.compute.servers(all_projects=True, **query):
                    result.append(
                        [
                            domain_name,
                            server.user_id if hasattr(server, "user_id") else None,
                            server.id,
                            server.name,
                            server.flavor["original_name"],
                            server.status,
                        ]
                    )

                print(
                    tabulate(
                        result,
                        headers=[
                            "Domain",
                            "User ID",
                            "ID",
                            "Name",
                            "Flavor",
                            "Status",
                        ],
                        tablefmt="psql",
                    )
                )

            elif user_id:
                query = {"user_id": user_id}

                for server in conn.compute.servers(all_projects=True, **query):
                    # Get domain name from project
                    domain_name = None
                    if hasattr(server, "project_id") and server.project_id:
                        try:
                            _project = conn.identity.get_project(server.project_id)
                            if (
                                _project
                                and hasattr(_project, "domain_id")
                                and _project.domain_id
                            ):
                                _domain = conn.identity.get_domain(_project.domain_id)
                                domain_name = (
                                    _domain.name if _domain else _project.domain_id
                                )
                        except Exception:
                            domain_name = None

                    result.append(
                        [
                            domain_name,
                            (
                                server.project_id
                                if hasattr(server, "project_id")
                                else None
                            ),
                            server.id,
                            server.name,
                            server.flavor["original_name"],
                            server.status,
                        ]
                    )

                print(
                    tabulate(
                        result,
                        headers=[
                            "Domain",
                            "Project ID",
                            "ID",
                            "Name",
                            "Flavor",
                            "Status",
                        ],
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
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class ServerClean(Command):
    def get_parser(self, prog_name):
        parser = super(ServerClean, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        parser.add_argument(
            "--yes",
            default=False,
            help="Always say yes",
            action="store_true",
        )
        parser.add_argument(
            "--build-timeout",
            default=7200,
            type=int,
            help="Timeout in seconds for servers stuck in BUILD status (default: 7200)",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        yes = parsed_args.yes
        build_timeout = parsed_args.build_timeout

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            # Handle servers stuck in BUILD status
            for server in conn.compute.servers(all_projects=True, status="build"):
                duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                    server.created_at
                )
                if duration.total_seconds() > build_timeout:
                    logger.info(
                        f"Server {server.id} ({server.name}) stuck in BUILD status "
                        f"for more than {build_timeout // 3600} hours"
                    )

                    if yes:
                        answer = "yes"
                    else:
                        answer = prompt(f"Delete server {server.id} [yes/no]: ")

                    if answer in ["yes", "y"]:
                        logger.info(f"Deleting server {server.id}")
                        conn.compute.delete_server(server.id, force=True)

            # Handle servers in ERROR status
            for server in conn.compute.servers(all_projects=True, status="error"):
                logger.info(f"Server {server.id} ({server.name}) is in ERROR status")

                if yes:
                    answer = "yes"
                else:
                    answer = prompt(f"Delete server {server.id} [yes/no]: ")

                if answer in ["yes", "y"]:
                    logger.info(f"Deleting server {server.id}")
                    conn.compute.delete_server(server.id, force=True)
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
