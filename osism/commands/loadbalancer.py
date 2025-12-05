# SPDX-License-Identifier: Apache-2.0

import os
from time import sleep

from cliff.command import Command
from loguru import logger
import pymysql
from prompt_toolkit import prompt
from tabulate import tabulate
import yaml

import openstack

from osism.commands.octavia import wait_for_amphora_boot
from osism.tasks.openstack import cleanup_cloud_environment, setup_cloud_environment
from osism.tasks.conductor.utils import get_vault


def _load_kolla_configuration():
    """Load kolla configuration from configuration.yml"""
    config_path = "/opt/configuration/environments/kolla/configuration.yml"

    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found: {config_path}")
        return None

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        return config
    except Exception as exc:
        logger.error(f"Failed to load configuration: {exc}")
        return None


def _load_octavia_database_password():
    """Load and decrypt the octavia database password from secrets.yml"""
    secrets_path = "/opt/configuration/environments/kolla/secrets.yml"

    if not os.path.exists(secrets_path):
        logger.error(f"Secrets file not found: {secrets_path}")
        return None

    try:
        vault = get_vault()

        with open(secrets_path, "rb") as f:
            file_data = f.read()

        if vault.is_encrypted(file_data):
            decrypted_data = vault.decrypt(file_data).decode()
            logger.debug(f"Successfully decrypted secrets file: {secrets_path}")
        else:
            decrypted_data = file_data.decode()
            logger.debug(
                f"Secrets file is not encrypted (development mode): {secrets_path}"
            )

        secrets = yaml.safe_load(decrypted_data)

        if not secrets or not isinstance(secrets, dict):
            logger.error("Empty or invalid secrets file")
            return None

        # Try octavia-specific password first, fallback to general database_password
        password = secrets.get("octavia_database_password")
        if password is None:
            password = secrets.get("database_password")
        if password is None:
            logger.error(
                "octavia_database_password or database_password not found in secrets file"
            )
            return None

        return str(password).strip()

    except Exception as exc:
        logger.error(f"Failed to load octavia database password: {exc}")
        return None


