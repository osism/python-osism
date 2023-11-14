# SPDX-License-Identifier: Apache-2.0

import subprocess
import time

from cliff.command import Command
from loguru import logger

from osism.tasks import reconciler
from osism.utils import redis


class Run(Command):
    def take_action(self, parsed_args):
        logger.info(
            "The osism reconciler command is deprecated and will be removed. Use osism service reconciler."
        )
        # NOTE: use python interface in the future, works for the moment
        p = subprocess.Popen(
            "celery -A osism.tasks.reconciler worker -n reconciler --loglevel=INFO -Q reconciler",
            shell=True,
        )
        p.wait()


class Sync(Command):
    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--task-timeout",
            default=3600,
            type=int,
            help="Timeout for a scheduled task that has not been executed yet",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        task_timeout = parsed_args.task_timeout

        t = reconciler.run.delay(publish=wait)
        if wait:
            logger.info(
                f"Task {t.task_id} is running in background. Output coming soon."
            )
            rc = 0
            stoptime = time.time() + task_timeout
            last_id = 0
            while time.time() < stoptime:
                data = redis.xread(
                    {str(t.task_id): last_id}, count=1, block=(300 * 1000)
                )
                if data:
                    stoptime = time.time() + task_timeout
                    messages = data[0]
                    for message_id, message in messages[1]:
                        last_id = message_id.decode()
                        message_type = message[b"type"].decode()
                        message_content = message[b"content"].decode()

                        logger.debug(
                            f"Processing message {last_id} of type {message_type}"
                        )
                        redis.xdel(str(t.task_id), last_id)

                        if message_type == "stdout":
                            print(message_content, end="")
                        elif message_type == "rc":
                            rc = int(message_content)
                        elif message_type == "action" and message_content == "quit":
                            redis.close()
                            return rc
        else:
            logger.info(f"Task {t.task_id} is running in background. No more output.")
