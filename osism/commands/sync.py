# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger

from osism.tasks import ansible, conductor, handle_task


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


class Sonic(Command):
    def get_parser(self, prog_name):
        parser = super(Sonic, self).get_parser(prog_name)
        parser.add_argument(
            "device",
            nargs="?",
            help="Optional device name to sync configuration for a specific device",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--diff",
            default=True,
            help="Show configuration diff when changes are detected (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--no-diff",
            dest="diff",
            help="Do not show configuration diff",
            action="store_false",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        device_name = parsed_args.device
        show_diff = parsed_args.diff

        task = conductor.sync_sonic.delay(device_name, show_diff)

        if device_name:
            logger.info(
                f"Task {task.task_id} (sync sonic for device {device_name}) started"
            )
        else:
            logger.info(f"Task {task.task_id} (sync sonic) started")

        rc = handle_task(task, wait=wait)
        return rc
