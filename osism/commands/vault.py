# SPDX-License-Identifier: Apache-2.0

# NOTE: This is a first step to make Ansible Vault usable via OSISM workers.
#       It's not ready in that form yet.

import os
import subprocess
import sys

from cliff.command import Command
from cryptography.fernet import Fernet
from prompt_toolkit import prompt

from osism.utils import redis


class SetPassword(Command):
    keyfile = "/share/ansible_vault_password.key"

    def get_parser(self, prog_name):
        parser = super(SetPassword, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        if os.path.isfile(self.keyfile):
            with open(self.keyfile, "r") as fp:
                key = fp.read()
        else:
            key = Fernet.generate_key()
            with open(self.keyfile, "w+") as fp:
                fp.write(key.decode("utf-8"))

        f = Fernet(key)

        # Check if password is being piped from STDIN
        if not sys.stdin.isatty():
            ansible_vault_password = sys.stdin.read().strip()
        else:
            ansible_vault_password = prompt(
                "Ansible Vault password: ", is_password=True
            )

        redis.set(
            "ansible_vault_password", f.encrypt(ansible_vault_password.encode("utf-8"))
        )


class UnsetPassword(Command):
    def get_parser(self, prog_name):
        parser = super(UnsetPassword, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        redis.delete("ansible_vault_password")


class View(Command):
    def get_parser(self, prog_name):
        parser = super(View, self).get_parser(prog_name)
        parser.add_argument(
            "path", nargs="?", type=str, help="Path to the secret.yml file"
        )
        return parser

    def take_action(self, parsed_args):
        path = parsed_args.path
        if not os.path.isabs(path):
            path = os.path.join("/opt/configuration", path)
        subprocess.call(f"/usr/local/bin/ansible-vault view {path}", shell=True)
