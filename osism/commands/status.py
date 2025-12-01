# SPDX-License-Identifier: Apache-2.0

import json
import os
import re
import subprocess

from celery import Celery
from cliff.command import Command
from loguru import logger
import pymysql
import requests
from tabulate import tabulate
import yaml

from osism.tasks import Config
from osism.tasks.conductor.utils import get_vault
from osism.utils import redis

# https://stackoverflow.com/questions/4048651/python-function-to-convert-seconds-into-minutes-hours-and-days/4048773

INTERVALS = (
    ("weeks", 604800),  # 60 * 60 * 24 * 7
    ("days", 86400),  # 60 * 60 * 24
    ("hours", 3600),  # 60 * 60
    ("minutes", 60),
    ("seconds", 1),
)


def display_time(seconds, granularity=2):
    result = []

    for name, count in INTERVALS:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip("s")
            result.append("{} {}".format(value, name))
    return ", ".join(result[:granularity])


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            nargs=1,
            type=str,
            choices=["workers"],
            help="Type of resource from which the status is to be displayed",
        )
        return parser

    def take_action(self, parsed_args):
        type_of_resource = parsed_args.type[0]

        app = Celery("status")
        app.config_from_object(Config)

        if type_of_resource == "workers":
            table = []
            i = app.control.inspect()
            s = i.stats()
            for node in sorted(s.keys()):
                ping = i.ping(destination=[node])
                if not ping:
                    health_status = "NOT REACHABLE"
                else:
                    health_status = "REACHABLE"
                table.append([node, display_time(s[node]["uptime"]), health_status])

            print(
                tabulate(table, headers=["Name", "Uptime", "Status"], tablefmt="psql")
            )
        else:
            logger.error(f"Unknown resource type '{type_of_resource}'")


class Database(Command):
    """Check MariaDB Galera Cluster status"""

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


