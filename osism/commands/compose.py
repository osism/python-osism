# SPDX-License-Identifier: Apache-2.0

import argparse
import subprocess

from cliff.command import Command
from loguru import logger

from osism.utils.ssh import ensure_known_hosts_file, KNOWN_HOSTS_PATH


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        parser.add_argument("environment", nargs=1, type=str, help="Environment")
        parser.add_argument(
            "arguments",
            nargs=argparse.REMAINDER,
            help="Other arguments for Docker compose",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        environment = parsed_args.environment[0]
        arguments = "".join(parsed_args.arguments)

        # Ensure known_hosts file exists
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
            )

        ssh_command = (
            f"docker compose --project-directory=/opt/{environment} {arguments}"
        )
        ssh_options = f"-o StrictHostKeyChecking=no -o LogLevel=ERROR -o UserKnownHostsFile={KNOWN_HOSTS_PATH}"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(
            f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{host} '{ssh_command}'",
            shell=True,
        )
