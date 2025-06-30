# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.tasks.conductor import get_redfish_resources


class List(Command):
    def get_parser(self, prog_name):
        parser = super(List, self).get_parser(prog_name)
        parser.add_argument(
            "hostname",
            type=str,
            help="Hostname of the target system",
        )
        parser.add_argument(
            "resourcetype",
            type=str,
            help="Resource type to process (e.g., EthernetInterfaces)",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        resourcetype = parsed_args.resourcetype
        logger.info(
            f"Redfish list command called with hostname: {hostname}, resourcetype: {resourcetype}"
        )

        # Use Celery task to get Redfish resources
        task_result = get_redfish_resources.delay(hostname, resourcetype)
        result = task_result.get()

        if resourcetype == "EthernetInterfaces" and result:
            self._display_ethernet_interfaces(result)
        elif result:
            logger.info(f"Retrieved resources: {result}")
        else:
            print(f"No {resourcetype} resources found for {hostname}")

    def _display_ethernet_interfaces(self, interfaces):
        """Display EthernetInterfaces in a formatted table."""
        if not interfaces:
            print("No EthernetInterfaces found")
            return

        # Prepare table data with specified columns
        table_data = []
        headers = [
            "ID",
            "Name",
            "MAC",
            "Permanent MAC",
            "Speed (Mbps)",
            "Link Status",
        ]

        for interface in interfaces:
            # Extract values with fallbacks for missing data
            row = [
                interface.get("id", "N/A"),
                interface.get("name", "N/A"),
                interface.get("mac_address", "N/A"),
                interface.get("permanent_mac_address", "N/A"),
                interface.get("speed_mbps", "N/A"),
                interface.get("link_status", "N/A"),
            ]
            table_data.append(row)

        # Display the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print(f"\nTotal EthernetInterfaces: {len(interfaces)}")
