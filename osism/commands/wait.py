import logging

from celery import Celery
from celery.result import AsyncResult
from cliff.command import Command
from redis import Redis

from osism.tasks import Config


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('--live', default=False, help='Show live output from a started task until it is finished', action='store_true')
        parser.add_argument('--output', default=False, help='Show output from a finished task', action='store_true')
        parser.add_argument('task_id', nargs='+', type=str, help='ID of tasks to wait for')
        return parser

    def take_action(self, parsed_args):
        live = parsed_args.live
        output = parsed_args.output
        task_ids = parsed_args.task_id

        app = Celery('wait')
        app.config_from_object(Config)

        for task_id in task_ids:
            result = AsyncResult(f"{task_id}", app=app)

            if result.state == 'SUCCESS':
                if output:
                    print(result.get())

            elif result.state == 'STARTED' and live:
                redis = Redis(host="redis", port="6379")
                p = redis.pubsub()
                p.subscribe(f"{task_id}")

                while_True = True
                while while_True:
                    for m in p.listen():
                        if type(m["data"]) == bytes:
                            line = m["data"].decode("utf-8")
                            if line.startswith("RC: "):
                                rc = int(line[4:])
                                continue
                            elif line == "QUIT":
                                redis.close()

                                if len(task_ids) == 1:
                                    return rc
                                else:
                                    while_True = False
                            else:
                                print(line, end="")
