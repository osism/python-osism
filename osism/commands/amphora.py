# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from time import sleep

from cliff.command import Command
from dateutil import parser as dateutil_parser
from loguru import logger
import openstack

from osism.commands.octavia import wait_for_amphora_boot, wait_for_amphora_delete
from osism.tasks.openstack import cleanup_cloud_environment, setup_cloud_environment

# Default age threshold for rotation (30 days in seconds)
DEFAULT_ROTATION_AGE_SECONDS = 2592000


class AmphoraRestore(Command):
    """Restore amphorae in ERROR state by triggering failover."""

    def get_parser(self, prog_name):
        parser = super(AmphoraRestore, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        parser.add_argument(
            "--loadbalancer",
            type=str,
            help="Limit restore to amphorae of this loadbalancer ID",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        loadbalancer_id = parsed_args.loadbalancer

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            if loadbalancer_id:
                amphorae = conn.load_balancer.amphorae(
                    status="ERROR", loadbalancer_id=loadbalancer_id
                )
            else:
                amphorae = conn.load_balancer.amphorae(status="ERROR")

            for amphora in amphorae:
                logger.info(
                    f"Amphora {amphora.id} of loadbalancer {amphora.loadbalancer_id} is in state ERROR, trigger amphora failover"
                )
                conn.load_balancer.failover_amphora(amphora.id)
                sleep(10)  # wait for the octavia API

                wait_for_amphora_boot(conn, amphora.loadbalancer_id)
                wait_for_amphora_delete(conn, amphora.loadbalancer_id)
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class AmphoraRotate(Command):
    """Rotate amphorae older than 30 days by triggering loadbalancer failover."""

    def get_parser(self, prog_name):
        parser = super(AmphoraRotate, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        parser.add_argument(
            "--loadbalancer",
            type=str,
            help="Limit rotation to amphorae of this loadbalancer ID",
            default=None,
        )
        parser.add_argument(
            "--force",
            default=False,
            help="Force rotation of amphorae regardless of age",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        loadbalancer_id = parsed_args.loadbalancer
        force = parsed_args.force

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            done = []

            if loadbalancer_id:
                amphorae = conn.load_balancer.amphorae(
                    status="ALLOCATED", loadbalancer_id=loadbalancer_id
                )
            else:
                amphorae = conn.load_balancer.amphorae(status="ALLOCATED")

            for amphora in amphorae:
                rotate = False

                if amphora.loadbalancer_id in done:
                    continue

                duration = datetime.now(timezone.utc) - dateutil_parser.parse(
                    amphora.created_at
                )
                if duration.total_seconds() > DEFAULT_ROTATION_AGE_SECONDS:
                    logger.info(f"Amphora {amphora.id} is older than 30 days")
                    rotate = True
                elif force:
                    logger.info(f"Force rotation of Amphora {amphora.id}")
                    rotate = True
                else:
                    continue

                if rotate:
                    logger.info(
                        f"Amphora {amphora.id} of loadbalancer {amphora.loadbalancer_id} is rotated by a loadbalancer failover"
                    )
                    try:
                        conn.load_balancer.failover_load_balancer(
                            amphora.loadbalancer_id
                        )
                        sleep(10)  # wait for the octavia API

                        done.append(amphora.loadbalancer_id)

                        wait_for_amphora_boot(conn, amphora.loadbalancer_id)
                        wait_for_amphora_delete(conn, amphora.loadbalancer_id)
                    except openstack.exceptions.ConflictException:
                        logger.warning(
                            f"Conflict while rotating loadbalancer {amphora.loadbalancer_id}, skipping"
                        )
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
