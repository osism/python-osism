# SPDX-License-Identifier: Apache-2.0

import re
import urllib.parse

from cliff.command import Command
from loguru import logger
import requests

from osism.utils.rabbitmq import (
    get_rabbitmq_node_addresses,
    load_rabbitmq_password,
    RABBITMQ_USER,
)


# Service-specific queue patterns for classic queue identification
# Each service has a list of regex patterns that match its queues
SERVICE_QUEUE_PATTERNS = {
    "aodh": [
        r"^alarm\.all\..*$",
        r"^alarming\..*$",
    ],
    "barbican": [
        r"^barbican\.workers$",
        r"^barbican\.workers\..*$",
        r"^barbican\.workers_fanout_.*$",
        r"^barbican_notifications\..*$",
    ],
    "ceilometer": [
        r"^ceilometer-agent-notification$",
        r"^ceilometer-agent-notification\..*$",
        r"^ceilometer-agent-notification_fanout_.*$",
        r"^metering$",
        r"^metering\..*$",
        r"^event\.sample$",
    ],
    "cinder": [
        r"^cinder-backup$",
        r"^cinder-backup\..*$",
        r"^cinder-backup_fanout_.*$",
        r"^cinder-scheduler$",
        r"^cinder-scheduler\..*$",
        r"^cinder-scheduler_fanout_.*$",
        r"^cinder-volume$",
        r"^cinder-volume\..*$",
        r"^cinder-volume_fanout_.*$",
    ],
    "designate": [
        r"^central$",
        r"^central\..*$",
        r"^central_fanout_.*$",
        r"^producer$",
        r"^producer\..*$",
        r"^producer_fanout_.*$",
        r"^worker$",
        r"^worker\..*$",
        r"^worker_fanout_.*$",
        r"^reply_[a-f0-9]+$",
    ],
    "notifications": [
        r"^notifications\..*$",
        r"^versioned_notifications\..*$",
    ],
    "manager": [
        r"^osism-listener-.*$",
    ],
    "magnum": [
        r"^magnum-conductor$",
        r"^magnum-conductor\..*$",
        r"^magnum-conductor_fanout_.*$",
    ],
    "manila": [
        r"^manila-data$",
        r"^manila-data\..*$",
        r"^manila-data_fanout_.*$",
        r"^manila-scheduler$",
        r"^manila-scheduler\..*$",
        r"^manila-scheduler_fanout_.*$",
        r"^manila-share$",
        r"^manila-share\..*$",
        r"^manila-share_fanout_.*$",
    ],
    "neutron": [
        r"^q-plugin$",
        r"^q-plugin\..*$",
        r"^q-reports-plugin$",
        r"^q-reports-plugin\..*$",
        r"^q-server-resource-versions$",
        r"^q-server-resource-versions\..*$",
        r"^q-agent-notifier-.*$",
        r"^q-l3-plugin$",
        r"^q-l3-plugin\..*$",
        r"^q-metering-plugin$",
        r"^q-metering-plugin\..*$",
        r"^l3_agent$",
        r"^l3_agent\..*$",
        r"^l3_agent_fanout_.*$",
        r"^dhcp_agent$",
        r"^dhcp_agent\..*$",
        r"^dhcp_agent_fanout_.*$",
    ],
    "nova": [
        r"^compute$",
        r"^compute\..*$",
        r"^compute_fanout_.*$",
        r"^conductor$",
        r"^conductor\..*$",
        r"^conductor_fanout_.*$",
        r"^scheduler$",
        r"^scheduler\..*$",
        r"^scheduler_fanout_.*$",
        r"^cert$",
        r"^cert\..*$",
        r"^cert_fanout_.*$",
        r"^consoleauth$",
        r"^consoleauth\..*$",
        r"^consoleauth_fanout_.*$",
        r"^cells$",
        r"^cells\..*$",
    ],
    "octavia": [
        r"^octavia_provisioning_v2$",
        r"^octavia_provisioning_v2\..*$",
        r"^octavia_provisioning_v2_fanout_.*$",
    ],
}


# Special commands that are not service names
SPECIAL_COMMANDS = ["list", "delete", "prepare", "check"]