class Messaging(Command):
    """Check RabbitMQ Cluster status"""

    def get_parser(self, prog_name):
        parser = super(Messaging, self).get_parser(prog_name)
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        )
        return parser

    def _get_rabbitmq_node_address(self):
        """Get the internal IPv4 address of the first RabbitMQ node from inventory"""
        try:
            # Use ansible-inventory with --limit to get hosts in rabbitmq group
            result = subprocess.check_output(
                "ansible-inventory -i /ansible/inventory/hosts.yml --list --limit rabbitmq",
                shell=True,
                stderr=subprocess.DEVNULL,
            )
            inventory = json.loads(result)

            # Get hosts from _meta.hostvars (contains all hosts matching the limit)
            if "_meta" not in inventory or "hostvars" not in inventory["_meta"]:
                logger.error("Invalid inventory format: _meta.hostvars not found")
                return None

            rabbitmq_hosts = list(inventory["_meta"]["hostvars"].keys())
            if not rabbitmq_hosts:
                logger.error("No hosts found in rabbitmq group")
                return None

            # Sort for consistent ordering and get first host
            rabbitmq_hosts.sort()
            first_host = rabbitmq_hosts[0]
            logger.debug(f"First RabbitMQ host: {first_host}")

            # Get ansible facts from Redis cache
            facts_data = redis.get(f"ansible_facts{first_host}")
            if not facts_data:
                logger.error(f"No ansible facts found in cache for {first_host}")
                return None

            facts = json.loads(facts_data)

            # Get hostvars for this host to find internal_interface
            result = subprocess.check_output(
                f"ansible-inventory -i /ansible/inventory/hosts.yml --host {first_host}",
                shell=True,
                stderr=subprocess.DEVNULL,
            )
            hostvars = json.loads(result)

            internal_interface_raw = hostvars.get("internal_interface")
            if not internal_interface_raw:
                logger.error(
                    f"internal_interface not found in hostvars for {first_host}"
                )
                return None

            # Resolve Jinja2 template if present (e.g., "{{ ansible_local.testbed_network_devices.management }}")
            internal_interface = internal_interface_raw
            template_match = re.match(r"\{\{\s*(.+?)\s*\}\}", internal_interface_raw)
            if template_match:
                path = template_match.group(1).strip()
                parts = path.split(".")
                value = facts
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                if value and isinstance(value, str):
                    internal_interface = value
                else:
                    logger.error(
                        f"Could not resolve template '{internal_interface_raw}' from facts for {first_host}"
                    )
                    return None

            logger.debug(f"Internal interface for {first_host}: {internal_interface}")

            # Look for the interface in ansible facts
            # Interface names with special chars are normalized (e.g., eth0.100 -> ansible_eth0_100)
            normalized_interface = internal_interface.replace(".", "_").replace(
                "-", "_"
            )
            interface_key = f"ansible_{normalized_interface}"

            interface_facts = facts.get(interface_key)
            if not interface_facts:
                logger.error(
                    f"Interface {internal_interface} ({interface_key}) not found in ansible facts for {first_host}"
                )
                return None

            # Get IPv4 address
            ipv4_info = interface_facts.get("ipv4")
            if not ipv4_info:
                logger.error(
                    f"No IPv4 address found for interface {internal_interface} on {first_host}"
                )
                return None

            ipv4_address = ipv4_info.get("address")
            if not ipv4_address:
                logger.error(
                    f"No IPv4 address found for interface {internal_interface} on {first_host}"
                )
                return None

            logger.debug(f"IPv4 address for {first_host}: {ipv4_address}")
            return ipv4_address, first_host

        except subprocess.CalledProcessError as exc:
            logger.error(f"Failed to query ansible inventory: {exc}")
            return None
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse inventory data: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Failed to get RabbitMQ node address: {exc}")
            return None

    def _load_rabbitmq_password(self):
        """Load and decrypt the RabbitMQ password from secrets.yml"""
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

            password = secrets.get("rabbitmq_password")
            if password is None:
                logger.error("rabbitmq_password not found in secrets file")
                return None

            return str(password).strip()

        except Exception as exc:
            logger.error(f"Failed to load RabbitMQ password: {exc}")
            return None

    def _check_rabbitmq_status(self, vip_address, username, password):
        """Check the RabbitMQ cluster status and return validation results"""
        results = {
            "cluster_name": None,
            "rabbitmq_version": None,
            "erlang_version": None,
            "nodes": [],
            "running_nodes": [],
            "partitioned_nodes": [],
            "alarms": [],
            "cluster_size": 0,
            # Statistics
            "total_connections": 0,
            "total_channels": 0,
            "total_queues": 0,
            "total_messages": 0,
            "messages_ready": 0,
            "messages_unacked": 0,
            # Message rates
            "publish_rate": 0.0,
            "deliver_rate": 0.0,
            # Node resources (from first node as reference)
            "disk_free": None,
            "disk_free_limit": None,
            "mem_used": None,
            "mem_limit": None,
            "fd_used": None,
            "fd_total": None,
            "sockets_used": None,
            "sockets_total": None,
        }
        errors = []

        base_url = f"http://{vip_address}:15672/api"
        auth = (username, password)

        try:
            # Get overview including version information and statistics
            response = requests.get(f"{base_url}/overview", auth=auth, timeout=10)
            response.raise_for_status()
            overview_data = response.json()
            results["rabbitmq_version"] = overview_data.get(
                "rabbitmq_version", "UNKNOWN"
            )
            results["erlang_version"] = overview_data.get("erlang_version", "UNKNOWN")
            results["cluster_name"] = overview_data.get("cluster_name", "UNKNOWN")

            # Object totals
            object_totals = overview_data.get("object_totals", {})
            results["total_connections"] = object_totals.get("connections", 0)
            results["total_channels"] = object_totals.get("channels", 0)
            results["total_queues"] = object_totals.get("queues", 0)

            # Queue totals
            queue_totals = overview_data.get("queue_totals", {})
            results["total_messages"] = queue_totals.get("messages", 0)
            results["messages_ready"] = queue_totals.get("messages_ready", 0)
            results["messages_unacked"] = queue_totals.get("messages_unacknowledged", 0)

            # Message rates
            message_stats = overview_data.get("message_stats", {})
            publish_details = message_stats.get("publish_details", {})
            deliver_details = message_stats.get("deliver_get_details", {})
            results["publish_rate"] = publish_details.get("rate", 0.0)
            results["deliver_rate"] = deliver_details.get("rate", 0.0)

        except requests.exceptions.RequestException as exc:
            errors.append(f"Failed to get overview: {exc}")

        try:
            # Get nodes information
            response = requests.get(f"{base_url}/nodes", auth=auth, timeout=10)
            response.raise_for_status()
            nodes_data = response.json()

            for idx, node in enumerate(nodes_data):
                node_name = node.get("name", "UNKNOWN")
                results["nodes"].append(node_name)

                if node.get("running", False):
                    results["running_nodes"].append(node_name)
                else:
                    errors.append(f"Node '{node_name}' is not running")

                # Check for memory or disk alarms on this node
                if node.get("mem_alarm", False):
                    errors.append(f"Memory alarm on node '{node_name}'")
                if node.get("disk_free_alarm", False):
                    errors.append(f"Disk free alarm on node '{node_name}'")

                # Check for cluster partitions (critical!)
                partitions = node.get("partitions", [])
                if partitions:
                    results["partitioned_nodes"].append(node_name)
                    errors.append(
                        f"CRITICAL: Node '{node_name}' has partitions: {partitions}"
                    )

                # Get resource info from first node as reference
                if idx == 0:
                    results["disk_free"] = node.get("disk_free")
                    results["disk_free_limit"] = node.get("disk_free_limit")
                    results["mem_used"] = node.get("mem_used")
                    results["mem_limit"] = node.get("mem_limit")
                    results["fd_used"] = node.get("fd_used")
                    results["fd_total"] = node.get("fd_total")
                    results["sockets_used"] = node.get("sockets_used")
                    results["sockets_total"] = node.get("sockets_total")

            results["cluster_size"] = len(results["nodes"])

            if results["cluster_size"] < 1:
                errors.append("No nodes found in cluster")

        except requests.exceptions.RequestException as exc:
            errors.append(f"Failed to get nodes information: {exc}")

        try:
            # Check health alarms
            response = requests.get(
                f"{base_url}/health/checks/alarms", auth=auth, timeout=10
            )
            response.raise_for_status()
            alarms_data = response.json()

            if alarms_data.get("status") != "ok":
                results["alarms"] = alarms_data.get("alarms", [])
                for alarm in results["alarms"]:
                    errors.append(f"Alarm: {alarm}")

        except requests.exceptions.RequestException as exc:
            errors.append(f"Failed to check health alarms: {exc}")

        return results, errors

    def take_action(self, parsed_args):
        format = parsed_args.format

        # Get RabbitMQ node address from inventory
        node_info = self._get_rabbitmq_node_address()
        if node_info is None:
            if format == "log":
                logger.error("Failed to get RabbitMQ node address from inventory")
            return 1

        node_address, node_name = node_info

        # Load RabbitMQ password
        password = self._load_rabbitmq_password()
        if password is None:
            if format == "log":
                logger.error("Failed to load RabbitMQ password")
            return 1

        # RabbitMQ user for OpenStack
        rabbitmq_user = "openstack"

        # Connect to RabbitMQ Management API
        if format == "log":
            logger.info(
                f"Connecting to RabbitMQ Management API at {node_address}:15672 ({node_name}) as {rabbitmq_user}..."
            )

        # Check RabbitMQ status
        results, errors = self._check_rabbitmq_status(
            node_address, rabbitmq_user, password
        )

        if format == "log":
            # Version info
            logger.info(f"RabbitMQ Version: {results['rabbitmq_version']}")
            logger.info(f"Erlang Version: {results['erlang_version']}")

            # Cluster info
            logger.info(f"Cluster Name: {results['cluster_name']}")
            logger.info(f"Cluster Size: {results['cluster_size']}")
            logger.info(f"Nodes: {', '.join(results['nodes']) or 'None'}")
            logger.info(
                f"Running Nodes: {', '.join(results['running_nodes']) or 'None'}"
            )

            # Partition status
            if results["partitioned_nodes"]:
                logger.error(
                    f"Partitioned Nodes: {', '.join(results['partitioned_nodes'])}"
                )
            else:
                logger.info("Partitions: None (healthy)")

            # Statistics
            logger.info(
                f"Connections: {results['total_connections']}, "
                f"Channels: {results['total_channels']}, "
                f"Queues: {results['total_queues']}"
            )
            logger.info(
                f"Messages: {results['total_messages']} total, "
                f"{results['messages_ready']} ready, "
                f"{results['messages_unacked']} unacked"
            )
            logger.info(
                f"Message Rates: {results['publish_rate']:.1f}/s publish, "
                f"{results['deliver_rate']:.1f}/s deliver"
            )

            # Resource usage (from first node)
            if results["disk_free"] is not None:
                disk_free_gb = results["disk_free"] / (1024**3)
                disk_limit_gb = (results["disk_free_limit"] or 0) / (1024**3)
                logger.info(
                    f"Disk Free: {disk_free_gb:.1f} GB (limit: {disk_limit_gb:.1f} GB)"
                )

            if results["mem_used"] is not None:
                mem_used_gb = results["mem_used"] / (1024**3)
                mem_limit_gb = (results["mem_limit"] or 0) / (1024**3)
                logger.info(
                    f"Memory Used: {mem_used_gb:.2f} GB (limit: {mem_limit_gb:.2f} GB)"
                )

            if results["fd_used"] is not None:
                logger.info(
                    f"File Descriptors: {results['fd_used']}/{results['fd_total']}"
                )

            if results["sockets_used"] is not None:
                logger.info(
                    f"Sockets: {results['sockets_used']}/{results['sockets_total']}"
                )

            if results["alarms"]:
                logger.warning(f"Alarms: {results['alarms']}")

            if errors:
                for error in errors:
                    logger.error(error)
                logger.error("RabbitMQ Cluster validation FAILED")
                return 1
            else:
                logger.info("RabbitMQ Cluster validation PASSED")
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
