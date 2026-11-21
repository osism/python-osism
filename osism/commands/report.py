# SPDX-License-Identifier: Apache-2.0

import configparser
from datetime import datetime, timezone
import fnmatch
import json
import subprocess

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism import settings, utils
from osism.commands.console import resolve_host_with_fallback
from osism.utils.hardware import parse_linux, parse_sonic
from osism.utils.hardware.collect import (
    Request,
    add_collection_arguments,
    collect,
    dump_raw,
)
from osism.utils.hardware.mapping import (
    fetch_interfaces,
    map_node_ports,
    map_switch_ports,
    physical_interfaces,
    sonic_name_index,
)
from osism.utils.hardware.parse_lldp import LldpError, linux_neighbours
from osism.utils.hardware.render import (
    Column,
    RenderError,
    add_output_arguments,
    flatten,
    render_csv,
    render_json,
    render_table,
    select_columns,
    sort_rows,
    write_output,
)
from osism.utils.hardware.selection import (
    KIND_NODE,
    KIND_SWITCH,
    SelectionError,
    add_selection_arguments,
    resolve_addresses,
    select_targets,
)
from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path
from osism.utils.ssh import ensure_known_hosts_file, KNOWN_HOSTS_PATH


class Memory(Command):
    def get_parser(self, prog_name):
        parser = super(Memory, self).get_parser(prog_name)
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit selected hosts to an additional pattern",
        )
        return parser

    def take_action(self, parsed_args):
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        try:
            command = [
                "ansible-inventory",
                "-i",
                get_inventory_path("/ansible/inventory/hosts.yml"),
                "--list",
            ]
            if parsed_args.limit:
                command.extend(["--limit", parsed_args.limit])

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("Error loading inventory.")
                return 1
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return 1

        data = json.loads(result.stdout)
        hosts = get_hosts_from_inventory(data)

        if not hosts:
            logger.error("No hosts found in inventory.")
            return

        ssh_base = [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            "-o",
            "ConnectTimeout=10",
        ]
        dmidecode_command = (
            "sudo dmidecode -t memory | grep 'Size:' | grep -v 'No Module'"
            " | awk '{if($3==\"MB\") s+=$2/1024; else s+=$2} END {print s}'"
        )
        uuid_command = "sudo cat /sys/class/dmi/id/product_uuid"

        table = []
        total_memory_gb = 0
        failed_hosts = []

        for host in hosts:
            resolved_host = resolve_host_with_fallback(host)

            try:
                memory_result = subprocess.run(
                    [
                        *ssh_base,
                        f"{settings.OPERATOR_USER}@{resolved_host}",
                        dmidecode_command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if memory_result.returncode != 0:
                    logger.warning(
                        f"Failed to get memory info from {host}: {memory_result.stderr.strip()}"
                    )
                    failed_hosts.append(host)
                    continue

                uuid_result = subprocess.run(
                    [
                        *ssh_base,
                        f"{settings.OPERATOR_USER}@{resolved_host}",
                        uuid_command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                product_uuid = (
                    uuid_result.stdout.strip() if uuid_result.returncode == 0 else "n/a"
                )
                memory_gb = int(memory_result.stdout.strip())
                total_memory_gb += memory_gb
                table.append([host, product_uuid, memory_gb])

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout connecting to {host}.")
                failed_hosts.append(host)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse memory info from {host}.")
                failed_hosts.append(host)

        if table:
            print(
                tabulate(
                    table,
                    headers=["Host", "UUID", "Memory (GB)"],
                    tablefmt="psql",
                )
            )
            print()
            print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Hosts: {len(table)}")
            print(f"Memory: {total_memory_gb} GB")

        if failed_hosts:
            print()
            logger.warning(
                f"Failed to query {len(failed_hosts)} host(s): {', '.join(failed_hosts)}"
            )


class Lldp(Command):
    def get_parser(self, prog_name):
        parser = super(Lldp, self).get_parser(prog_name)
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit selected hosts to an additional pattern",
        )
        return parser

    def take_action(self, parsed_args):
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        try:
            command = [
                "ansible-inventory",
                "-i",
                get_inventory_path("/ansible/inventory/hosts.yml"),
                "--list",
            ]
            if parsed_args.limit:
                command.extend(["--limit", parsed_args.limit])

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("Error loading inventory.")
                return 1
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return 1

        data = json.loads(result.stdout)
        hosts = get_hosts_from_inventory(data)

        if not hosts:
            logger.error("No hosts found in inventory.")
            return

        ssh_base = [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            "-o",
            "ConnectTimeout=10",
        ]
        lldp_command = "lldpctl -f json"

        table = []
        failed_hosts = []

        for host in hosts:
            resolved_host = resolve_host_with_fallback(host)

            try:
                lldp_result = subprocess.run(
                    [
                        *ssh_base,
                        f"{settings.OPERATOR_USER}@{resolved_host}",
                        lldp_command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if lldp_result.returncode != 0:
                    logger.warning(
                        f"Failed to get LLDP info from {host}: {lldp_result.stderr.strip()}"
                    )
                    failed_hosts.append(host)
                    continue

                lldp_data = json.loads(lldp_result.stdout)
                interfaces = lldp_data.get("lldp", {}).get("interface", {})

                # lldpctl returns a list of dicts for multiple interfaces,
                # but a single dict for one interface. Normalize to list.
                if isinstance(interfaces, dict):
                    interfaces = [{k: v} for k, v in interfaces.items()]

                for iface_entry in interfaces:
                    for local_iface, iface_data in iface_entry.items():
                        chassis = iface_data.get("chassis", {})
                        remote_switch = next(iter(chassis), "n/a")

                        port = iface_data.get("port", {})
                        remote_port = port.get("id", {}).get("value", "n/a")
                        port_descr = port.get("descr", "")

                        age = iface_data.get("age", "n/a")

                        table.append(
                            [
                                host,
                                local_iface,
                                remote_switch,
                                remote_port,
                                port_descr,
                                age,
                            ]
                        )

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout connecting to {host}.")
                failed_hosts.append(host)
            except (ValueError, json.JSONDecodeError):
                logger.warning(f"Could not parse LLDP info from {host}.")
                failed_hosts.append(host)

        if table:
            print(
                tabulate(
                    table,
                    headers=[
                        "Host",
                        "Local Interface",
                        "Remote Switch",
                        "Remote Port",
                        "Port Description",
                        "Age",
                    ],
                    tablefmt="psql",
                )
            )
            print()
            print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Hosts: {len(set(row[0] for row in table))}")
            print(f"Neighbors: {len(table)}")

        if failed_hosts:
            print()
            logger.warning(
                f"Failed to query {len(failed_hosts)} host(s): {', '.join(failed_hosts)}"
            )


class Bgp(Command):
    def get_parser(self, prog_name):
        parser = super(Bgp, self).get_parser(prog_name)
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit selected hosts to an additional pattern",
        )
        parser.add_argument(
            "--afi",
            type=str,
            nargs="+",
            choices=[
                "ipv4Unicast",
                "ipv4Multicast",
                "ipv4Vpn",
                "ipv4Flowspec",
                "ipv6Unicast",
                "ipv6Multicast",
                "ipv6Vpn",
                "ipv6Flowspec",
                "l2VpnEvpn",
            ],
            help="Filter by address family (e.g. ipv4Unicast ipv6Unicast)",
        )
        return parser

    def take_action(self, parsed_args):
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        try:
            command = [
                "ansible-inventory",
                "-i",
                get_inventory_path("/ansible/inventory/hosts.yml"),
                "--list",
            ]
            if parsed_args.limit:
                command.extend(["--limit", parsed_args.limit])

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("Error loading inventory.")
                return 1
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return 1

        data = json.loads(result.stdout)
        hosts = get_hosts_from_inventory(data)

        if not hosts:
            logger.error("No hosts found in inventory.")
            return

        ssh_base = [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            "-o",
            "ConnectTimeout=10",
        ]
        bgp_command = 'sudo vtysh -c "show bgp summary json"'

        table = []
        failed_hosts = []

        for host in hosts:
            resolved_host = resolve_host_with_fallback(host)

            try:
                bgp_result = subprocess.run(
                    [
                        *ssh_base,
                        f"{settings.OPERATOR_USER}@{resolved_host}",
                        bgp_command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if bgp_result.returncode != 0:
                    logger.warning(
                        f"Failed to get BGP info from {host}: {bgp_result.stderr.strip()}"
                    )
                    failed_hosts.append(host)
                    continue

                bgp_data = json.loads(bgp_result.stdout)

                afi_filter = None
                if parsed_args.afi:
                    afi_filter = {a.lower() for a in parsed_args.afi}

                for afi, afi_data in bgp_data.items():
                    if afi_filter is not None and afi.lower() not in afi_filter:
                        continue
                    peers = afi_data.get("peers", {})
                    for peer_name, peer_data in peers.items():
                        table.append(
                            [
                                host,
                                afi,
                                peer_name,
                                peer_data.get("hostname", "n/a"),
                                peer_data.get("remoteAs", "n/a"),
                                peer_data.get("localAs", "n/a"),
                                peer_data.get("state", "n/a"),
                                peer_data.get("peerState", "n/a"),
                                peer_data.get("peerUptime", "n/a"),
                                peer_data.get("msgRcvd", 0),
                                peer_data.get("msgSent", 0),
                                peer_data.get("pfxRcd", 0),
                                peer_data.get("pfxSnt", 0),
                                peer_data.get("connectionsEstablished", 0),
                                peer_data.get("connectionsDropped", 0),
                            ]
                        )

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout connecting to {host}.")
                failed_hosts.append(host)
            except (ValueError, json.JSONDecodeError):
                logger.warning(f"Could not parse BGP info from {host}.")
                failed_hosts.append(host)

        if table:
            print(
                tabulate(
                    table,
                    headers=[
                        "Host",
                        "AFI",
                        "Peer",
                        "Remote Hostname",
                        "Remote AS",
                        "Local AS",
                        "State",
                        "Peer State",
                        "Uptime",
                        "Msg Rcvd",
                        "Msg Sent",
                        "Pfx Rcvd",
                        "Pfx Sent",
                        "Conn Est",
                        "Conn Drop",
                    ],
                    tablefmt="psql",
                )
            )
            print()
            print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Hosts: {len(set(row[0] for row in table))}")
            print(f"Sessions: {len(table)}")
            established = sum(1 for row in table if row[6] == "Established")
            print(f"Established: {established}/{len(table)}")

        if failed_hosts:
            print()
            logger.warning(
                f"Failed to query {len(failed_hosts)} host(s): {', '.join(failed_hosts)}"
            )


class Status(Command):
    def get_parser(self, prog_name):
        parser = super(Status, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            type=str,
            choices=["bootstrap"],
            help="Type of status to report",
        )
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit selected hosts to an additional pattern",
        )
        parser.add_argument(
            "--status",
            type=str,
            choices=["True", "False"],
            default=None,
            help="Filter by status value",
        )
        return parser

    def take_action(self, parsed_args):
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        try:
            command = [
                "ansible-inventory",
                "-i",
                get_inventory_path("/ansible/inventory/hosts.yml"),
                "--list",
            ]
            if parsed_args.limit:
                command.extend(["--limit", parsed_args.limit])

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("Error loading inventory.")
                return 1
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return 1

        data = json.loads(result.stdout)
        hosts = get_hosts_from_inventory(data)

        if not hosts:
            logger.error("No hosts found in inventory.")
            return

        ssh_base = [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            "-o",
            "ConnectTimeout=10",
        ]
        fact_command = "cat /etc/ansible/facts.d/osism.fact"

        section = parsed_args.type

        filter_status = parsed_args.status

        table = []
        failed_hosts = []

        for host in hosts:
            resolved_host = resolve_host_with_fallback(host)

            try:
                fact_result = subprocess.run(
                    [
                        *ssh_base,
                        f"{settings.OPERATOR_USER}@{resolved_host}",
                        fact_command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if fact_result.returncode != 0:
                    status = "False"
                    timestamp = "n/a"
                else:
                    config = configparser.ConfigParser()
                    config.read_string(fact_result.stdout)

                    status = config.get(section, "status", fallback="False")
                    timestamp = config.get(section, "timestamp", fallback="n/a")

                if filter_status and status != filter_status:
                    continue

                table.append([host, status, timestamp])

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout connecting to {host}.")
                failed_hosts.append(host)
            except (ValueError, configparser.Error):
                logger.warning(f"Could not parse {section} info from {host}.")
                failed_hosts.append(host)

        if table:
            print(
                tabulate(
                    table,
                    headers=["Host", "Status", "Timestamp"],
                    tablefmt="psql",
                )
            )
            print()
            print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Hosts: {len(table)}")

        if failed_hosts:
            print()
            logger.warning(
                f"Failed to query {len(failed_hosts)} host(s): {', '.join(failed_hosts)}"
            )


def _collect_hardware(parsed_args, requests):
    """Select the devices of a hardware report and query them.

    Returns:
        ``(targets, collection)``

    Raises:
        SelectionError: The selection failed or matched no device
    """
    if not ensure_known_hosts_file():
        logger.warning(
            f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
        )

    targets = select_targets(parsed_args, utils.nb)
    resolve_addresses(targets, resolve_host_with_fallback)

    collection = collect(
        targets,
        requests,
        parallel=parsed_args.parallel,
        timeout=parsed_args.timeout,
    )
    if parsed_args.dump_raw:
        paths = dump_raw(collection, parsed_args.dump_raw)
        logger.info(f"Wrote {len(paths)} raw document(s) to {parsed_args.dump_raw}")

    return targets, collection


def _fetch_netbox_interfaces(targets):
    """Return the NetBox interfaces per device ID, empty without NetBox."""
    device_ids = [target.device_id for target in targets if target.device_id]
    if not utils.nb or not device_ids:
        return {}
    try:
        return fetch_interfaces(utils.nb, device_ids)
    except Exception as exc:
        logger.warning(f"Could not load interfaces from NetBox: {exc}")
        return {}


def _warn_failed(failed):
    if failed:
        details = ", ".join(f"{item['name']} ({item['error']})" for item in failed)
        logger.warning(f"Failed to query {len(failed)} device(s): {details}")


def _matches_interface(patterns, *names):
    if not patterns:
        return True
    return any(
        fnmatch.fnmatchcase(name, pattern)
        for pattern in patterns
        for name in names
        if name
    )


TRANSCEIVER_COLUMNS = [
    Column("device_name", "Device"),
    Column("device_inventory_hostname", "Inventory Hostname", default=False),
    Column("device_kind", "Kind", default=False),
    Column("device_address", "Address", default=False),
    Column("device_site", "Site", default=False),
    Column("device_rack", "Rack", default=False),
    Column("device_role", "Role", default=False),
    Column("device_device_type", "Device Type", default=False),
    Column("device_manufacturer", "Manufacturer", default=False),
    Column("device_serial", "Device Serial", default=False),
    Column("device_system_vendor", "System Vendor", default=False),
    Column("device_system_model", "System Model", default=False),
    Column("device_hwsku", "HWSKU", default=False),
    Column("device_platform", "Platform", default=False),
    Column("device_asic", "ASIC", default=False),
    Column("device_os_version", "OS Version", default=False),
    Column("device_firmware_bios", "BIOS", default=False),
    Column("device_firmware_cpld", "CPLD", default=False),
    Column("device_firmware_onie", "ONIE", default=False),
    Column("interface_name", "Interface"),
    Column("interface_kind", "Port Kind", default=False),
    Column("interface_parent", "Parent", default=False),
    Column("interface_alias", "Alias", default=False),
    Column("interface_netbox_name", "NetBox Interface"),
    Column("interface_mapping", "Mapping"),
    Column("interface_netbox_peer_device", "NetBox Peer Device", default=False),
    Column("interface_netbox_peer_interface", "NetBox Peer Interface", default=False),
    Column("interface_lldp_neighbor", "LLDP Neighbor", default=False),
    Column("interface_lldp_neighbor_port", "LLDP Neighbor Port", default=False),
    Column("interface_admin_status", "Admin"),
    Column("interface_oper_status", "Oper"),
    Column("interface_speed", "Speed"),
    Column("interface_duplex", "Duplex", default=False),
    Column("interface_autoneg", "Autoneg", default=False),
    Column("interface_fec", "FEC", default=False),
    Column("interface_mtu", "MTU", default=False),
    Column("interface_mac", "MAC", default=False),
    Column("interface_permanent_mac", "Permanent MAC", default=False),
    Column("interface_port_type", "Port Type", default=False),
    Column("interface_bond", "Bond", default=False),
    Column("nic_pci_address", "PCI Address", default=False),
    Column("nic_vendor", "NIC Vendor", default=False),
    Column("nic_model", "NIC Model"),
    Column("nic_subsystem_vendor", "NIC Subsystem Vendor", default=False),
    Column("nic_subsystem_model", "NIC Subsystem Model", default=False),
    Column("nic_revision", "NIC Revision", default=False),
    Column("nic_serial", "NIC Serial", default=False),
    Column("nic_driver", "Driver", default=False),
    Column("nic_driver_version", "Driver Version", default=False),
    Column("nic_firmware_version", "NIC Firmware"),
    Column("transceiver_present", "Present", default=False),
    Column("transceiver_form_factor", "Form Factor"),
    Column("transceiver_connector", "Connector", default=False),
    Column("transceiver_vendor", "Vendor"),
    Column("transceiver_vendor_oui", "Vendor OUI", default=False),
    Column("transceiver_part_number", "Part Number"),
    Column("transceiver_serial", "Serial"),
    Column("transceiver_revision", "Revision"),
    Column("transceiver_date_code", "Date Code", default=False),
    Column("transceiver_firmware_active", "Firmware"),
    Column("transceiver_firmware_inactive", "Inactive Firmware", default=False),
    Column("transceiver_compliance", "Compliance", default=False),
    Column("transceiver_cable_length", "Cable Length", default=False),
    Column("transceiver_wavelength", "Wavelength", default=False),
    Column("transceiver_dom_temperature", "Temperature", default=False),
    Column("transceiver_dom_voltage", "Voltage", default=False),
    Column("transceiver_dom_lanes", "Lanes", default=False),
]

# Fields of an interface entry, in the order they appear in JSON
TRANSCEIVER_INTERFACE_FIELDS = [
    "name",
    "kind",
    "parent",
    "alias",
    "netbox_name",
    "mapping",
    "netbox_peer_device",
    "netbox_peer_interface",
    "lldp_neighbor",
    "lldp_neighbor_port",
    "admin_status",
    "oper_status",
    "speed",
    "duplex",
    "autoneg",
    "fec",
    "mtu",
    "mac",
    "permanent_mac",
    "port_type",
    "bond",
]


def _transceiver_device(target, document, netbox_interfaces, dom):
    """Build the report entry of one device from its collector document.

    Args:
        target: The device
        document: Raw document of the collector
        netbox_interfaces: All NetBox interfaces of the device
        dom: Include the diagnostic readings of the modules
    """
    # Management, virtual and LAG interfaces have no port with a cage
    documented = physical_interfaces(netbox_interfaces, include_mgmt=False)
    neighbours = {}

    if target.kind == KIND_SWITCH:
        system, ports = parse_sonic.parse_inventory(document, dom)
        index = sonic_name_index(
            target.device_id,
            target.name,
            target.hwsku or system.get("hwsku"),
            netbox_interfaces,
        )
        matches, unmatched = map_switch_ports(ports, documented, index)
    else:
        system, ports = parse_linux.parse_inventory(document, dom)
        try:
            neighbours = linux_neighbours(document)
        except LldpError as exc:
            # LLDP is a bonus in this report, a node without lldpd is fine
            logger.debug(f"{target.name}: no LLDP data: {exc}")
        matches, unmatched = map_node_ports(ports, documented, neighbours)

    interfaces = []
    for port in ports:
        match = matches[port["name"]]
        port["mapping"] = match.method
        if match.interface is not None:
            port["netbox_name"] = match.interface.name
            endpoints = match.interface.endpoints
            port["netbox_peer_device"] = (
                ", ".join(endpoint.device for endpoint in endpoints) or None
            )
            port["netbox_peer_interface"] = (
                ", ".join(endpoint.interface for endpoint in endpoints) or None
            )
        seen = neighbours.get(port["name"]) or []
        if seen:
            port["lldp_neighbor"] = seen[0]["system_name"] or seen[0]["chassis_id"]
            port["lldp_neighbor_port"] = seen[0]["port_id"]

        entry = {field: port.get(field) for field in TRANSCEIVER_INTERFACE_FIELDS}
        entry["nic"] = port.get("nic")
        entry["transceiver"] = port["transceiver"]
        interfaces.append(entry)

    device = target.describe()
    # What the device says about itself is more current than NetBox
    device["serial"] = system.get("serial") or device["serial"]
    device["system_vendor"] = system.get("system_vendor")
    device["system_model"] = system.get("system_model")
    if target.kind == KIND_SWITCH:
        for field in ("hwsku", "platform", "asic", "os_version", "firmware"):
            device[field] = system.get(field)
    device["interfaces"] = interfaces
    device["unmatched_netbox_interfaces"] = [interface.name for interface in unmatched]
    return device


class Transceiver(Command):
    """Report transceivers and NIC hardware of nodes and SONiC switches."""

    def get_parser(self, prog_name):
        parser = super(Transceiver, self).get_parser(prog_name)
        add_selection_arguments(parser)
        parser.add_argument(
            "--include-vf",
            action="store_true",
            help="Also report SR-IOV virtual functions",
        )
        parser.add_argument(
            "--include-infiniband",
            action="store_true",
            help="Also report InfiniBand ports",
        )
        parser.add_argument(
            "--interface",
            action="append",
            metavar="PATTERN",
            help="Only show ports whose name on the device or in NetBox matches the pattern (can be used multiple times)",
        )
        parser.add_argument(
            "--present",
            action="store_true",
            help="Only show ports with a module plugged in",
        )
        parser.add_argument(
            "--oper-status",
            choices=["up", "down"],
            help="Only show ports with this link state",
        )
        add_output_arguments(parser)
        parser.add_argument(
            "--dom",
            action="store_true",
            help="Include the diagnostic readings of the modules (temperature, voltage, optical power)",
        )
        add_collection_arguments(parser)
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with 1 when a device could not be queried",
        )
        return parser

    def take_action(self, parsed_args):
        try:
            columns = select_columns(
                TRANSCEIVER_COLUMNS, parsed_args.column, parsed_args.long
            )
        except RenderError as exc:
            logger.error(str(exc))
            return 1

        node_options = []
        if parsed_args.include_vf:
            node_options.append("--include-vf")
        if parsed_args.include_infiniband:
            node_options.append("--include-infiniband")
        switch_sections = ["ports", "transceiver", "system"]
        if parsed_args.dom:
            switch_sections.append("dom")
        requests = {
            # Reading the module EEPROM needs root
            KIND_NODE: Request(
                sections=["ports", "lldp", "ethtool", "module", "nic", "system"],
                options=node_options,
                sudo=True,
            ),
            KIND_SWITCH: Request(sections=switch_sections),
        }

        try:
            targets, collection = _collect_hardware(parsed_args, requests)
        except SelectionError as exc:
            logger.error(str(exc))
            return 1

        netbox_interfaces = _fetch_netbox_interfaces(targets)
        failed = list(collection.failed)
        devices = []
        for target in targets:
            document = collection.documents.get(target.name)
            if document is None:
                continue
            try:
                devices.append(
                    _transceiver_device(
                        target,
                        document,
                        netbox_interfaces.get(target.device_id) or [],
                        parsed_args.dom,
                    )
                )
            except Exception as exc:
                logger.debug(f"{target.name}: {type(exc).__name__}: {exc}")
                failed.append({"name": target.name, "error": "unparsable output"})

        for device in devices:
            device["interfaces"] = [
                interface
                for interface in device["interfaces"]
                if _matches_interface(
                    parsed_args.interface, interface["name"], interface["netbox_name"]
                )
                and (not parsed_args.present or interface["transceiver"]["present"])
                and (
                    not parsed_args.oper_status
                    or interface["oper_status"] == parsed_args.oper_status
                )
            ]

        if parsed_args.format == "json":
            document = {
                "generated_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "devices": devices,
                "failed": failed,
            }
            write_output(render_json(document), parsed_args.output)
        else:
            rows = []
            for device in devices:
                attributes = {
                    key: value
                    for key, value in device.items()
                    if key not in ("interfaces", "unmatched_netbox_interfaces")
                }
                for interface in device["interfaces"]:
                    port = {
                        key: value
                        for key, value in interface.items()
                        if key not in ("nic", "transceiver")
                    }
                    rows.append(
                        flatten(
                            {
                                "device": attributes,
                                "interface": port,
                                "nic": interface["nic"] or {},
                                "transceiver": interface["transceiver"],
                            }
                        )
                    )
            rows = sort_rows(rows, "device_name", "interface_name")

            if parsed_args.format == "csv":
                write_output(render_csv(rows, columns), parsed_args.output)
            elif rows:
                present = sum(1 for row in rows if row.get("transceiver_present"))
                footer = [
                    f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Devices: {len(devices)}",
                    f"Ports: {len(rows)}",
                    f"Modules present: {present}",
                ]
                write_output(render_table(rows, columns, footer), parsed_args.output)

            for device in devices:
                unmatched = device["unmatched_netbox_interfaces"]
                if unmatched:
                    logger.warning(
                        f"{device['name']}: {len(unmatched)} NetBox interface(s) "
                        f"without a live port: {', '.join(unmatched)}"
                    )

        _warn_failed(failed)
        if parsed_args.strict and failed:
            return 1
