import argparse
import logging

from cliff.command import Command
from redis import Redis

from osism.tasks import ansible


redis = Redis(host="redis", port="6379")


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Arguments for Bifrost')
        return parser

    def take_action(self, parsed_args):
        task = ansible.run.delay("manager", "bifrost-command", parsed_args.arguments)

        self.log.info("Task is running. Wait. No more output. Check ARA for logs.")
        task.wait(timeout=None, interval=0.5)

        result = task.get()
        print(result)


class Deploy(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Deploy, self).get_parser(prog_name)
        parser.add_argument('--no-wait', default=False, help='Do not wait until the role has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        ansible.run.delay("manager", "bifrost-deploy", [])

        if wait:
            p = redis.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe("manager-bifrost-deploy")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            redis.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")
