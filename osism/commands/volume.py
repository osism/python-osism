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
        return parser

    def take_action(self, parsed_args):
        conn = get_cloud_connection()

        result = []
        for volume in conn.block_storage.volumes(all_projects=True, status="detaching"):
            created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
            duration = datetime.now(timezone.utc) - created_at
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in DETACHING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="creating"):
            created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
            duration = datetime.now(timezone.utc) - created_at
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in CREATING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(
            all_projects=True, status="error_deleting"
        ):
            created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
            duration = datetime.now(timezone.utc) - created_at
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in ERROR_DELETING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="deleting"):
            created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
            duration = datetime.now(timezone.utc) - created_at
            if duration.total_seconds() > 7200:
                logger.info(
                    f"Volume {volume.id} hangs in DELETING status for more than 2 hours"
                )
                result.append([volume.id, volume.name, volume.status])

        for volume in conn.block_storage.volumes(all_projects=True, status="error"):
            created_at = pytz.utc.localize(dateutil.parser.parse(volume.created_at))
            duration = datetime.now(timezone.utc) - created_at
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
