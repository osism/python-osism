# SPDX-License-Identifier: Apache-2.0

import json
from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.tasks.conductor import get_redfish_resources


class List(Command):
    def _normalize_column_name(self, column_name):
        """Normalize column name to lowercase with underscores instead of spaces."""
        if not column_name:
            return column_name
        return column_name.lower().replace(" ", "_")

    def _get_column_mappings(self, resourcetype):
        """Get column mappings for a specific resource type."""
        if resourcetype == "EthernetInterfaces":
            return {
                "ID": "id",
                "Name": "name",
                "Description": "description",
                "MAC Address": "mac_address",
                "Permanent MAC Address": "permanent_mac_address",
                "Speed (Mbps)": "speed_mbps",
                "MTU Size": "mtu_size",
                "Link Status": "link_status",
                "Interface Enabled": "interface_enabled",
            }
        elif resourcetype == "NetworkAdapters":
            return {
                "ID": "id",
                "Name": "name",
                "Description": "description",
                "Manufacturer": "manufacturer",
                "Model": "model",
                "Part Number": "part_number",
                "Serial Number": "serial_number",
                "Firmware Version": "firmware_version",
            }
        elif resourcetype == "NetworkDeviceFunctions":
            return {
                "ID": "id",
                "Name": "name",
                "Description": "description",
                "Device Enabled": "device_enabled",
                "Ethernet Enabled": "ethernet_enabled",
                "MAC Address": "mac_address",
                "Permanent MAC Address": "permanent_mac_address",
                "Adapter ID": "adapter_id",
                "Adapter Name": "adapter_name",
            }
        return None

    def _get_filtered_columns(self, column_mappings, selected_columns=None):
        """Get filtered column mappings based on selected columns."""
        # If no columns specified, use all available columns
        if not selected_columns:
            return list(column_mappings.keys()), list(column_mappings.values())

        # Normalize selected columns and filter
        normalized_selected = [
            self._normalize_column_name(col) for col in selected_columns
        ]
        headers = []
        data_keys = []

        for display_name, data_key in column_mappings.items():
            normalized_display = self._normalize_column_name(display_name)
            if normalized_display in normalized_selected:
                headers.append(display_name)
                data_keys.append(data_key)

        # Check if any requested columns were not found
        found_columns = [self._normalize_column_name(h) for h in headers]
        for requested_col in normalized_selected:
            if requested_col not in found_columns:
                logger.warning(
                    f"Column '{requested_col}' not found. Available columns: {list(column_mappings.keys())}"
                )

        return headers, data_keys

    def _filter_json_data(self, data, data_keys):
        """Filter JSON data to include only selected columns."""
        if not data or not data_keys:
            return data

        filtered_data = []
        for item in data:
            filtered_item = {key: item.get(key) for key in data_keys}
            filtered_data.append(filtered_item)

        return filtered_data

    def _filter_and_display_table(self, data, column_mappings, selected_columns=None):
        """Generic method to filter columns and display table data."""
        if not data:
            return

        headers, data_keys = self._get_filtered_columns(
            column_mappings, selected_columns
        )

        if not headers:
            print("No valid columns specified")
            return

        # Prepare table data
        table_data = []
        for item in data:
            row = [item.get(key, "N/A") for key in data_keys]
            table_data.append(row)

        # Display the table
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print(f"\nTotal items: {len(data)}")

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
        parser.add_argument(
            "--format",
            type=str,
            choices=["table", "json"],
            default="table",
            help="Output format (default: table)",
        )
        parser.add_argument(
            "--column",
            action="append",
            help="Column to include in output (can be used multiple times)",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        resourcetype = parsed_args.resourcetype
        output_format = parsed_args.format
        columns = parsed_args.column
        logger.info(
            f"Redfish list command called with hostname: {hostname}, resourcetype: {resourcetype}, format: {output_format}"
        )

        # Use Celery task to get Redfish resources
        task_result = get_redfish_resources.delay(hostname, resourcetype)
        result = task_result.get()

        if output_format == "json":
            if result:
                # Apply column filtering for JSON output if columns are specified
                if columns:
                    # Get column mappings for the resource type
                    column_mappings = self._get_column_mappings(resourcetype)
                    if column_mappings:
                        _, data_keys = self._get_filtered_columns(
                            column_mappings, columns
                        )
                        filtered_result = self._filter_json_data(result, data_keys)
                        print(json.dumps(filtered_result, indent=2))
                    else:
                        print(json.dumps(result, indent=2))
                else:
                    print(json.dumps(result, indent=2))
            else:
                print("[]")
        else:
            if resourcetype == "EthernetInterfaces" and result:
                self._display_ethernet_interfaces(result, columns)
            elif resourcetype == "NetworkAdapters" and result:
                self._display_network_adapters(result, columns)
            elif resourcetype == "NetworkDeviceFunctions" and result:
                self._display_network_device_functions(result, columns)
            elif result:
                logger.info(f"Retrieved resources: {result}")
            else:
                print(f"No {resourcetype} resources found for {hostname}")

    def _display_ethernet_interfaces(self, interfaces, selected_columns=None):
        """Display EthernetInterfaces in a formatted table."""
        if not interfaces:
            print("No EthernetInterfaces found")
            return

        column_mappings = self._get_column_mappings("EthernetInterfaces")
        self._filter_and_display_table(interfaces, column_mappings, selected_columns)

    def _display_network_adapters(self, adapters, selected_columns=None):
        """Display NetworkAdapters in a formatted table."""
        if not adapters:
            print("No NetworkAdapters found")
            return

        column_mappings = self._get_column_mappings("NetworkAdapters")
        self._filter_and_display_table(adapters, column_mappings, selected_columns)

    def _display_network_device_functions(
        self, device_functions, selected_columns=None
    ):
        """Display NetworkDeviceFunctions in a formatted table."""
        if not device_functions:
            print("No NetworkDeviceFunctions found")
            return

        column_mappings = self._get_column_mappings("NetworkDeviceFunctions")
        self._filter_and_display_table(
            device_functions, column_mappings, selected_columns
        )
