# SPDX-License-Identifier: Apache-2.0

import subprocess
import time

from cliff.command import Command
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

from osism.tasks import reconciler


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument("type", nargs=1, type=str, help="Type of the service")
        return parser

    def take_action(self, parsed_args):
        service = parsed_args.type[0]

        if service == "api":
            p = subprocess.Popen(
                "uvicorn osism.api:app --host 0.0.0.0 --port 8000", shell=True
            )
            p.wait()

        elif service == "listener":
            p = subprocess.Popen(
                "python3 -c 'from osism.services import listener; listener.main()'",
                shell=True,
            )
            p.wait()

        elif service == "beat":
            ts = [
                "osism.tasks.ansible",
                "osism.tasks.ceph",
                "osism.tasks.conductor",
                "osism.tasks.kolla",
                "osism.tasks.netbox",
                "osism.tasks.openstack",
                "osism.tasks.reconciler",
            ]
            ps = [
                subprocess.Popen(
                    f"celery -A {t} --broker=redis://redis beat -s /tmp/celerybeat-schedule-{t}.db",
                    shell=True,
                )
                for t in ts
            ]

            for p in ps:
                p.wait()

        elif service == "flower":
            p = subprocess.Popen(
                "celery --broker=redis://redis flower",
                shell=True,
            )
            p.wait()

        elif service == "reconciler":
            p = subprocess.Popen(
                "celery -A osism.tasks.reconciler worker -n reconciler --loglevel=INFO -Q reconciler",
                shell=True,
            )
            p.wait()

        elif service == "watchdog":
            event_handler_inventory = FileSystemEventHandler()
            event_handler_inventory.on_any_event = self.watchdog_inventory_on_any_event

            # We are not interested in being notified directly of any changes.
            # Therefore not the Inotify Observer but the Polling Observer. It
            # checks for changes every 10 seconds.

            observer = PollingObserver(10.0)
            observer.schedule(
                event_handler_inventory, "/opt/configuration/inventory", recursive=True
            )
            observer.start()

            try:
                while True:
                    time.sleep(1)
            finally:
                observer.stop()
                observer.join()

    def watchdog_inventory_on_any_event(self, event):
        reconciler.run.delay()
