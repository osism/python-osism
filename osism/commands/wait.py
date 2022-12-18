import time

from celery import Celery
from celery.result import AsyncResult
from cliff.command import Command
from loguru import logger
from redis import Redis

from osism.tasks import Config


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--delay",
            default=1,
            type=int,
            help="Delay in seconds between two task checks",
        )
        parser.add_argument(
            "--live",
            default=False,
            help="Show live output from a started task until it is finished",
            action="store_true",
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        ),
        parser.add_argument(
            "--output",
            default=False,
            help="Show output from a finished task",
            action="store_true",
        )
        parser.add_argument(
            "task_id", nargs="+", type=str, help="ID of tasks to wait for"
        )
        return parser

    def take_action(self, parsed_args):
        delay = parsed_args.delay
        format = parsed_args.format
        live = parsed_args.live
        output = parsed_args.output
        task_ids = parsed_args.task_id

        app = Celery("wait")
        app.config_from_object(Config)
        i = app.control.inspect()

        while task_ids:
            time.sleep(delay)

            task_id = task_ids.pop()
            result = AsyncResult(f"{task_id}", app=app)

            if result.state == "PENDING":

                q = i.query_task(f"{task_id}")
                if not len([x for x in q.values() if len(x)]):
                    if format == "log":
                        logger.info(f"Task {task_id} is unavailable")
                    elif format == "script":
                        print(f"{task_id} = UNAVAILABLE")
                else:
                    if format == "log":
                        logger.info(f"Task {task_id} is in state PENDING")
                    elif format == "script":
                        print(f"{task_id} = PENDING")

                    task_ids.insert(0, task_id)

            elif result.state == "SUCCESS":

                if format == "log":
                    logger.info(f"Task {task_id} is in state SUCCESS")
                elif format == "script":
                    print(f"{task_id} = SUCCESS")

                if output:
                    print(result.get())

            elif result.state == "STARTED":

                if format == "log":
                    logger.info(f"Task {task_id} is in state STARTED")
                elif format == "script":
                    print(f"{task_id} = STARTED")

                if live:
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
                else:
                    task_ids.insert(0, task_id)
