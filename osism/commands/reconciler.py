# SPDX-License-Identifier: Apache-2.0

import os
import subprocess

from cliff.command import Command
from loguru import logger

from osism.tasks import reconciler
from osism import utils


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
            default=os.environ.get("OSISM_TASK_TIMEOUT", 300),
            type=int,
            help="Timeout for a scheduled task that has not been executed yet",
        )
        parser.add_argument(
            "--flush-cache",
            default=False,
            help="Flush cache before running sync",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        task_timeout = parsed_args.task_timeout
        flush_cache = parsed_args.flush_cache

        t = reconciler.run.delay(publish=wait, flush_cache=flush_cache)
        if wait:
            logger.info(
                f"Task {t.task_id} (sync inventory) is running in background. Output coming soon."
            )
            try:
                return utils.fetch_task_output(t.id, timeout=task_timeout)
            except TimeoutError:
                logger.error(
                    f"Timeout while waiting for further output of task {t.task_id} (sync inventory)"
                )
        else:
            logger.info(
                f"Task {t.task_id} (sync inventory) is running in background. No more output."
            )
