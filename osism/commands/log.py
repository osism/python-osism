# SPDX-License-Identifier: Apache-2.0

import argparse
import json
import posixpath
import shlex
import subprocess

from cliff.command import Command
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
import requests

from osism import settings
from osism.utils.hosts import get_hosts_from_group, resolve_host_with_fallback
from osism.utils.ssh import (
    build_clush_command,
    build_ssh_command,
    ensure_known_hosts_file,
    KNOWN_HOSTS_PATH,
)


class Ansible(Command):
    def get_parser(self, prog_name):
        parser = super(Ansible, self).get_parser(prog_name)
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the ara command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        parameters = " ".join(parsed_args.parameter)
        subprocess.call(
            f"/usr/local/bin/ara {parameters}",
            shell=True,
        )


class Container(Command):
    def get_parser(self, prog_name):
        parser = super(Container, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        parser.add_argument(
            "container", nargs=1, type=str, help="Name of the container"
        )
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the docker logs command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        container_name = parsed_args.container[0]
        parameters = " ".join(parsed_args.parameter)

        # Ensure known_hosts file exists
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        remote_command = f"docker logs {parameters} {container_name}"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(build_ssh_command(host, remote_command=remote_command))


class File(Command):
    def get_parser(self, prog_name):
        parser = super(File, self).get_parser(prog_name)
        parser.add_argument(
            "host", nargs=1, type=str, help="Hostname, address, or inventory group"
        )
        parser.add_argument(
            "path",
            nargs=1,
            type=str,
            help="Path relative to /var/log (e.g. syslog, kern.log, kolla/nova/nova-compute.log)",
        )
        parser.add_argument(
            "--follow",
            "-f",
            default=False,
            action="store_true",
            help="Follow the log file in real-time (tail -f)",
        )
        parser.add_argument(
            "--lines",
            "-n",
            default=100,
            type=int,
            choices=range(1, 100001),
            metavar="LINES",
            help="Number of lines to show (1-100000, default: %(default)s)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        path = parsed_args.path[0]
        follow = parsed_args.follow
        lines = parsed_args.lines

        # Resolve the path relative to /var/log and prevent path traversal
        resolved = posixpath.normpath(posixpath.join("/var/log", path))
        if not resolved.startswith("/var/log/"):
            logger.error("Invalid path: must stay within /var/log")
            return 1

        # Ensure known_hosts file exists
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        # Build tail command
        tail_command = f"tail -n {lines}"
        if follow:
            tail_command += " -f"
        tail_command += f" {shlex.quote(resolved)}"

        # Check if host is an inventory group with multiple hosts
        group_hosts = get_hosts_from_group(host)

        if len(group_hosts) > 1:
            # Use clush for multi-node log tailing.
            # SSH options are configured in clush.conf.
            rc = subprocess.call(
                build_clush_command(hosts=group_hosts, remote_command=tail_command)
            )
            if rc != 0:
                logger.error(
                    "clush log tailing failed with return code %s for group '%s' (hosts: %s)",
                    rc,
                    host,
                    ",".join(group_hosts),
                )
                return rc
        else:
            if len(group_hosts) == 1:
                logger.info(f"Group '{host}' contains one host: {group_hosts[0]}")
                host = group_hosts[0]

            # Resolve hostname with DNS + Netbox fallback
            resolved_host = resolve_host_with_fallback(host)

            # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
            rc = subprocess.call(
                build_ssh_command(resolved_host, remote_command=tail_command)
            )
            if rc != 0:
                logger.error(
                    "ssh log tailing failed with return code %s for host '%s'",
                    rc,
                    resolved_host,
                )
                return rc

        return 0


class Opensearch(Command):
    def get_parser(self, prog_name):
        parser = super(Opensearch, self).get_parser(prog_name)
        parser.add_argument(
            "--verbose",
            default=False,
            help="Verbose output",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        session = PromptSession(history=FileHistory("/tmp/.opensearch.history"))
        verbose = parsed_args.verbose

        while True:
            query = session.prompt(">>> ")
            if query in ["Exit", "exit", "EXIT"]:
                break

            result = requests.post(
                f"{settings.OPENSEARCH_PROTOCOL}://{settings.OPENSEARCH_ADDRESS}:{settings.OPENSEARCH_PORT}/_plugins/_sql?format=json",
                data=json.dumps({"query": query}),
                headers={"content-type": "application/json"},
                verify=False,
            )
            data = result.json()
            if "hits" in data:
                for hit in data["hits"]["hits"]:
                    source = hit["_source"]
                    if verbose:
                        if "timestamp" not in source:
                            source["timestamp"] = source["@timestamp"]

                        if "programname" in source:
                            print(
                                f"{source['timestamp']} | {source['Hostname']} | {source['programname']} | {source['Payload']}"
                            )
                        else:
                            print(
                                f"{source['timestamp']} | {source['Hostname']} | {source['Payload']}"
                            )
                    else:
                        print(source["Payload"])
            else:
                print(data)
