import logging
import subprocess
# import time

from cliff.command import Command
# from watchdog.observers import Observer
# from watchdog.events import FileSystemEventHandler


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('type', nargs=1, type=str, help='Type of the service')
        return parser

    def take_action(self, parsed_args):
        service = parsed_args.type[0]

        if service == "api":
            p = subprocess.Popen("uvicorn osism.api:app --host 0.0.0.0 --port 8000", shell=True)
            p.wait()

        elif service == "listener":
            p = subprocess.Popen("python3 -c 'from osism import listener; listener.main()'", shell=True)
            p.wait()

        elif service == "beat":
            ts = [
                "osism.tasks.ansible",
                "osism.tasks.ceph",
                "osism.tasks.kolla",
                "osism.tasks.netbox",
                "osism.tasks.reconciler"
            ]
            ps = [subprocess.Popen(f"celery -A {t} --broker=redis://redis beat -s /tmp/celerybeat-schedule-{t}.db", shell=True) for t in ts]

            for p in ps:
                p.wait()

        elif service == "flower":
            p = subprocess.Popen("celery --broker=redis://redis flower", shell=True)
            p.wait()

        elif service == "watchdog":
            p = subprocess.Popen("sleep infinity", shell=True)
            p.wait()

            # event_handler = FileSystemEventHandler()
            # event_handler.on_any_event = self.on_any_event
            # observer = Observer()
            # observer.schedule(event_handler, "/opt/configuration", recursive=True)
            # observer.start()
            # try:
            #     while True:
            #         time.sleep(1)
            # finally:
            #     observer.stop()
            #     observer.join()

    def on_any_event(self, event):
        # reconciler.run.delay()
        pass
