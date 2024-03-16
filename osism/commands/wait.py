# SPDX-License-Identifier: Apache-2.0

import time

from celery import Celery
from celery.result import AsyncResult
from cliff.command import Command
from loguru import logger
from redis import Redis
from osism import settings
from osism.tasks import Config


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--delay",
            default=1,
            type=int,
            help="Delay in second(s) between two task checks",
        )
        parser.add_argument(
            "--refresh",
            default=0,
            type=int,
            help="While waiting for all tasks refresh the list n times",
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
            "task_id", nargs="*", type=str, help="ID of tasks to wait for"
        )
        return parser

    def get_all_task_ids(self, i):
        task_ids = []
        for _, tasks in i.scheduled().items():
            for task in tasks:
                task_ids.append(task["id"])

        for _, tasks in i.active().items():
            for task in tasks:
                task_ids.append(task["id"])

        return sorted(task_ids)

    def take_action(self, parsed_args):
        delay = parsed_args.delay
        format = parsed_args.format
        live = parsed_args.live
        output = parsed_args.output
        refresh = parsed_args.refresh
        task_ids = sorted(parsed_args.task_id)

        do_refresh = False

        app = Celery("wait")
        app.config_from_object(Config)
        i = app.control.inspect()

        if not task_ids:
            logger.info("No task IDs specified, wait for all currently running tasks")
            task_ids = self.get_all_task_ids(i)
            do_refresh = True

        tmp_task_ids = []
        while task_ids or do_refresh:
            if task_ids:
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

                        tmp_task_ids.insert(0, task_id)

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
                        redis = Redis(
                            host=settings.REDIS_HOST,
                            port=settings.REDIS_PORT,
                            db=settings.REDIS_DB,
                            socket_keepalive=True,
                        )
                        redis.ping()

                        last_id = 0
                        while_True = True
                        while while_True:
                            data = redis.xread(
                                {str(task_id): last_id}, count=1, block=1000
                            )
                            if data:
                                messages = data[0]
                                for message_id, message in messages[1]:
                                    last_id = message_id.decode()
                                    message_type = message[b"type"].decode()
                                    message_content = message[b"content"].decode()

                                    logger.debug(
                                        f"Processing message {last_id} of type {message_type}"
                                    )
                                    redis.xdel(str(task_id), last_id)

                                    if message_type == "stdout":
                                        print(message_content, end="")
                                    elif message_type == "rc":
                                        rc = int(message_content)
                                    elif (
                                        message_type == "action"
                                        and message_content == "quit"
                                    ):
                                        redis.close()
                                        if len(task_ids) == 1:
                                            return rc
                                        else:
                                            while_True = False
                    else:
                        tmp_task_ids.insert(0, task_id)

                if not task_ids and tmp_task_ids:
                    logger.info(f"Wait {delay} second(s) until the next check")
                    time.sleep(delay)

                    if do_refresh:
                        task_ids = sorted(
                            list(set(self.get_all_task_ids(i) + tmp_task_ids))
                        )
                        tmp_task_ids = []
                    else:
                        task_ids = tmp_task_ids
            else:
                if refresh > 0:
                    refresh = refresh - 1
                    logger.info(
                        f"Wait {delay} second(s) until refresh of running tasks"
                    )
                    time.sleep(delay)
                    task_ids = self.get_all_task_ids(i)
                    tmp_task_ids = []
                else:
                    do_refresh = False
