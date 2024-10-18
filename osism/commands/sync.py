# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command

from osism.tasks import ansible, handle_task


class Facts(Command):
    def get_parser(self, prog_name):
        parser = super(Facts, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        arguments = []
        t = ansible.run.delay(
            "generic", "gather-facts", arguments, auto_release_time=3600
        )
        rc = handle_task(t)
        return rc
