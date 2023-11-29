# SPDX-License-Identifier: Apache-2.0

import argparse

from cliff.command import Command
from loguru import logger

from osism.tasks import ansible, handle_task


class Sync(Command):
    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments

        logger.info(
            "Task was prepared for execution. It takes a moment until the task has been started and output is visible here."
        )

        t = ansible.run.delay(
            "manager", "configuration", arguments, auto_release_time=60
        )
        rc = handle_task(t, True, format, 60)
        return rc
