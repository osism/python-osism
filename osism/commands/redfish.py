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
            help="Resource type to process (e.g., EthernetInterfaces, NetworkAdapters, NetworkDeviceFunctions)",
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
        elif resourcetype == "NetworkAdapters" and result:
            self._display_network_adapters(result)
        elif resourcetype == "NetworkDeviceFunctions" and result:
            self._display_network_device_functions(result)
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

    def _display_network_adapters(self, adapters):
        """Display NetworkAdapters in a formatted table."""
        if not adapters:
            print("No NetworkAdapters found")
            return

        # Prepare table data with specified columns
        table_data = []
        headers = [
            "ID",
            "Name",
            "Manufacturer",
            "Model",
            "Part Number",
            "Serial Number",
            "Firmware Version",
            "Status",
        ]

        for adapter in adapters:
            # Extract values with fallbacks for missing data
            status_str = "N/A"
            if adapter.get("status"):
                status_data = adapter.get("status")
                if isinstance(status_data, str):
                    try:
                        import json

                        status_dict = json.loads(status_data)
                        status_str = status_dict.get("Health", "N/A")
                    except (json.JSONDecodeError, AttributeError):
                        status_str = status_data
                elif isinstance(status_data, dict):
                    status_str = status_data.get("Health", "N/A")

            row = [
                adapter.get("id", "N/A"),
                adapter.get("name", "N/A"),
                adapter.get("manufacturer", "N/A"),
                adapter.get("model", "N/A"),
                adapter.get("part_number", "N/A"),
                adapter.get("serial_number", "N/A"),
                adapter.get("firmware_version", "N/A"),
                status_str,
            ]
            table_data.append(row)

        # Display the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print(f"\nTotal NetworkAdapters: {len(adapters)}")

    def _display_network_device_functions(self, device_functions):
        """Display NetworkDeviceFunctions in a formatted table."""
        if not device_functions:
            print("No NetworkDeviceFunctions found")
            return

        # Prepare table data with specified columns
        table_data = []
        headers = [
            "ID",
            "Name",
            "MAC Address",
            "Permanent MAC",
            "Adapter Name",
            "Device Enabled",
            "Ethernet Enabled",
            "Status",
        ]

        for device_func in device_functions:
            # Extract values with fallbacks for missing data
            status_str = "N/A"
            if device_func.get("status"):
                status_data = device_func.get("status")
                if isinstance(status_data, str):
                    try:
                        import json

                        status_dict = json.loads(status_data)
                        status_str = status_dict.get("Health", "N/A")
                    except (json.JSONDecodeError, AttributeError):
                        status_str = status_data
                elif isinstance(status_data, dict):
                    status_str = status_data.get("Health", "N/A")

            row = [
                device_func.get("id", "N/A"),
                device_func.get("name", "N/A"),
                device_func.get("mac_address", "N/A"),
                device_func.get("permanent_mac_address", "N/A"),
                device_func.get("adapter_name", "N/A"),
                device_func.get("device_enabled", "N/A"),
                device_func.get("ethernet_enabled", "N/A"),
                status_str,
            ]
            table_data.append(row)

        # Display the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print(f"\nTotal NetworkDeviceFunctions: {len(device_functions)}")
