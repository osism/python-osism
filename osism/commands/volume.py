# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from time import sleep

from cliff.command import Command
import dateutil
from loguru import logger
import openstack
from prompt_toolkit import prompt
import pytz
from tabulate import tabulate

from osism.tasks.openstack import cleanup_cloud_environment, setup_cloud_environment

# Time threshold for stuck volumes (2 hours in seconds)
STUCK_VOLUME_THRESHOLD_SECONDS = 7200

# Wait time for API operations
SLEEP_WAIT_FOR_API = 2


class VolumeList(Command):
    def get_parser(self, prog_name):
        parser = super(VolumeList, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
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
        cloud = parsed_args.cloud
        domain = parsed_args.domain
        project = parsed_args.project
        project_domain = parsed_args.project_domain

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            result = []
            if domain:
                _domain = conn.identity.find_domain(domain)
                if not _domain:
                    logger.error(f"Domain {domain} not found")
                    return
                projects = list(conn.identity.projects(domain_id=_domain.id))

                for project in projects:
                    query = {"project_id": project.id}
                    for volume in conn.block_storage.volumes(
                        all_projects=True, **query
                    ):
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
                        headers=[
                            "Project",
                            "Project ID",
                            "ID",
                            "Name",
                            "Type",
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
                    created_at = pytz.utc.localize(
                        dateutil.parser.parse(volume.created_at)
                    )
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
                    created_at = pytz.utc.localize(
                        dateutil.parser.parse(volume.created_at)
                    )
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
                    created_at = pytz.utc.localize(
                        dateutil.parser.parse(volume.created_at)
                    )
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
                    created_at = pytz.utc.localize(
                        dateutil.parser.parse(volume.created_at)
                    )
                    duration = datetime.now(timezone.utc) - created_at
                    if duration.total_seconds() > 7200:
                        logger.info(
                            f"Volume {volume.id} hangs in DELETING status for more than 2 hours"
                        )
                        result.append(
                            [volume.id, volume.name, volume.volume_type, volume.status]
                        )

                for volume in conn.block_storage.volumes(
                    all_projects=True, status="error"
                ):
                    created_at = pytz.utc.localize(
                        dateutil.parser.parse(volume.created_at)
                    )
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
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class VolumeRepair(Command):
    """Repair volumes stuck in problematic states.

    Handles volumes in the following states:
    - DETACHING (> 2 hours): Aborts the detach operation
    - CREATING (> 2 hours): Deletes the volume (with confirmation)
    - ERROR_DELETING: Retries deletion (with confirmation)
    - DELETING (> 2 hours): Resets status and retries deletion (with confirmation)
    """

    def get_parser(self, prog_name):
        parser = super(VolumeRepair, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        parser.add_argument(
            "--yes",
            default=False,
            help="Automatically confirm all prompts",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        auto_confirm = parsed_args.yes

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            # Handle volumes stuck in DETACHING state
            for volume in conn.block_storage.volumes(
                all_projects=True, status="detaching"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > STUCK_VOLUME_THRESHOLD_SECONDS:
                    logger.info(
                        f"Volume {volume.id} hangs in DETACHING status for more than 2 hours"
                    )
                    logger.info(
                        f"Aborting detach of attachment(s) of volume {volume.id}"
                    )
                    conn.block_storage.abort_volume_detaching(volume.id)

            # Handle volumes stuck in CREATING state
            for volume in conn.block_storage.volumes(
                all_projects=True, status="creating"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > STUCK_VOLUME_THRESHOLD_SECONDS:
                    logger.info(
                        f"Volume {volume.id} hangs in CREATING status for more than 2 hours"
                    )
                    if auto_confirm:
                        result = "yes"
                    else:
                        result = prompt(f"Delete volume {volume.id} [yes/no]: ")
                    if result == "yes":
                        logger.info(f"Deleting volume {volume.id}")
                        conn.block_storage.delete_volume(volume.id, force=True)

            # Handle volumes in ERROR_DELETING state
            for volume in conn.block_storage.volumes(
                all_projects=True, status="error_deleting"
            ):
                logger.info(f"Volume {volume.id} is in ERROR_DELETING status")
                if auto_confirm:
                    result = "yes"
                else:
                    result = prompt(f"Retry to delete volume {volume.id} [yes/no]: ")
                if result == "yes":
                    logger.info(f"Deleting volume {volume.id}")
                    conn.block_storage.delete_volume(volume.id, force=True)

            # Handle volumes stuck in DELETING state
            for volume in conn.block_storage.volumes(
                all_projects=True, status="deleting"
            ):
                created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
                duration = datetime.now(timezone.utc) - created_at
                if duration.total_seconds() > STUCK_VOLUME_THRESHOLD_SECONDS:
                    logger.info(
                        f"Volume {volume.id} hangs in DELETING status for more than 2 hours"
                    )
                    if auto_confirm:
                        result = "yes"
                    else:
                        result = prompt(
                            f"Retry deletion of volume {volume.id} [yes/no]: "
                        )
                    if result == "yes":
                        logger.info(f"Resetting and deleting volume {volume.id}")
                        conn.block_storage.reset_volume_status(
                            volume.id,
                            status="available",
                            attach_status=None,
                            migration_status=None,
                        )
                        sleep(SLEEP_WAIT_FOR_API)
                        conn.block_storage.delete_volume(volume.id, force=True)
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