def _get_octavia_database_connection():
    """Establish connection to Octavia database"""
    config = _load_kolla_configuration()
    if config is None:
        return None

    vip_address = config.get("kolla_internal_vip_address")
    if not vip_address:
        logger.error("kolla_internal_vip_address not found in configuration")
        return None

    password = _load_octavia_database_password()
    if password is None:
        return None

    # Determine database user based on ProxySQL configuration
    enable_proxysql = config.get("enable_proxysql", False)
    db_user = "octavia_shard_0" if enable_proxysql else "octavia"

    try:
        connection = pymysql.connect(
            host=vip_address,
            port=3306,
            user=db_user,
            password=password,
            database="octavia",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        logger.debug(f"Connected to Octavia database at {vip_address}")
        return connection
    except pymysql.Error as exc:
        logger.error(f"Failed to connect to Octavia database: {exc}")
        return None


def _reset_provisioning_status(database, loadbalancer_id, status="ACTIVE"):
    """Reset the provisioning status of a loadbalancer in the database"""
    with database.cursor() as cursor:
        query = f"UPDATE load_balancer SET provisioning_status = '{status}' WHERE id = '{loadbalancer_id}';"
        logger.debug(query)
        cursor.execute(query)
        database.commit()


def _reset_operating_status(database, loadbalancer_id, status="ONLINE"):
    """Reset the operating status of a loadbalancer in the database"""
    with database.cursor() as cursor:
        query = f"UPDATE load_balancer SET operating_status = '{status}' WHERE id = '{loadbalancer_id}';"
        logger.debug(query)
        cursor.execute(query)
        database.commit()


class LoadbalancerList(Command):
    """List loadbalancers with problematic status"""

    def get_parser(self, prog_name):
        parser = super(LoadbalancerList, self).get_parser(prog_name)
        parser.add_argument(
            "--status-type",
            type=str,
            help="Status type to check",
            default="provisioning_status",
            choices=["provisioning_status", "operating_status"],
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        return parser

    def take_action(self, parsed_args):
        status_type = parsed_args.status_type
        cloud = parsed_args.cloud

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            result = []
            if status_type == "provisioning_status":
                # List loadbalancers with problematic provisioning status
                for status in ["PENDING_CREATE", "PENDING_UPDATE", "ERROR"]:
                    for lb in conn.load_balancer.load_balancers(
                        provisioning_status=status
                    ):
                        result.append(
                            [
                                lb.id,
                                lb.name,
                                lb.provisioning_status,
                                lb.operating_status,
                                lb.project_id,
                            ]
                        )
            else:
                # List loadbalancers with ERROR operating status
                for lb in conn.load_balancer.load_balancers(operating_status="ERROR"):
                    result.append(
                        [
                            lb.id,
                            lb.name,
                            lb.provisioning_status,
                            lb.operating_status,
                            lb.project_id,
                        ]
                    )

            if result:
                print(
                    tabulate(
                        result,
                        headers=[
                            "ID",
                            "Name",
                            "Provisioning Status",
                            "Operating Status",
                            "Project ID",
                        ],
                        tablefmt="psql",
                    )
                )
            else:
                logger.info("No loadbalancers with problematic status found")
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class LoadbalancerReset(Command):
    """Reset a loadbalancer with problematic status"""

    def get_parser(self, prog_name):
        parser = super(LoadbalancerReset, self).get_parser(prog_name)
        parser.add_argument(
            "loadbalancer",
            type=str,
            help="Loadbalancer ID to reset",
        )
        parser.add_argument(
            "--status-type",
            type=str,
            help="Status type to reset",
            default="provisioning_status",
            choices=["provisioning_status", "operating_status"],
        )
        parser.add_argument(
            "--yes",
            default=False,
            help="Skip confirmation prompt",
            action="store_true",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        parser.add_argument(
            "--no-failover",
            default=False,
            help="Skip triggering failover after reset",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        loadbalancer_id = parsed_args.loadbalancer
        status_type = parsed_args.status_type
        yes = parsed_args.yes
        no_failover = parsed_args.no_failover
        cloud = parsed_args.cloud

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            # Get loadbalancer details
            try:
                lb = conn.load_balancer.get_load_balancer(loadbalancer_id)
            except Exception as exc:
                logger.error(f"Failed to get loadbalancer {loadbalancer_id}: {exc}")
                return 1

            logger.info(
                f"Loadbalancer {lb.name} ({lb.id}): "
                f"provisioning_status={lb.provisioning_status}, "
                f"operating_status={lb.operating_status}"
            )

            # Validate status
            if status_type == "provisioning_status":
                if lb.provisioning_status not in ["PENDING_UPDATE", "ERROR"]:
                    logger.error(
                        f"Loadbalancer {loadbalancer_id} has provisioning_status "
                        f"'{lb.provisioning_status}', expected PENDING_UPDATE or ERROR. "
                        f"Use 'manage loadbalancer delete' for PENDING_CREATE status."
                    )
                    return 1
            else:
                if lb.operating_status != "ERROR":
                    logger.error(
                        f"Loadbalancer {loadbalancer_id} has operating_status "
                        f"'{lb.operating_status}', expected ERROR"
                    )
                    return 1
                if lb.provisioning_status != "ACTIVE":
                    logger.error(
                        f"Loadbalancer {loadbalancer_id} has provisioning_status "
                        f"'{lb.provisioning_status}', expected ACTIVE for operating_status reset"
                    )
                    return 1

            # Confirm action
            if not yes:
                answer = prompt(f"Reset loadbalancer {lb.name} ({lb.id}) [yes/no]: ")
                if answer.lower() not in ["yes", "y"]:
                    logger.info("Aborted")
                    return 0

            # Connect to database
            database = _get_octavia_database_connection()
            if database is None:
                return 1

            try:
                # Reset status in database
                logger.info(f"Resetting {status_type} for {lb.name}")
                if status_type == "provisioning_status":
                    _reset_provisioning_status(database, lb.id)
                else:
                    _reset_operating_status(database, lb.id)

                # Trigger failover
                if not no_failover:
                    logger.info(f"Triggering failover for {lb.name}")
                    conn.load_balancer.failover_load_balancer(lb.id)
                    sleep(10)  # wait for the octavia API
                    wait_for_amphora_boot(conn, lb.id)

                logger.info(f"Successfully reset loadbalancer {lb.name}")

            finally:
                database.close()
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)


class LoadbalancerDelete(Command):
    """Delete a loadbalancer stuck in PENDING_CREATE status"""

    def get_parser(self, prog_name):
        parser = super(LoadbalancerDelete, self).get_parser(prog_name)
        parser.add_argument(
            "loadbalancer",
            type=str,
            help="Loadbalancer ID to delete",
        )
        parser.add_argument(
            "--yes",
            default=False,
            help="Skip confirmation prompt",
            action="store_true",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml",
            default="admin",
        )
        return parser

    def take_action(self, parsed_args):
        loadbalancer_id = parsed_args.loadbalancer
        yes = parsed_args.yes
        cloud = parsed_args.cloud

        temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            logger.error(f"Failed to setup cloud environment for '{cloud}'")
            return 1

        try:
            conn = openstack.connect(cloud=cloud)

            # Get loadbalancer details
            try:
                lb = conn.load_balancer.get_load_balancer(loadbalancer_id)
            except Exception as exc:
                logger.error(f"Failed to get loadbalancer {loadbalancer_id}: {exc}")
                return 1

            logger.info(
                f"Loadbalancer {lb.name} ({lb.id}): "
                f"provisioning_status={lb.provisioning_status}, "
                f"operating_status={lb.operating_status}"
            )

            # Validate status
            if lb.provisioning_status != "PENDING_CREATE":
                logger.error(
                    f"Loadbalancer {loadbalancer_id} has provisioning_status "
                    f"'{lb.provisioning_status}', expected PENDING_CREATE. "
                    f"Use 'manage loadbalancer reset' for other status values."
                )
                return 1

            # Confirm action
            if not yes:
                answer = prompt(f"Delete loadbalancer {lb.name} ({lb.id}) [yes/no]: ")
                if answer.lower() not in ["yes", "y"]:
                    logger.info("Aborted")
                    return 0

            # Connect to database
            database = _get_octavia_database_connection()
            if database is None:
                return 1

            try:
                # Set status to ERROR first so delete works
                logger.info(f"Setting provisioning_status to ERROR for {lb.name}")
                _reset_provisioning_status(database, lb.id, status="ERROR")

                # Delete loadbalancer
                logger.info(f"Deleting loadbalancer {lb.name}")
                conn.load_balancer.delete_load_balancer(lb.id)

                logger.info(f"Successfully deleted loadbalancer {lb.name}")

            finally:
                database.close()
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
