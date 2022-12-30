import pprint
import subprocess

from cliff.command import Command
import json
from loguru import logger
from tabulate import tabulate

from osism.utils import redis


class Facts(Command):
    def get_parser(self, prog_name):
        parser = super(Facts, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname (as the host is known in Ansible inventory)",
        )
        parser.add_argument(
            "fact",
            nargs="?",
            type=str,
            help="Name of a fact to show",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            help="Do not use facts from the cache",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        fact = parsed_args.fact
        cache = not parsed_args.no_cache

        data = redis.get(f"ansible_facts{host}")
        if data:
            data = json.loads(data)
            table = []

            if fact:
                if fact in data:
                    row = pprint.pformat(data[fact], indent=2, width=60, compact=True)
                    table.append([host, fact, row])
                else:
                    logger.error(f"Fact {fact} not found in cache for {host}.")
            else:
                for fact in data:
                    row = pprint.pformat(data[fact], indent=2, width=60, compact=True)
                    if fact in [
                        "ansible_ssh_host_key_dsa_public",
                        "ansible_ssh_host_key_ecdsa_public",
                        "ansible_ssh_host_key_ed25519_public",
                        "ansible_ssh_host_key_rsa_public",
                    ]:
                        row = f"{row[0:40]}..."
                    table.append([host, fact, row])

            if table:
                print(
                    tabulate(table, headers=["Host", "Fact", "Value"], tablefmt="grid")
                )
        else:
            logger.error(f"No facts found in cache for {host}.")

        return


class Inventory(Command):
    def get_parser(self, prog_name):
        parser = super(Inventory, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname (as the host is known in Ansible inventory)",
        )
        parser.add_argument(
            "variable",
            nargs="?",
            type=str,
            help="Name of a variable to show",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        variable = parsed_args.variable

        try:
            result = subprocess.check_output(
                f"ansible-inventory -i /ansible/inventory/hosts.yml --host {host}",
                shell=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            logger.error(f"Host {host} not found in inventory.")
            return

        data = json.loads(result)
        table = []

        if variable:
            if variable in data:
                row = pprint.pformat(data[variable], indent=2, width=60, compact=True)
                table.append([host, variable, row])
            else:
                logger.error(f"Variable {variable} not found in inventory for {host}.")
        else:
            for variable in data:
                row = pprint.pformat(data[variable], indent=2, width=60, compact=True)
                table.append([host, variable, row])

        if table:
            print(
                tabulate(table, headers=["Host", "Variable", "Value"], tablefmt="grid")
            )

        return
