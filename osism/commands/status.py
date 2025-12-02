# SPDX-License-Identifier: Apache-2.0

import os

from celery import Celery
from cliff.command import Command
from loguru import logger
import pymysql
import requests
from tabulate import tabulate
import yaml

from osism.tasks import Config
from osism.tasks.conductor.utils import get_vault
from osism.utils.rabbitmq import (
    get_rabbitmq_node_addresses,
    load_rabbitmq_password,
    RABBITMQ_USER,
)

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
            # Basic cluster status
            "cluster_status": None,
            "connected": None,
            "ready": None,
            "cluster_size": None,
            "local_state": None,
            "cluster_state_uuid": None,
            # Cluster members
            "incoming_addresses": None,
            "provider_version": None,
            "local_node_uuid": None,
            # Flow control metrics
            "flow_control_paused": None,
            "local_recv_queue_avg": None,
            "local_send_queue_avg": None,
            # Transaction statistics
            "local_commits": None,
            "local_cert_failures": None,
            "local_bf_aborts": None,
            "replicated": None,
            "received": None,
            # General MariaDB metrics
            "uptime": None,
            "threads_connected": None,
            "threads_running": None,
            "questions": None,
            "slow_queries": None,
            "aborted_connects": None,
        }
        errors = []
        warnings = []

        try:
            with connection.cursor() as cursor:
                # Get wsrep status variables
                cursor.execute("SHOW STATUS LIKE 'wsrep_%'")
                wsrep_rows = cursor.fetchall()

                # Get general status variables
                cursor.execute(
                    "SHOW GLOBAL STATUS WHERE Variable_name IN "
                    "('Uptime', 'Threads_connected', 'Threads_running', "
                    "'Questions', 'Slow_queries', 'Aborted_connects')"
                )
                general_rows = cursor.fetchall()

            wsrep_status = {row[0]: row[1] for row in wsrep_rows}
            general_status = {row[0]: row[1] for row in general_rows}

            # === Basic Cluster Status ===

            # Check wsrep_cluster_status (should be "Primary")
            results["cluster_status"] = wsrep_status.get(
                "wsrep_cluster_status", "UNKNOWN"
            )
            if results["cluster_status"] != "Primary":
                errors.append(
                    f"Cluster status is '{results['cluster_status']}', expected 'Primary'"
                )

            # Check wsrep_connected (should be "ON")
            results["connected"] = wsrep_status.get("wsrep_connected", "UNKNOWN")
            if results["connected"] != "ON":
                errors.append(
                    f"Cluster connected is '{results['connected']}', expected 'ON'"
                )

            # Check wsrep_ready (should be "ON")
            results["ready"] = wsrep_status.get("wsrep_ready", "UNKNOWN")
            if results["ready"] != "ON":
                errors.append(f"Cluster ready is '{results['ready']}', expected 'ON'")

            # Check wsrep_cluster_size (should be > 0)
            results["cluster_size"] = wsrep_status.get("wsrep_cluster_size", "0")
            try:
                size = int(results["cluster_size"])
                if size < 1:
                    errors.append(f"Cluster size is {size}, expected at least 1")
            except ValueError:
                errors.append(f"Invalid cluster size: {results['cluster_size']}")

            # Check wsrep_local_state_comment (should be "Synced")
            results["local_state"] = wsrep_status.get(
                "wsrep_local_state_comment", "UNKNOWN"
            )
            if results["local_state"] != "Synced":
                errors.append(
                    f"Local state is '{results['local_state']}', expected 'Synced'"
                )

            # Get cluster state UUID for informational purposes
            results["cluster_state_uuid"] = wsrep_status.get(
                "wsrep_cluster_state_uuid", "UNKNOWN"
            )

            # === Cluster Members ===

            results["incoming_addresses"] = wsrep_status.get(
                "wsrep_incoming_addresses", "UNKNOWN"
            )
            results["provider_version"] = wsrep_status.get(
                "wsrep_provider_version", "UNKNOWN"
            )
            results["local_node_uuid"] = wsrep_status.get("wsrep_gcomm_uuid", "UNKNOWN")

            # === Flow Control Metrics ===

            results["flow_control_paused"] = wsrep_status.get(
                "wsrep_flow_control_paused", "0"
            )
            results["local_recv_queue_avg"] = wsrep_status.get(
                "wsrep_local_recv_queue_avg", "0"
            )
            results["local_send_queue_avg"] = wsrep_status.get(
                "wsrep_local_send_queue_avg", "0"
            )

            # Check flow control - warn if paused > 5%
            try:
                fc_paused = float(results["flow_control_paused"])
                if fc_paused > 0.05:
                    warnings.append(
                        f"Flow control paused ratio is {fc_paused:.2%}, "
                        "which may indicate replication lag"
                    )
            except ValueError:
                pass

            # Check receive queue average - warn if > 0.5
            try:
                recv_queue = float(results["local_recv_queue_avg"])
                if recv_queue > 0.5:
                    warnings.append(
                        f"Local receive queue average is {recv_queue:.2f}, "
                        "which may indicate apply lag"
                    )
            except ValueError:
                pass

            # === Transaction Statistics ===

            results["local_commits"] = wsrep_status.get("wsrep_local_commits", "0")
            results["local_cert_failures"] = wsrep_status.get(
                "wsrep_local_cert_failures", "0"
            )
            results["local_bf_aborts"] = wsrep_status.get("wsrep_local_bf_aborts", "0")
            results["replicated"] = wsrep_status.get("wsrep_replicated", "0")
            results["received"] = wsrep_status.get("wsrep_received", "0")

            # Check certification failures - warn if > 0
            try:
                cert_failures = int(results["local_cert_failures"])
                if cert_failures > 0:
                    warnings.append(
                        f"Certification failures: {cert_failures} "
                        "(transaction conflicts detected)"
                    )
            except ValueError:
                pass

            # === General MariaDB Metrics ===

            results["uptime"] = general_status.get("Uptime", "0")
            results["threads_connected"] = general_status.get("Threads_connected", "0")
            results["threads_running"] = general_status.get("Threads_running", "0")
            results["questions"] = general_status.get("Questions", "0")
            results["slow_queries"] = general_status.get("Slow_queries", "0")
            results["aborted_connects"] = general_status.get("Aborted_connects", "0")

        except Exception as exc:
            errors.append(f"Failed to query Galera status: {exc}")

        return results, errors, warnings

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
            results, errors, warnings = self._check_galera_status(connection)

            if format == "log":
                # === Basic Cluster Status ===
                logger.info(f"Cluster Status: {results['cluster_status']}")
                logger.info(f"Connected: {results['connected']}")
                logger.info(f"Ready: {results['ready']}")
                logger.info(f"Cluster Size: {results['cluster_size']}")
                logger.info(f"Local State: {results['local_state']}")
                logger.info(f"Cluster State UUID: {results['cluster_state_uuid']}")

                # === Cluster Members ===
                logger.info(f"Cluster Members: {results['incoming_addresses']}")
                logger.info(f"Galera Version: {results['provider_version']}")
                logger.info(f"Local Node UUID: {results['local_node_uuid']}")

                # === Flow Control Metrics ===
                try:
                    fc_paused = float(results["flow_control_paused"])
                    logger.info(f"Flow Control Paused: {fc_paused:.2%}")
                except (ValueError, TypeError):
                    logger.info(
                        f"Flow Control Paused: {results['flow_control_paused']}"
                    )

                logger.info(f"Recv Queue Avg: {results['local_recv_queue_avg']}")
                logger.info(f"Send Queue Avg: {results['local_send_queue_avg']}")

                # === Transaction Statistics ===
                logger.info(
                    f"Transactions: {results['local_commits']} local commits, "
                    f"{results['replicated']} replicated, "
                    f"{results['received']} received"
                )
                logger.info(
                    f"Conflicts: {results['local_cert_failures']} cert failures, "
                    f"{results['local_bf_aborts']} bf aborts"
                )

                # === General MariaDB Metrics ===
                try:
                    uptime_seconds = int(results["uptime"])
                    uptime_str = display_time(uptime_seconds)
                    logger.info(f"MariaDB Uptime: {uptime_str}")
                except (ValueError, TypeError):
                    logger.info(f"MariaDB Uptime: {results['uptime']}s")

                logger.info(
                    f"Threads: {results['threads_connected']} connected, "
                    f"{results['threads_running']} running"
                )
                logger.info(
                    f"Queries: {results['questions']} total, "
                    f"{results['slow_queries']} slow"
                )
                logger.info(f"Aborted Connects: {results['aborted_connects']}")

                # Show warnings
                if warnings:
                    for warning in warnings:
                        logger.warning(warning)

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
            "hosts",
            nargs="*",
            default=[],
            help="Optional hostname(s) to filter (default: all nodes)",
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        )
        return parser

    def _check_rabbitmq_status(self, vip_address, username, password, target_host=None):
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
            # Node resources (from target node or first node as reference)
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

            resource_node_found = False
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

                # Get resource info from target node (match by hostname in node name)
                # Node names are typically "rabbit@hostname"
                is_target_node = False
                if target_host:
                    is_target_node = node_name.endswith(f"@{target_host}")

                # Use target node's resources, or fall back to first node
                if (
                    (target_host and is_target_node)
                    or (not target_host and idx == 0)
                    or (
                        target_host
                        and not resource_node_found
                        and idx == len(nodes_data) - 1
                    )
                ):
                    if (
                        is_target_node
                        or not target_host
                        or (not resource_node_found and idx == len(nodes_data) - 1)
                    ):
                        results["disk_free"] = node.get("disk_free")
                        results["disk_free_limit"] = node.get("disk_free_limit")
                        results["mem_used"] = node.get("mem_used")
                        results["mem_limit"] = node.get("mem_limit")
                        results["fd_used"] = node.get("fd_used")
                        results["fd_total"] = node.get("fd_total")
                        results["sockets_used"] = node.get("sockets_used")
                        results["sockets_total"] = node.get("sockets_total")
                        resource_node_found = True

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
        filter_hosts = parsed_args.hosts

        # Get RabbitMQ node addresses from inventory
        node_addresses = get_rabbitmq_node_addresses()
        if node_addresses is None:
            if format == "log":
                logger.error("Failed to get RabbitMQ node addresses from inventory")
            return 1

        # Filter nodes if hostnames specified
        if filter_hosts:
            available_hosts = [name for _, name in node_addresses]
            filtered_addresses = [
                (addr, name) for addr, name in node_addresses if name in filter_hosts
            ]

            # Warn about unknown hosts
            for host in filter_hosts:
                if host not in available_hosts:
                    if format == "log":
                        logger.warning(
                            f"Host '{host}' not found in rabbitmq group, skipping"
                        )

            if not filtered_addresses:
                if format == "log":
                    logger.error(
                        f"None of the specified hosts found. Available: {', '.join(available_hosts)}"
                    )
                return 1

            node_addresses = filtered_addresses

        # Load RabbitMQ password
        password = load_rabbitmq_password()
        if password is None:
            if format == "log":
                logger.error("Failed to load RabbitMQ password")
            return 1

        all_errors = []
        all_results = []

        # Check each node
        for node_address, node_name in node_addresses:
            if format == "log":
                logger.info(
                    f"[{node_name}] Connecting to RabbitMQ Management API at {node_address}:15672 as {RABBITMQ_USER}..."
                )

            # Check RabbitMQ status for this node
            results, errors = self._check_rabbitmq_status(
                node_address, RABBITMQ_USER, password, target_host=node_name
            )
            results["node_name"] = node_name
            all_results.append(results)
            all_errors.extend([(node_name, e) for e in errors])

            if format == "log":
                # Version info
                logger.info(
                    f"[{node_name}] RabbitMQ Version: {results['rabbitmq_version']}"
                )
                logger.info(
                    f"[{node_name}] Erlang Version: {results['erlang_version']}"
                )

                # Cluster info
                logger.info(f"[{node_name}] Cluster Name: {results['cluster_name']}")
                logger.info(f"[{node_name}] Cluster Size: {results['cluster_size']}")
                logger.info(
                    f"[{node_name}] Nodes: {', '.join(results['nodes']) or 'None'}"
                )
                logger.info(
                    f"[{node_name}] Running Nodes: {', '.join(results['running_nodes']) or 'None'}"
                )

                # Partition status
                if results["partitioned_nodes"]:
                    logger.error(
                        f"[{node_name}] Partitioned Nodes: {', '.join(results['partitioned_nodes'])}"
                    )
                else:
                    logger.info(f"[{node_name}] Partitions: None (healthy)")

                # Statistics
                logger.info(
                    f"[{node_name}] Connections: {results['total_connections']}, "
                    f"Channels: {results['total_channels']}, "
                    f"Queues: {results['total_queues']}"
                )
                logger.info(
                    f"[{node_name}] Messages: {results['total_messages']} total, "
                    f"{results['messages_ready']} ready, "
                    f"{results['messages_unacked']} unacked"
                )
                logger.info(
                    f"[{node_name}] Message Rates: {results['publish_rate']:.1f}/s publish, "
                    f"{results['deliver_rate']:.1f}/s deliver"
                )

                # Resource usage
                if results["disk_free"] is not None:
                    disk_free_gb = results["disk_free"] / (1024**3)
                    disk_limit_gb = (results["disk_free_limit"] or 0) / (1024**3)
                    logger.info(
                        f"[{node_name}] Disk Free: {disk_free_gb:.1f} GB (limit: {disk_limit_gb:.1f} GB)"
                    )

                if results["mem_used"] is not None:
                    mem_used_gb = results["mem_used"] / (1024**3)
                    mem_limit_gb = (results["mem_limit"] or 0) / (1024**3)
                    logger.info(
                        f"[{node_name}] Memory Used: {mem_used_gb:.2f} GB (limit: {mem_limit_gb:.2f} GB)"
                    )

                if results["fd_used"] is not None:
                    logger.info(
                        f"[{node_name}] File Descriptors: {results['fd_used']}/{results['fd_total']}"
                    )

                if results["sockets_used"] is not None:
                    logger.info(
                        f"[{node_name}] Sockets: {results['sockets_used']}/{results['sockets_total']}"
                    )

                if results["alarms"]:
                    logger.warning(f"[{node_name}] Alarms: {results['alarms']}")

                # Show errors for this node
                node_errors = [e for n, e in all_errors if n == node_name]
                if node_errors:
                    for error in node_errors:
                        logger.error(f"[{node_name}] {error}")

        # Final summary
        if format == "log":
            if all_errors:
                logger.error("RabbitMQ Cluster validation FAILED")
                return 1
            else:
                logger.info("RabbitMQ Cluster validation PASSED")
                return 0

        elif format == "script":
            if all_errors:
                print("FAILED")
                for node_name, error in all_errors:
                    print(f"  - [{node_name}] {error}")
                return 1
            else:
                print("PASSED")
                return 0