class Rabbitmq3to4(Command):
    """Prepare migration from RabbitMQ 3 to RabbitMQ 4 by removing classic queues"""

    def get_parser(self, prog_name):
        parser = super(Rabbitmq3to4, self).get_parser(prog_name)
        parser.add_argument(
            "command",
            nargs="?",
            default=None,
            choices=SPECIAL_COMMANDS,
            help="Command: 'list' (show queues), 'delete' (remove queues), 'prepare' (create vhost), 'check' (check if migration needed)",
        )
        parser.add_argument(
            "service",
            nargs="?",
            default=None,
            choices=list(SERVICE_QUEUE_PATTERNS.keys()),
            help="Service name to filter/delete queues (used with 'list' or 'delete' command)",
        )
        parser.add_argument(
            "--server",
            default=None,
            help="RabbitMQ node hostname to connect to (default: first node in rabbitmq group)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which queues would be deleted without actually deleting them",
        )
        parser.add_argument(
            "--no-close-connections",
            action="store_true",
            help="Do not close consumer connections before deleting queues (default: connections are closed)",
        )
        parser.add_argument(
            "--quorum",
            action="store_true",
            help="List quorum queues instead of classic queues (only for 'list' command)",
        )
        parser.add_argument(
            "--vhost",
            default="/",
            help="Virtual host to filter queues (default: /). Used with 'list' and 'delete' commands",
        )
        return parser

    def _check_kolla_configuration(self):
        """Check kolla configuration for required settings.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        config_path = "/opt/configuration/environments/kolla/configuration.yml"

        try:
            with open(config_path) as f:
                content = f.read()
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            return False
        except OSError as exc:
            logger.error(f"Failed to read configuration file: {exc}")
            return False

        # Check that om_enable_rabbitmq_quorum_queues is not set to false/"no"
        # Valid values: true, "yes", or not set at all
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(
                r'^om_enable_rabbitmq_quorum_queues:\s*(false|"no")\s*$', stripped
            ):
                logger.error(
                    f"Invalid configuration in {config_path}: "
                    "'om_enable_rabbitmq_quorum_queues' must be set to 'true' or removed"
                )
                return False

        # Check that om_rpc_vhost: "openstack" or om_rpc_vhost: openstack is present
        has_rpc_vhost = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r'^om_rpc_vhost:\s*["\']?openstack["\']?\s*$', stripped):
                has_rpc_vhost = True
                break

        if not has_rpc_vhost:
            logger.error(
                f"Missing configuration in {config_path}: "
                "'om_rpc_vhost: openstack' must be added"
            )
            return False

        # Check that om_notify_vhost: "openstack" or om_notify_vhost: openstack is present
        has_notify_vhost = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r'^om_notify_vhost:\s*["\']?openstack["\']?\s*$', stripped):
                has_notify_vhost = True
                break

        if not has_notify_vhost:
            logger.error(
                f"Missing configuration in {config_path}: "
                "'om_notify_vhost: openstack' must be added"
            )
            return False

        logger.info("Kolla configuration check passed")
        return True

    def _prepare_vhost(self, base_url, auth, dry_run=False):
        """Create 'openstack' vhost with quorum queue default and set permissions.

        Args:
            base_url: RabbitMQ API base URL.
            auth: Authentication tuple (username, password).
            dry_run: If True, don't actually create vhost.

        Returns:
            bool: True if successful, False on error.
        """
        # Check kolla configuration first
        if not self._check_kolla_configuration():
            return False

        vhost_name = "openstack"
        username = "openstack"

        if dry_run:
            logger.info(
                f"[DRY-RUN] Would create vhost '{vhost_name}' with default_queue_type=quorum"
            )
            logger.info(
                f"[DRY-RUN] Would set permissions for user '{username}' on vhost '{vhost_name}'"
            )
            return True

        try:
            # Create vhost with default_queue_type=quorum
            encoded_vhost = urllib.parse.quote(vhost_name, safe="")
            response = requests.put(
                f"{base_url}/vhosts/{encoded_vhost}",
                auth=auth,
                json={"default_queue_type": "quorum"},
                timeout=30,
            )
            response.raise_for_status()
            logger.info(f"Created vhost '{vhost_name}' with default_queue_type=quorum")

            # Set permissions for openstack user
            response = requests.put(
                f"{base_url}/permissions/{encoded_vhost}/{username}",
                auth=auth,
                json={"configure": ".*", "write": ".*", "read": ".*"},
                timeout=30,
            )
            response.raise_for_status()
            logger.info(
                f"Set permissions for user '{username}' on vhost '{vhost_name}'"
            )

            return True

        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 409:
                logger.warning(f"Vhost '{vhost_name}' already exists")
                return True
            logger.error(f"Failed to prepare vhost: {exc}")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error(f"Failed to prepare vhost: {exc}")
            return False

    def _get_all_queues(self, base_url, auth):
        """Get all queues from RabbitMQ API.

        Returns:
            list: List of queue dictionaries, or None on error.
        """
        try:
            response = requests.get(f"{base_url}/queues", auth=auth, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.error(f"Failed to get queues: {exc}")
            return None

    def _get_classic_queues(self, queues):
        """Filter queues to only include classic queues.

        Args:
            queues: List of queue dictionaries from RabbitMQ API.

        Returns:
            list: List of classic queue dictionaries.
        """
        classic_queues = []
        for queue in queues:
            # In RabbitMQ 3.x, classic queues have type "classic" or no type specified
            # In RabbitMQ 4.x, quorum queues have type "quorum"
            queue_type = queue.get("type", "classic")
            if queue_type == "classic":
                classic_queues.append(queue)
        return classic_queues

    def _get_quorum_queues(self, queues):
        """Filter queues to only include quorum queues.

        Args:
            queues: List of queue dictionaries from RabbitMQ API.

        Returns:
            list: List of quorum queue dictionaries.
        """
        quorum_queues = []
        for queue in queues:
            queue_type = queue.get("type", "classic")
            if queue_type == "quorum":
                quorum_queues.append(queue)
        return quorum_queues

    def _match_queues_for_service(self, queues, service):
        """Match queues against service patterns.

        Args:
            queues: List of queue dictionaries.
            service: Service name to match patterns for.

        Returns:
            list: List of matching queue dictionaries.
        """
        patterns = SERVICE_QUEUE_PATTERNS.get(service, [])
        compiled_patterns = [re.compile(p) for p in patterns]

        matched_queues = []
        for queue in queues:
            queue_name = queue.get("name", "")
            for pattern in compiled_patterns:
                if pattern.match(queue_name):
                    matched_queues.append(queue)
                    break

        return matched_queues

    def _close_queue_connections(
        self, base_url, auth, vhost, queue_name, dry_run=False
    ):
        """Close all connections that have consumers on the specified queue.

        Args:
            base_url: RabbitMQ API base URL.
            auth: Authentication tuple (username, password).
            vhost: Virtual host name.
            queue_name: Name of the queue.
            dry_run: If True, don't actually close connections.

        Returns:
            int: Number of connections closed.
        """
        try:
            # Get queue details including consumer information
            encoded_vhost = urllib.parse.quote(vhost, safe="")
            encoded_queue = urllib.parse.quote(queue_name, safe="")

            response = requests.get(
                f"{base_url}/queues/{encoded_vhost}/{encoded_queue}",
                auth=auth,
                timeout=30,
            )

            if response.status_code == 404:
                return 0

            response.raise_for_status()
            queue_info = response.json()

            # Get consumer details
            consumer_details = queue_info.get("consumer_details", [])
            if not consumer_details:
                return 0

            # Collect unique connection names
            connection_names = set()
            for consumer in consumer_details:
                channel_details = consumer.get("channel_details", {})
                connection_name = channel_details.get("connection_name")
                if connection_name:
                    connection_names.add(connection_name)

            if not connection_names:
                return 0

            # Close each connection
            closed_count = 0
            for conn_name in connection_names:
                if dry_run:
                    logger.info(f"[DRY-RUN] Would close connection: {conn_name}")
                    closed_count += 1
                    continue

                try:
                    encoded_conn = urllib.parse.quote(conn_name, safe="")
                    response = requests.delete(
                        f"{base_url}/connections/{encoded_conn}",
                        auth=auth,
                        timeout=30,
                    )
                    if response.status_code in (200, 204):
                        logger.info(f"Closed connection: {conn_name}")
                        closed_count += 1
                    elif response.status_code == 404:
                        # Connection already closed
                        pass
                    else:
                        response.raise_for_status()
                except requests.exceptions.RequestException as exc:
                    logger.warning(f"Failed to close connection '{conn_name}': {exc}")

            return closed_count

        except requests.exceptions.RequestException as exc:
            logger.warning(f"Failed to get queue consumers for '{queue_name}': {exc}")
            return 0

    def _delete_queue(
        self, base_url, auth, vhost, queue_name, dry_run=False, close_connections=False
    ):
        """Delete a queue from RabbitMQ.

        Args:
            base_url: RabbitMQ API base URL.
            auth: Authentication tuple (username, password).
            vhost: Virtual host name (URL encoded).
            queue_name: Name of the queue to delete.
            dry_run: If True, don't actually delete.
            close_connections: If True, close consumer connections before deleting.

        Returns:
            bool: True if successful (or dry run or already deleted), False on error.
        """
        # Close connections first if requested
        if close_connections:
            closed = self._close_queue_connections(
                base_url, auth, vhost, queue_name, dry_run
            )
            if closed > 0 and not dry_run:
                logger.info(f"Closed {closed} connection(s) for queue: {queue_name}")

        if dry_run:
            logger.info(f"[DRY-RUN] Would delete queue: {queue_name}")
            return True

        try:
            # URL encode the vhost and queue name
            encoded_vhost = urllib.parse.quote(vhost, safe="")
            encoded_queue = urllib.parse.quote(queue_name, safe="")

            response = requests.delete(
                f"{base_url}/queues/{encoded_vhost}/{encoded_queue}",
                auth=auth,
                timeout=30,
            )
            response.raise_for_status()
            logger.info(f"Deleted queue: {queue_name}")
            return True
        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 404:
                # Queue was already deleted (possibly by another process or
                # it was recreated and deleted in a race condition)
                logger.warning(
                    f"Queue '{queue_name}' not found (already deleted or recreated by running service)"
                )
                return True
            logger.error(f"Failed to delete queue '{queue_name}': {exc}")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error(f"Failed to delete queue '{queue_name}': {exc}")
            return False

    def take_action(self, parsed_args):
        command = parsed_args.command
        service = parsed_args.service
        server = parsed_args.server
        dry_run = parsed_args.dry_run
        close_connections = not parsed_args.no_close_connections
        list_quorum = parsed_args.quorum
        vhost_filter = parsed_args.vhost

        # Determine command type
        is_list = command == "list"
        is_delete = command == "delete"
        is_prepare = command == "prepare"
        is_check = command == "check"

        # Validate arguments
        if not command:
            logger.error("A command (list, delete, prepare, check) must be specified")
            return 1

        # Get RabbitMQ node addresses from inventory
        node_addresses = get_rabbitmq_node_addresses()
        if node_addresses is None:
            logger.error("Failed to get RabbitMQ node addresses from inventory")
            return 1

        # Select target node
        if server:
            # Find the specified server
            target_address = None
            available_hosts = [name for _, name in node_addresses]
            for addr, name in node_addresses:
                if name == server:
                    target_address = addr
                    target_name = name
                    break
            if target_address is None:
                logger.error(
                    f"Server '{server}' not found in rabbitmq group. "
                    f"Available: {', '.join(available_hosts)}"
                )
                return 1
        else:
            # Use the first node
            target_address, target_name = node_addresses[0]

        # Load RabbitMQ password
        password = load_rabbitmq_password()
        if password is None:
            logger.error("Failed to load RabbitMQ password")
            return 1

        base_url = f"http://{target_address}:15672/api"
        auth = (RABBITMQ_USER, password)

        logger.info(
            f"Connecting to RabbitMQ Management API at {target_address}:15672 "
            f"(node: {target_name}) as {RABBITMQ_USER}..."
        )

        # Handle 'prepare' command
        if is_prepare:
            if self._prepare_vhost(base_url, auth, dry_run):
                return 0
            return 1

        # Get all queues
        queues = self._get_all_queues(base_url, auth)
        if queues is None:
            return 1

        # Filter queues by vhost for list and delete commands
        if is_list or is_delete:
            queues = [q for q in queues if q.get("vhost", "/") == vhost_filter]

        # Get classic and quorum queues
        classic_queues = self._get_classic_queues(queues)
        quorum_queues = self._get_quorum_queues(queues)

        # Handle 'check' command
        if is_check:
            # Get all queues (not filtered by vhost) for check
            all_queues = self._get_all_queues(base_url, auth)
            if all_queues is None:
                return 1

            # Get all unique vhosts
            all_vhosts = sorted(set(q.get("vhost", "/") for q in all_queues))

            # Get totals
            all_classic = self._get_classic_queues(all_queues)
            all_quorum = self._get_quorum_queues(all_queues)

            logger.info(f"Found {len(all_classic)} classic queue(s)")
            logger.info(f"Found {len(all_quorum)} quorum queue(s)")

            # Log breakdown by vhost
            for vhost in all_vhosts:
                vhost_queues = [q for q in all_queues if q.get("vhost", "/") == vhost]
                classic_in_vhost = self._get_classic_queues(vhost_queues)
                quorum_in_vhost = self._get_quorum_queues(vhost_queues)
                if classic_in_vhost:
                    logger.info(
                        f"  - {len(classic_in_vhost)} classic queue(s) in vhost {vhost}"
                    )
                if quorum_in_vhost:
                    logger.info(
                        f"  - {len(quorum_in_vhost)} quorum queue(s) in vhost {vhost}"
                    )

            # Get queues by known vhosts for migration status check
            queues_root = [q for q in all_queues if q.get("vhost", "/") == "/"]
            queues_openstack = [
                q for q in all_queues if q.get("vhost", "/") == "/openstack"
            ]

            # Get classic queues in / vhost
            classic_in_root = self._get_classic_queues(queues_root)
            # Get quorum queues in /openstack vhost
            quorum_in_openstack = self._get_quorum_queues(queues_openstack)
            # Get quorum queues in / vhost (legacy mixed setup)
            quorum_in_root = self._get_quorum_queues(queues_root)

            has_classic_in_root = len(classic_in_root) > 0
            has_quorum_in_openstack = len(quorum_in_openstack) > 0
            has_quorum_in_root = len(quorum_in_root) > 0
            has_classic = len(all_classic) > 0
            has_quorum = len(all_quorum) > 0

            # Check for migration in progress scenarios:
            # 1. Classic queues in / AND quorum queues in /openstack
            # 2. Classic queues in / AND quorum queues in / (legacy mixed setup)
            if has_classic_in_root and (has_quorum_in_openstack or has_quorum_in_root):
                logger.info(
                    "Migration is IN PROGRESS: Classic queues in / and quorum queues "
                    "in /openstack or / found"
                )
                return 0

            if has_classic and not has_quorum:
                logger.info(
                    "Migration is REQUIRED: Only classic queues found, no quorum queues"
                )
                return 0
            elif not has_classic and has_quorum:
                logger.info("Migration is NOT required: Only quorum queues found")
                return 0
            elif has_classic and has_quorum:
                logger.info(
                    "Migration is IN PROGRESS: Both classic and quorum queues found"
                )
                return 0
            else:
                logger.info("Migration is NOT required: No queues found")
                return 0

        # Handle 'list' command
        if is_list:
            # Determine which queues to list
            if list_quorum:
                queues_to_list = quorum_queues
                queue_type_info = "quorum"
            else:
                queues_to_list = classic_queues
                queue_type_info = "classic"

            # Filter by service if specified
            if service:
                queues_to_list = self._match_queues_for_service(queues_to_list, service)
                service_info = f" for service '{service}'"
            else:
                service_info = ""

            vhost_info = f" in vhost '{vhost_filter}'"

            if not queues_to_list:
                logger.info(
                    f"No {queue_type_info} queues found{service_info}{vhost_info}"
                )
                return 0

            logger.info(
                f"Found {len(queues_to_list)} {queue_type_info} queue(s){service_info}{vhost_info}:"
            )
            for queue in sorted(queues_to_list, key=lambda q: q.get("name", "")):
                name = queue.get("name", "")
                vhost = queue.get("vhost", "/")
                messages = queue.get("messages", 0)
                logger.info(f"  - {name} (vhost: {vhost}, messages: {messages})")
            return 0

        # Handle 'delete' command
        if is_delete:
            # Filter by service if specified
            if service:
                queues_to_delete = self._match_queues_for_service(
                    classic_queues, service
                )
                service_info = f" for service '{service}'"
            else:
                queues_to_delete = classic_queues
                service_info = ""

            vhost_info = f" in vhost '{vhost_filter}'"

            if not queues_to_delete:
                logger.info(f"No classic queues found{service_info}{vhost_info}")
                return 0

            logger.info(
                f"Found {len(queues_to_delete)} classic queue(s){service_info}{vhost_info}"
            )

            failed_count = 0
            for queue in sorted(queues_to_delete, key=lambda q: q.get("name", "")):
                name = queue.get("name", "")
                vhost = queue.get("vhost", "/")
                if not self._delete_queue(
                    base_url, auth, vhost, name, dry_run, close_connections
                ):
                    failed_count += 1

            if failed_count > 0:
                logger.error(f"Failed to delete {failed_count} queue(s)")
                return 1

            if dry_run:
                logger.info(
                    f"[DRY-RUN] Would delete {len(queues_to_delete)} queue(s){service_info}{vhost_info}"
                )
            else:
                logger.info(
                    f"Successfully deleted {len(queues_to_delete)} queue(s){service_info}{vhost_info}"
                )
            return 0

        return 0
