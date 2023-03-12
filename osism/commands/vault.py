from cliff.command import Command
from prompt_toolkit import prompt

from osism.utils import redis


class Password(Command):
    def get_parser(self, prog_name):
        parser = super(Password, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        # NOTE: This is a first step to make Ansible Vault usable via OSISM workers.
        #       It's not ready in that form yet.
        ansible_vault_password = prompt("Ansible Vault password: ", is_password=True)
        redis.set("ansible_vault_password", ansible_vault_password)
