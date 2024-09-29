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


class VolumeList(Command):
    def get_parser(self, prog_name):
        parser = super(VolumeList, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        conn = get_cloud_connection()

        result = []
        for volume in conn.block_storage.volumes(all_projects=True, status="detaching"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                volume.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in DETACHING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="creating"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                volume.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in CREATING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(
            all_projects=True, status="error_deleting"
        ):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                volume.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in ERROR_DELETING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="deleting"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                volume.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in DELETING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="error"):
            duration = datetime.now(timezone.utc) - dateutil.parser.parse(
                volume.created_at
            )
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in ERROR status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        print(
            tabulate(
                result,
                headers=["ID", "Name", "Status"],
                tablefmt="psql",
            )
        )
