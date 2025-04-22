# SPDX-License-Identifier: Apache-2.0

import time
import datetime

from cliff.command import Command
from jc import parse
from loguru import logger
import openstack
from tabulate import tabulate
from prompt_toolkit import prompt

from osism.commands import get_cloud_connection, get_cloud_project


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

        if service["forced_down"]:
            logger.info(
                f"Remove force down from nova-compute binary @ {host} ({service.id})"
            )

            try:
                conn.compute.update_service_forced_down(
                    service=service.id, host=host, binary="nova-compute", forced=False
                )
            except openstack.exceptions.BadRequestException:
                logger.error(
                    f"Unable to force up host {host} as `done` evacuation migration "
                    "records remain associated with the host. Ensure the compute service "
                    "has been restarted, allowing these records to move to `completed` "
                    "before retrying this request."
                )
                return

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
            "--project",
            default=None,
            type=str,
            help="Filter by project ID",
        )
        parser.add_argument(
            "--domain",
            default=None,
            type=str,
            help="Filter by domain ID",
        )
        parser.add_argument(
            "--details",
            default=False,
            help="Show details",
            action="store_true",
        )
        parser.add_argument(
            "host",
            nargs="?",
            type=str,
            help="Host on that all running instances are to be listed",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host
        conn = get_cloud_connection()
        domain = parsed_args.domain
        project = parsed_args.project
        details = parsed_args.details

        result = []
        if host:
            for server in conn.compute.servers(all_projects=True, node=host):
                if project and server.project_id == project:
                    result.append([server.id, server.name, server.status])
                elif domain:
                    server_project = get_cloud_project(server.project_id)
                    if server_project.domain_id == domain:
                        result.append([server.id, server.name, server.status])
                else:
                    result.append([server.id, server.name, server.status])

            print(
                tabulate(
                    result,
                    headers=["ID", "Name", "Status"],
                    tablefmt="psql",
                )
            )

        else:
            hypervisors = conn.compute.hypervisors(details=True)
            if details:
                for hypervisor in hypervisors:
                    if hypervisor.get("uptime"):
                        try:
                            uptime = parse("uptime", hypervisor.get("uptime"))
                        except:
                            uptime = None
                    else:
                        uptime = None

                    if not uptime:
                        uptime = {
                            "uptime": "-",
                            "load_1m": "-",
                            "load_5m": "-",
                            "load_15m": "-",
                        }

                    result.append(
                        [
                            hypervisor.get("id"),
                            hypervisor.name,
                            hypervisor.get("status"),
                            hypervisor.get("state"),
                            uptime["uptime"],
                            uptime["load_1m"],
                            uptime["load_5m"],
                            uptime["load_15m"],
                        ]
                    )

                print(
                    tabulate(
                        result,
                        headers=[
                            "ID",
                            "Host",
                            "Status",
                            "State",
                            "Uptime",
                            "Load 1",
                            "Load 5",
                            "Load 15",
                        ],
                        tablefmt="psql",
                    )
                )
            else:
                for hypervisor in hypervisors:
                    result.append(
                        [
                            hypervisor.get("id"),
                            hypervisor.name,
                            hypervisor.get("status"),
                            hypervisor.get("state"),
                        ]
                    )

                print(
                    tabulate(
                        result,
                        headers=["ID", "Host", "Status", "State"],
                        tablefmt="psql",
                    )
                )


class ComputeEvacuate(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeEvacuate, self).get_parser(prog_name)
        parser.add_argument(
            "--yes",
            default=False,
            help="Always say yes",
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
        yes = parsed_args.yes
        conn = get_cloud_connection()

        result = []
        for server in conn.compute.servers(all_projects=True, node=host):
            result.append([server.id, server.name, server.status])

        if yes:
            answer = "yes"
        else:
            answer = prompt(f"Evacuate all servers on host {host} [yes/no]: ")

        start = []
        if answer in ["yes", "y"]:
            for server in result:
                if server[2] not in ["ACTIVE", "SHUTOFF"]:
                    logger.info(
                        f"{server[0]} ({server[1]}) in status {server[2]} cannot be evacuated"
                    )
                    continue
                if server[2] in ["ACTIVE"]:
                    logger.info(f"Stopping server {server[0]}")
                    start.append(str(server[0]))
                    conn.compute.stop_server(server[0])
                    inner_wait = True
                    while inner_wait:
                        time.sleep(2)
                        s = conn.compute.get_server(server[0])
                        if s.status not in ["SHUTOFF"]:
                            logger.info(
                                f"Stopping of {server[0]} ({server[1]}) is still in progress"
                            )
                            inner_wait = True
                        else:
                            inner_wait = False

            services = conn.compute.services(**{"host": host, "binary": "nova-compute"})
            service = next(services)
            logger.info(f"Forcing down nova-compute binary @ {host} ({service.id})")
            conn.compute.update_service_forced_down(
                service=service.id, host=host, binary="nova-compute", forced=True
            )

            for server in result:
                if server[2] in ["ACTIVE", "SHUTOFF"]:
                    logger.info(f"Evacuating server {server[0]}")
                    conn.compute.evacuate_server(server[0], host=target)

            if result:
                logger.info("Waiting 30 seconds")
                time.sleep(30)

            for server in start:
                logger.info(f"Starting server {server}")
                conn.compute.start_server(server)
                inner_wait = True
                while inner_wait:
                    time.sleep(2)
                    s = conn.compute.get_server(server)
                    if s.status not in ["ACTIVE"]:
                        logger.info(
                            f"Starting of {s.id} ({s.name}) is still in progress"
                        )
                        inner_wait = True
                    else:
                        inner_wait = False

            logger.info(f"Disabling nova-compute binary @ {host} ({service.id})")
            conn.compute.disable_service(
                service=service.id,
                host=host,
                binary="nova-compute",
                disabled_reason="EVACUATE",
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
            help="Do not wait for completion of migration (Resize of cold migrated instances will not be confirmed!)",
            action="store_true",
        )
        parser.add_argument(
            "--no-cold-migration",
            default=False,
            help="Do not cold migrate instances",
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
            "--project",
            default=None,
            type=str,
            help="Filter by project ID",
        )
        parser.add_argument(
            "--domain",
            default=None,
            type=str,
            help="Filter by domain ID",
        )
        parser.add_argument(
            "--filter",
            default=None,
            type=str,
            help="Filter by string",
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
        no_cold_migration = parsed_args.no_cold_migration
        yes = parsed_args.yes
        domain = parsed_args.domain
        project = parsed_args.project
        xfilter = parsed_args.filter

        conn = get_cloud_connection()

        result = []
        for server in conn.compute.servers(all_projects=True, node=host):
            if project and server.project_id == project:
                result.append([server.id, server.name, server.status])
            elif domain:
                server_project = get_cloud_project(server.project_id)
                if server_project.domain_id == domain:
                    result.append([server.id, server.name, server.status])
            elif xfilter:
                if xfilter in server.name:
                    result.append([server.id, server.name, server.status])
            else:
                result.append([server.id, server.name, server.status])

        if not result:
            logger.info(f"No migratable instances found on node {host}")

        for server in result:
            if server[2] in ["ACTIVE", "PAUSED"]:
                migration_type = "live"
            elif server[2] in ["SHUTOFF"] and not no_cold_migration:
                migration_type = "cold"
            else:
                logger.info(
                    f"{server[0]} ({server[1]}) in status {server[2]} cannot be migrated"
                )
                continue

            if yes:
                answer = "yes"
            else:
                answer = prompt(
                    f"{migration_type.capitalize()} migrate server {server[0]} ({server[1]}) [yes/no]: "
                )

            if answer in ["yes", "y"]:
                logger.info(
                    f"{migration_type.capitalize()} migrating server {server[0]}"
                )
                if migration_type == "live":
                    conn.compute.live_migrate_server(
                        server[0], host=target, block_migration="auto", force=force
                    )
                elif migration_type == "cold":
                    conn.compute.migrate_server(server[0], host=target)

                if not no_wait:
                    while True:
                        time.sleep(2)
                        s = conn.compute.get_server(server[0])
                        if (
                            migration_type == "live"
                            and s.status in ["MIGRATING"]
                            or migration_type == "cold"
                            and s.status in ["RESIZE"]
                        ):
                            logger.info(
                                f"{migration_type.capitalize()} migration of {server[0]} ({server[1]}) is still in progress"
                            )
                        elif migration_type == "cold" and s.status in ["VERIFY_RESIZE"]:
                            try:
                                conn.compute.confirm_server_resize(s)
                                logger.info(
                                    f"{migration_type.capitalize()} migration of {server[0]} ({server[1]}) confirmed"
                                )
                            except Exception as exc:
                                logger.error(
                                    f"{migration_type.capitalize()} migration of {server[0]} ({server[1]}) could not be confirmed"
                                )
                                raise exc
                            # NOTE: There seems to be no simple way to check whether the resize
                            # has been confirmed. The state is still "VERIFY_RESIZE" afterwards.
                            # Therefore we drop out without waiting for the "SHUTOFF" state
                            break
                        else:
                            logger.info(
                                f"{migration_type.capitalize()} migration of {server[0]} ({server[1]}) completed with status {s.status}"
                            )
                            break


class ComputeMigrationList(Command):
    def get_parser(self, prog_name):
        parser = super(ComputeMigrationList, self).get_parser(prog_name)
        parser.add_argument(
            "--host",
            default=None,
            type=str,
            help="Only list migrations with the given host as source or destination",
        )
        parser.add_argument(
            "--server",
            default=None,
            type=str,
            help="Only list migrations for the given instance (name or ID)",
        )
        parser.add_argument(
            "--user",
            default=None,
            type=str,
            help="Only list migrations for the given user (name or ID)",
        )
        parser.add_argument(
            "--user-domain",
            default=None,
            type=str,
            help="Domain the user belongs to (name or ID)",
        )
        parser.add_argument(
            "--project",
            default=None,
            type=str,
            help="Only list migrations for the given project (name or ID)",
        )
        parser.add_argument(
            "--project-domain",
            default=None,
            type=str,
            help="Domain the project belongs to (name or ID)",
        )
        parser.add_argument(
            "--status",
            default=None,
            type=str,
            help="Only list migrations with the given status",
        )
        parser.add_argument(
            "--type",
            default=None,
            choices=["migration", "live-migration", "evacuation", "resize"],
            type=str,
            help="Only list migrations with the given type",
        )
        parser.add_argument(
            "--changes-since",
            default=None,
            type=datetime.datetime.fromisoformat,
            help="Only list migrations last chganged since the given date in ISO 8601 format (CCYY-MM-DDThh:mm:ss±hh:mm)",
        )
        parser.add_argument(
            "--changes-before",
            default=None,
            type=datetime.datetime.fromisoformat,
            help="Only list migrations last chganged before the given date in ISO 8601 format (CCYY-MM-DDThh:mm:ss±hh:mm)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host
        server = parsed_args.server
        user = parsed_args.user
        user_domain = parsed_args.user_domain
        project = parsed_args.project
        project_domain = parsed_args.project_domain
        status = parsed_args.status
        migration_type = parsed_args.type
        changes_since = parsed_args.changes_since
        changes_before = parsed_args.changes_before

        if changes_before and changes_since:
            if not changes_since <= changes_before:
                logger.error(
                    "changes-since needs to be less or equal to changes-before"
                )
                return

        conn = get_cloud_connection()

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

        project_id = None
        if project:
            project_query = {}

            if project_domain:
                p_d = conn.identity.find_domain(project_domain, ignore_missing=True)
                if p_d and "id" in p_d:
                    project_query = dict(domain_id=p_d.id)
                else:
                    logger.error(f"No domain found for {project_domain}")
                    return

            p = conn.identity.find_project(
                project, ignore_missing=True, **project_query
            )
            if p and "id" in p:
                project_id = p.id
            else:
                logger.error(f"No project found for {project}")
                return

        instance_uuid = None
        if server:
            try:
                s = conn.compute.find_server(
                    server, details=False, ignore_missing=False, all_projects=True
                )
                if s and "id" in s:
                    instance_uuid = s.id
                else:
                    raise openstack.exceptions.NotFoundException
            except openstack.exceptions.DuplicateResource:
                logger.error(f"Multiple servers where found for {server}")
                return
            except openstack.exceptions.NotFoundException:
                logger.error(f"No server found for {server}")
                return

        query = {}
        if host:
            query.update(dict(host=host))
        if instance_uuid:
            query.update(dict(instance_uuid=instance_uuid))
        if status:
            query.update(dict(status=status))
        if migration_type:
            query.update(dict(migration_type=migration_type))
        if user_id:
            query.update(dict(user_id=user_id))
        if project_id:
            query.update(dict(project_id=project_id))
        if changes_since:
            query.update(dict(changes_since=changes_since))
        if changes_before:
            query.update(dict(changes_before=changes_before))

        migrations = conn.compute.migrations(**query)
        result = [
            [
                m.source_compute,
                m.dest_compute,
                m.status,
                m.migration_type,
                m["instance_uuid"],
                m.user_id,
                m.created_at,
                m.updated_at,
            ]
            for m in migrations
        ]

        print(
            tabulate(
                result,
                headers=[
                    "Source",
                    "Destintion",
                    "Status",
                    "Type",
                    "Server UUID",
                    "User",
                    "Created At",
                    "Updated At",
                ],
                tablefmt="psql",
            )
        )


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
            if server[2] not in ["ACTIVE", "PAUSED"]:
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
