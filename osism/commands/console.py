# SPDX-License-Identifier: Apache-2.0

import shlex
import subprocess

from cliff.command import Command
from loguru import logger
from prompt_toolkit import prompt

from osism.utils.hosts import (  # noqa: F401
    resolve_hostname_to_ip,
    get_primary_ipv4_from_netbox,
    resolve_host_with_fallback,
    get_hosts_from_group,
    select_host_from_list,
)
from osism.utils.ssh import (
    build_clush_command,
    build_ssh_command,
    ensure_known_hosts_file,
    KNOWN_HOSTS_PATH,
)


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--type",
            default="ssh",
            choices=["ansible", "clush", "container", "ssh"],
            help="Type of the console (default: %(default)s)",
        )
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname, address, or inventory group of the console to connect",
        )
        return parser

    def take_action(self, parsed_args):
        type_console = parsed_args.type
        host = parsed_args.host[0]

        # Ensure known_hosts file exists
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        # If certain characters are contained in the hostname, then
        # enforce a certain console type.

        # ctl001/
        if host.endswith("/"):
            type_console = "container_prompt"
        # ctl001/rabbitmq
        elif "/" in host:
            type_console = "container"
        # .ctl001
        elif host.startswith("."):
            type_console = "ansible"
            host = host[1:]
        # :ctl00[1-3]
        elif host.startswith(":"):
            type_console = "clush"
            host = host[1:]

        if type_console == "ansible":
            subprocess.call(["/run-ansible-console.sh", host])
        elif type_console == "clush":
            subprocess.call(build_clush_command(group=host))
        elif type_console == "ssh":
            # Try to resolve as an inventory group
            group_hosts = get_hosts_from_group(host)
            if len(group_hosts) == 1:
                logger.info(f"Group '{host}' contains one host: {group_hosts[0]}")
                host = group_hosts[0]
            elif len(group_hosts) > 1:
                selected = select_host_from_list(group_hosts)
                if not selected:
                    return
                host = selected

            # Resolve hostname with Netbox fallback
            resolved_host = resolve_host_with_fallback(host)
            # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
            subprocess.call(build_ssh_command(resolved_host))
        elif type_console == "container_prompt":
            while True:
                command = prompt(f"{host[:-1]}>>> ")
                if command in ["Exit", "exit", "EXIT"]:
                    break

                ssh_command = f"docker {shlex.quote(command)}"
                # Resolve hostname with Netbox fallback
                resolved_host = resolve_host_with_fallback(host[:-1])
                # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
                subprocess.call(
                    build_ssh_command(resolved_host, remote_command=ssh_command)
                )
        elif type_console == "container":
            target_containername = host.split("/")[1]
            target_host = host.split("/")[0]
            target_command = "bash"

            ssh_command = f"docker exec -it {shlex.quote(target_containername)} {shlex.quote(target_command)}"

            # Resolve hostname with Netbox fallback
            resolved_target_host = resolve_host_with_fallback(target_host)
            # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
            subprocess.call(
                build_ssh_command(
                    resolved_target_host,
                    remote_command=ssh_command,
                    request_tty=True,
                )
            )
