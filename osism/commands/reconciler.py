import subprocess

from cliff.command import Command
from loguru import logger

from osism.tasks import reconciler


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
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        task = reconciler.run.delay()
        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)
