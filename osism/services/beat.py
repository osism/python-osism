# NOTE: will be removed in the future, use the service command from now on

import logging
import subprocess

from cliff.command import Command


class Run(Command):

    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        ts = [
            "osism.tasks.ansible",
            "osism.tasks.ceph",
            "osism.tasks.conductor",
            "osism.tasks.kolla",
            "osism.tasks.netbox",
            "osism.tasks.reconciler"
        ]
        ps = [subprocess.Popen(f"celery -A {t} --broker=redis://redis beat -s /tmp/celerybeat-schedule-{t}.db", shell=True) for t in ts]

        for p in ps:
            p.wait()
