# SPDX-License-Identifier: Apache-2.0

import argparse

from cliff.command import Command
from loguru import logger
from redis import Redis
from osism import settings
from osism.tasks import ansible


redis = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
redis.ping()


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Arguments for Bifrost"
        )
        return parser

    def take_action(self, parsed_args):
        task = ansible.run.delay("manager", "bifrost-command", parsed_args.arguments)

        task.wait(timeout=None, interval=0.5)

        result = task.get()
        print(result)


class Deploy(Command):
    def get_parser(self, prog_name):
        parser = super(Deploy, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        t = ansible.run.delay("manager", "bifrost-deploy", [])
        logger.info(
            f"Task {t.task_id} is running in background. No more output. Check ARA for logs."
        )
