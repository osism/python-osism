# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import json
import subprocess

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.commands.console import resolve_host_with_fallback
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
                "/ansible/inventory/hosts.yml",
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
        hosts = sorted(data.get("_meta", {}).get("hostvars", {}).keys())

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
                    [*ssh_base, f"dragon@{resolved_host}", dmidecode_command],
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
                    [*ssh_base, f"dragon@{resolved_host}", uuid_command],
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
