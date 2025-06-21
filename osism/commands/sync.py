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
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        device_name = parsed_args.device

        task = conductor.sync_sonic.delay(device_name)
        if wait:
            if device_name:
                logger.info(
                    f"Task {task.task_id} (sync sonic for device {device_name}) is running. Wait. No more output."
                )
            else:
                logger.info(
                    f"Task {task.task_id} (sync sonic) is running. Wait. No more output."
                )
            task.wait(timeout=None, interval=0.5)
        else:
            if device_name:
                logger.info(
                    f"Task {task.task_id} (sync sonic for device {device_name}) is running in background. No more output."
                )
            else:
                logger.info(
                    f"Task {task.task_id} (sync sonic) is running in background. No more output."
                )
