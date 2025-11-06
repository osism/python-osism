# SPDX-License-Identifier: Apache-2.0

import os
import subprocess

from cliff.command import Command
from loguru import logger
from tabulate import tabulate
import yaml

from osism.tasks import conductor, netbox, handle_task
from osism import utils


class Ironic(Command):
    def get_parser(self, prog_name):
        parser = super(Ironic, self).get_parser(prog_name)
        parser.add_argument(
            "node",
            nargs="?",
            help="Optional node name to sync only a specific node",
        )
        parser.add_argument(
            "--no-wait",
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--task-timeout",
            default=os.environ.get("OSISM_TASK_TIMEOUT", 300),
            type=int,
            help="Timeout for a scheduled task that has not been executed yet",
        )
        parser.add_argument(
            "--force-update",
            help="Force update of baremetal nodes (Used to update non-comparable items like passwords)",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        task_timeout = parsed_args.task_timeout
        node_name = parsed_args.node

        task = conductor.sync_ironic.delay(
            node_name=node_name, force_update=parsed_args.force_update
        )
        if wait:
            if node_name:
                logger.info(
                    f"Task {task.task_id} (sync ironic for node {node_name}) is running in background. Output comming soon."
                )
            else:
                logger.info(
                    f"Task {task.task_id} (sync ironic) is running in background. Output comming soon."
                )
            try:
                return utils.fetch_task_output(task.id, timeout=task_timeout)
            except TimeoutError:
                if node_name:
                    logger.error(
                        f"Timeout while waiting for further output of task {task.task_id} (sync ironic for node {node_name})"
                    )
                else:
                    logger.error(
                        f"Timeout while waiting for further output of task {task.task_id} (sync ironic)"
                    )
        else:
            if node_name:
                logger.info(
                    f"Task {task.task_id} (sync ironic for node {node_name}) is running in background. No more output."
                )
            else:
                logger.info(
                    f"Task {task.task_id} (sync ironic) is running in background. No more output."
                )


class Sync(Command):
    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait

        task = conductor.sync_netbox.delay()
        if wait:
            logger.info(
                f"Task {task.task_id} (sync netbox) is running. Wait. No more output."
            )
            task.wait(timeout=None, interval=0.5)


class Manage(Command):
    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the management of the NetBox has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--no-netbox-wait",
            default=False,
            help="Do not wait for the NetBox API to be ready",
            action="store_true",
        )
        parser.add_argument(
            "--parallel",
            type=str,
            default=None,
            help="Process up to n files in parallel",
        )
        parser.add_argument(
            "--limit",
            type=str,
            default=None,
            help="Limit files by prefix",
        )
        parser.add_argument(
            "--skipdtl",
            default=False,
            help="Skip devicetype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipmtl",
            default=False,
            help="Skip moduletype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipres",
            default=False,
            help="Skip resources",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        arguments = ["run"]

        if parsed_args.no_netbox_wait:
            arguments.append("--no-wait")
        else:
            arguments.append("--wait")

        if parsed_args.parallel:
            arguments.append("--parallel")
            arguments.append(parsed_args.parallel)

        if parsed_args.limit:
            arguments.append("--limit")
            arguments.append(parsed_args.limit)

        if parsed_args.skipdtl:
            arguments.append("--skipdtl")
        else:
            arguments.append("--no-skipdtl")

        if parsed_args.skipmtl:
            arguments.append("--skipmtl")
        else:
            arguments.append("--no-skipmtl")

        if parsed_args.skipres:
            arguments.append("--skipres")
        else:
            arguments.append("--no-skipres")

        task_signature = netbox.manage.si(*arguments)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (netbox-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Versions(Command):
    def get_parser(self, prog_name):
        parser = super(Versions, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        task = netbox.ping.delay()
        task.wait(timeout=None, interval=0.5)
        result = task.get()
        print(result)


class Console(Command):
    def get_parser(self, prog_name):
        parser = super(Console, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            nargs=1,
            choices=["info", "search", "filter", "shell"],
            help="Type of the console (default: %(default)s)",
        )
        parser.add_argument(
            "arguments", nargs="*", type=str, default="", help="Additional arguments"
        )

        return parser

    def take_action(self, parsed_args):
        type_console = parsed_args.type[0]
        arguments = " ".join(
            [f"'{item}'" if " " in item else item for item in parsed_args.arguments]
        )

        home_dir = os.path.expanduser("~")
        nbcli_dir = os.path.join(home_dir, ".nbcli")
        if not os.path.exists(nbcli_dir):
            os.mkdir(nbcli_dir)

        nbcli_file = os.path.join(nbcli_dir, "user_config.yml")
        if not os.path.exists(nbcli_file):
            try:
                with open("/run/secrets/NETBOX_TOKEN", "r") as fp:
                    token = str(fp.read().strip())
            except FileNotFoundError:
                token = ""

            url = os.environ.get("NETBOX_API", None)

            if not token or not url:
                logger.error("NetBox integration not configured.")
                return

            subprocess.call(
                ["/usr/local/bin/nbcli", "init"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.remove(nbcli_file)

            nbcli_config = {
                "pynetbox": {
                    "url": url,
                    "token": token,
                },
                "requests": {"verify": False},
                "nbcli": {"filter_limit": 50},
                "user": {},
            }
            with open(nbcli_file, "w") as fp:
                yaml.dump(nbcli_config, fp, default_flow_style=False)

        subprocess.call(f"/usr/local/bin/nbcli {type_console} {arguments}", shell=True)


class Show(Command):
    def get_parser(self, prog_name):
        parser = super(Show, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname or device name to search in NetBox",
        )
        parser.add_argument(
            "field",
            nargs="?",
            type=str,
            default=None,
            help="Optional field name filter (case-insensitive, partial match)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        field_filter = parsed_args.field

        # Check if NetBox connection is available
        if not utils.nb:
            logger.error("NetBox integration not configured.")
            return

        # Search for device by name first
        devices = list(utils.nb.dcim.devices.filter(name=host))

        # If not found by name, search by custom fields
        if not devices:
            # Search by alternative_name custom field
            devices = list(utils.nb.dcim.devices.filter(cf_alternative_name=host))

        if not devices:
            # Search by inventory_hostname custom field
            devices = list(utils.nb.dcim.devices.filter(cf_inventory_hostname=host))

        if not devices:
            # Search by external_hostname custom field
            devices = list(utils.nb.dcim.devices.filter(cf_external_hostname=host))

        if not devices:
            logger.error(f"Device '{host}' not found in NetBox.")
            return

        # Get the first matching device
        device = devices[0]

        # Prepare table data for display
        table = []

        # Add basic device information
        table.append(["Name", device.name])

        # Device type - defensively accessed
        device_type = getattr(device, "device_type", None)
        table.append(["Device Type", str(device_type) if device_type else "N/A"])

        # NetBox v3.x renamed device_role to role
        device_role = getattr(device, "role", None)
        table.append(["Device Role", str(device_role) if device_role else "N/A"])

        # Site and status
        site = getattr(device, "site", None)
        table.append(["Site", str(site) if site else "N/A"])

        status = getattr(device, "status", None)
        table.append(["Status", str(status) if status else "N/A"])

        # Add out-of-band IP
        oob_ip = getattr(device, "oob_ip", None)
        table.append(["Out-of-band IP", str(oob_ip.address) if oob_ip else "N/A"])

        # Add primary IPs - defensively accessed
        primary_ip4 = getattr(device, "primary_ip4", None)
        table.append(
            ["Primary IPv4", str(primary_ip4.address) if primary_ip4 else "N/A"]
        )

        primary_ip6 = getattr(device, "primary_ip6", None)
        table.append(
            ["Primary IPv6", str(primary_ip6.address) if primary_ip6 else "N/A"]
        )

        # Add custom fields if they exist - defensively accessed
        custom_fields = getattr(device, "custom_fields", {})

        # Display custom field parameters with YAML formatting
        if custom_fields:
            # Define YAML custom fields for consistent formatting
            yaml_fields = [
                "dnsmasq_parameters",
                "netplan_parameters",
                "sonic_parameters",
                "frr_parameters",
            ]

            for field_name in yaml_fields:
                field_value = custom_fields.get(field_name, None)
                if field_value:
                    try:
                        # Parse YAML string if needed, or use value directly if already parsed
                        if isinstance(field_value, str):
                            parsed_value = yaml.safe_load(field_value)
                        else:
                            parsed_value = field_value

                        # Format as YAML with proper indentation and structure
                        formatted_value = yaml.dump(
                            parsed_value,
                            default_flow_style=False,
                            indent=2,
                            sort_keys=False,
                            width=80,
                        ).strip()

                        table.append([field_name, formatted_value])
                    except Exception:
                        # Fallback to string representation if YAML parsing fails
                        table.append([field_name, str(field_value)])

            # alternative_name
            alternative_name = custom_fields.get("alternative_name", None)
            if alternative_name:
                table.append(["Alternative Name", str(alternative_name)])

            # inventory_hostname
            inventory_hostname = custom_fields.get("inventory_hostname", None)
            if inventory_hostname:
                table.append(["Inventory Hostname", str(inventory_hostname)])

            # external_hostname
            external_hostname = custom_fields.get("external_hostname", None)
            if external_hostname:
                table.append(["External Hostname", str(external_hostname)])

        # Apply field filter if specified
        if field_filter:
            filter_term = field_filter.lower()
            filtered_table = [row for row in table if filter_term in row[0].lower()]

            if not filtered_table:
                logger.warning(f"No fields matching '{field_filter}' found")
                return

            table = filtered_table

        # Print formatted table
        result = tabulate(table, headers=["Field", "Value"], tablefmt="grid")
        print(result)
