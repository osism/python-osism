import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        # NOTE: use python interface in the future, works for the moment
        p = subprocess.Popen("celery -A osism.tasks.reconciler worker -n reconciler --loglevel=INFO -Q reconciler", shell=True)
        p.wait()
