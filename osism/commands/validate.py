# SPDX-License-Identifier: Apache-2.0

import argparse
import os

from cliff.command import Command
from loguru import logger
import pymysql
import yaml

from osism.data.enums import VALIDATE_PLAYBOOKS
from osism.tasks import ansible, ceph, kolla
from osism.tasks.conductor.utils import get_vault
from osism import utils


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "validator",
            nargs=1,
            type=str,
            help="Validator to run",
            choices=VALIDATE_PLAYBOOKS.keys(),
        )
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        ),
        parser.add_argument(
            "--environment",
            default=None,
            help="Environment",
            type=str,
        ),
        parser.add_argument(
            "--timeout",
            default=300,
            type=int,
            help="Timeout to end if there is no output",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the validator run has been completed",
            action="store_true",
        )
        return parser

    def _handle_task(self, t, wait, format, timeout, playbook):
        if wait:
            try:
                return utils.fetch_task_output(t.id, timeout=timeout)
            except TimeoutError:
                logger.error(
                    f"Timeout while waiting for further output of task {t.task_id} (sync inventory)"
                )
        else:
            if format == "log":
                logger.info(
                    f"Task {t.task_id} (validate {playbook}) is running in background. No more output. Check ARA for logs."
                )
            elif format == "script":
                print(f"{t.task_id}")

            return 0

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        arguments = parsed_args.arguments
        environment = parsed_args.environment
        validator = parsed_args.validator[0]
        format = parsed_args.format
        timeout = parsed_args.timeout
        wait = not parsed_args.no_wait

        runtime = VALIDATE_PLAYBOOKS[validator]["runtime"]

        if "playbook" in VALIDATE_PLAYBOOKS[validator]:
            playbook = VALIDATE_PLAYBOOKS[validator]["playbook"]
        else:
            playbook = f"validate-{validator}"

        if runtime == "ceph-ansible":
            if not environment:
                environment = "ceph"
            t = ceph.run.delay(environment, playbook, arguments)
        elif runtime == "kolla-ansible":
            arguments.append("-e kolla_action=config_validate")
            if not environment:
                environment = "kolla"
            t = kolla.run.delay(environment, playbook, arguments)
        else:
            environment = VALIDATE_PLAYBOOKS[validator]["environment"]
            t = ansible.run.delay(environment, playbook, arguments)

        rc = self._handle_task(t, wait, format, timeout, playbook)

        return rc


class Database(Command):
    """Validate MariaDB Galera Cluster functionality"""

    def get_parser(self, prog_name):
        parser = super(Database, self).get_parser(prog_name)
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        )
        return parser

    def _load_kolla_configuration(self):
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

    def _load_database_password(self):
        """Load and decrypt the database password from secrets.yml"""
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

            password = secrets.get("database_password")
            if password is None:
                logger.error("database_password not found in secrets file")
                return None

            return str(password).strip()

        except Exception as exc:
            logger.error(f"Failed to load database password: {exc}")
            return None

    def _check_galera_status(self, connection):
        """Check the Galera cluster status and return validation results"""
        results = {
            "cluster_status": None,
            "connected": None,
            "ready": None,
            "cluster_size": None,
            "local_state": None,
            "cluster_state_uuid": None,
        }
        errors = []

        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW STATUS LIKE 'wsrep_%'")
                status_rows = cursor.fetchall()

            status = {row[0]: row[1] for row in status_rows}

            # Check wsrep_cluster_status (should be "Primary")
            results["cluster_status"] = status.get("wsrep_cluster_status", "UNKNOWN")
            if results["cluster_status"] != "Primary":
                errors.append(
                    f"Cluster status is '{results['cluster_status']}', expected 'Primary'"
                )

            # Check wsrep_connected (should be "ON")
            results["connected"] = status.get("wsrep_connected", "UNKNOWN")
            if results["connected"] != "ON":
                errors.append(
                    f"Cluster connected is '{results['connected']}', expected 'ON'"
                )

            # Check wsrep_ready (should be "ON")
            results["ready"] = status.get("wsrep_ready", "UNKNOWN")
            if results["ready"] != "ON":
                errors.append(f"Cluster ready is '{results['ready']}', expected 'ON'")

            # Check wsrep_cluster_size (should be > 0)
            results["cluster_size"] = status.get("wsrep_cluster_size", "0")
            try:
                size = int(results["cluster_size"])
                if size < 1:
                    errors.append(f"Cluster size is {size}, expected at least 1")
            except ValueError:
                errors.append(f"Invalid cluster size: {results['cluster_size']}")

            # Check wsrep_local_state_comment (should be "Synced")
            results["local_state"] = status.get("wsrep_local_state_comment", "UNKNOWN")
            if results["local_state"] != "Synced":
                errors.append(
                    f"Local state is '{results['local_state']}', expected 'Synced'"
                )

            # Get cluster state UUID for informational purposes
            results["cluster_state_uuid"] = status.get(
                "wsrep_cluster_state_uuid", "UNKNOWN"
            )

        except Exception as exc:
            errors.append(f"Failed to query Galera status: {exc}")

        return results, errors

    def take_action(self, parsed_args):
        format = parsed_args.format

        # Load configuration
        config = self._load_kolla_configuration()
        if config is None:
            if format == "log":
                logger.error("Failed to load kolla configuration")
            return 1

        # Get VIP address
        vip_address = config.get("kolla_internal_vip_address")
        if not vip_address:
            if format == "log":
                logger.error("kolla_internal_vip_address not found in configuration")
            return 1

        # Load database password
        password = self._load_database_password()
        if password is None:
            if format == "log":
                logger.error("Failed to load database password")
            return 1

        # Determine database user based on ProxySQL configuration
        enable_proxysql = config.get("enable_proxysql", False)
        db_user = "root_shard_0" if enable_proxysql else "root"

        # Connect to MariaDB
        if format == "log":
            logger.info(f"Connecting to MariaDB at {vip_address} as {db_user}...")

        try:
            connection = pymysql.connect(
                host=vip_address,
                port=3306,
                user=db_user,
                password=password,
                connect_timeout=10,
            )
        except pymysql.Error as exc:
            if format == "log":
                logger.error(f"Failed to connect to MariaDB: {exc}")
            elif format == "script":
                print(f"FAILED: Connection error - {exc}")
            return 1

        try:
            # Check Galera status
            results, errors = self._check_galera_status(connection)

            if format == "log":
                logger.info(f"Cluster Status: {results['cluster_status']}")
                logger.info(f"Connected: {results['connected']}")
                logger.info(f"Ready: {results['ready']}")
                logger.info(f"Cluster Size: {results['cluster_size']}")
                logger.info(f"Local State: {results['local_state']}")
                logger.info(f"Cluster State UUID: {results['cluster_state_uuid']}")

                if errors:
                    for error in errors:
                        logger.error(error)
                    logger.error("MariaDB Galera Cluster validation FAILED")
                    return 1
                else:
                    logger.info("MariaDB Galera Cluster validation PASSED")
                    return 0

            elif format == "script":
                if errors:
                    print("FAILED")
                    for error in errors:
                        print(f"  - {error}")
                    return 1
                else:
                    print("PASSED")
                    return 0

        finally:
            connection.close()
