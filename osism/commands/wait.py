import logging

from cliff.command import Command
from redis import Redis

redis = Redis(host="redis", port="6379")


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('task_id', nargs=1, type=str, help='Task ID')
        return parser

    def take_action(self, parsed_args):
        task_id = parsed_args.task_id[0]

        p = redis.pubsub()
        p.subscribe(f"{task_id}")

        while True:
            for m in p.listen():
                if type(m["data"]) == bytes:
                    line = m["data"].decode("utf-8")
                    if line.startswith("RC: "):
                        rc = int(line[4:])
                        continue
                    if line == "QUIT":
                        redis.close()
                        # NOTE: Use better solution
                        return rc
                    print(line, end="")
