# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone

from cliff.command import Command
import dateutil
from loguru import logger
import pytz
from tabulate import tabulate

from osism.commands import get_cloud_connection


class VolumeList(Command):
    def get_parser(self, prog_name):
        parser = super(VolumeList, self).get_parser(prog_name)
        parser.add_argument(
            "--domain",
            help="List all volumes of a specific domain",
            type=str,
            default=None,
        )
        parser.add_argument(
            "--project",
            help="List all volumes of a specific project",
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
                for volume in conn.block_storage.volumes(all_projects=True, **query):
                    result.append(
                        [
                            project.name,
                            project.id,
                            volume.id,
                            volume.name,
                            volume.volume_type,
                            volume.status,
                        ]
                    )

            print(
                tabulate(
                    result,
                    headers=["Project", "Project ID", "ID", "Name", "Type", "Status"],
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

            for volume in conn.block_storage.volumes(all_projects=True, **query):
                result.append(
                    [
                        volume.id,
                        volume.name,
                        volume.volume_type,
                        volume.status,
                    ]
                )

            print(
                tabulate(
                    result,
                    headers=["ID", "Name", "Type", "Status"],
                    tablefmt="psql",
                )
            )

        else:
            for volume in conn.block_storage.volumes(
                all_projects=True, status="detaching"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Volume {volume.id} hangs in DETACHING status for more than 2 hours"
                    )
                    result.append(
                        [volume.id, volume.name, volume.volume_type, volume.status]
                    )

            for volume in conn.block_storage.volumes(
                all_projects=True, status="creating"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Volume {volume.id} hangs in CREATING status for more than 2 hours"
                    )
                    result.append(
                        [volume.id, volume.name, volume.volume_type, volume.status]
                    )

            for volume in conn.block_storage.volumes(
                all_projects=True, status="error_deleting"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Volume {volume.id} hangs in ERROR_DELETING status for more than 2 hours"
                    )
                    result.append(
                        [volume.id, volume.name, volume.volume_type, volume.status]
                    )

            for volume in conn.block_storage.volumes(
                all_projects=True, status="deleting"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Volume {volume.id} hangs in DELETING status for more than 2 hours"
                    )
                    result.append(
                        [volume.id, volume.name, volume.volume_type, volume.status]
                    )

            for volume in conn.block_storage.volumes(all_projects=True, status="error"):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > 7200:
                    logger.info(
                        f"Volume {volume.id} hangs in ERROR status for more than 2 hours"
                    )
                    result.append(
                        [volume.id, volume.name, volume.volume_type, volume.status]
                    )

            print(
                tabulate(
                    result,
                    headers=["ID", "Name", "Type", "Status"],
                    tablefmt="psql",
                )
            )
