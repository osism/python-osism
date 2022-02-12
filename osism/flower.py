# NOTE: will be removed in the future, use the service command from now on

import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        p = subprocess.Popen("celery --broker=redis://redis flower", shell=True)
        p.wait()
