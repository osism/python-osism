# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import json
import subprocess

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism import settings
from osism.commands.console import resolve_host_with_fallback
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
                return
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return

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
                return
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return

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
                return
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return

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

                for afi, afi_data in bgp_data.items():
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
