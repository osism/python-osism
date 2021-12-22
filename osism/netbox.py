import argparse
import logging

from cliff.command import Command
import redis

from osism.tasks import ansible, reconciler


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('action', nargs=1, type=str, help='Action to be applied')
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Ansible')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the action has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        action = parsed_args.action[0]
        arguments = parsed_args.arguments
        wait = not parsed_args.no_wait

        if action == "sync":
            reconciler.sync_inventory_with_netbox.delay()
        else:
            ansible.run.delay("netbox", action, arguments)

            if wait:
                r = redis.Redis(host="redis", port="6379")
                p = r.pubsub()
                p.subscribe(f"netbox-{action}")

                while True:
                    for m in p.listen():
                        if type(m["data"]) == bytes:
                            if m["data"].decode("utf-8") == "QUIT":
                                r.close()
                                # NOTE: Use better solution
                                return
                            print(m["data"].decode("utf-8"), end="")
