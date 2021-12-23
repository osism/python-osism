import logging
import time

from cliff.command import Command
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# from osism.tasks import reconciler


class Run(Command):

    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        event_handler = FileSystemEventHandler()
        event_handler.on_any_event = self.on_any_event
        observer = Observer()
        observer.schedule(event_handler, "/opt/configuration", recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    def on_any_event(self, event):
        pass
        # reconciler.run.delay()
