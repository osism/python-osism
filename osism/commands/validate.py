# SPDX-License-Identifier: Apache-2.0

import argparse
import time

from cliff.command import Command
from loguru import logger

from osism.core.enums import VALIDATE_PLAYBOOKS
from osism.tasks import ansible, ceph, kolla
from osism.utils import redis


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "validator",
            nargs=1,
            type=str,
            help="Validator to run",
            choices=VALIDATE_PLAYBOOKS.keys(),
        )
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
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
            "--environment",
            default=None,
            help="Environment",
            type=str,
        ),
        parser.add_argument(
            "--timeout",
            default=300,
            type=int,
            help="Timeout to end if there is no output",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the validator run has been completed",
            action="store_true",
        )
        return parser

    def _handle_task(self, t, wait, format, timeout):
        rc = 0
        if wait:
            stoptime = time.time() + timeout
            last_id = 0
            while time.time() < stoptime:
                data = redis.xread(
                    {str(t.task_id): last_id}, count=1, block=(timeout * 1000)
                )
                if data:
                    stoptime = time.time() + timeout
                    messages = data[0]
                    for message_id, message in messages[1]:
                        last_id = message_id.decode()
                        message_type = message[b"type"].decode()
                        message_content = message[b"content"].decode()

                        logger.debug(
                            f"Processing message {last_id} of type {message_type}"
                        )
                        redis.xdel(str(t.task_id), message_id)

                        if message_type == "stdout":
                            print(message_content, end="")
                        elif message_type == "rc":
                            rc = int(message_content)
                        elif message_type == "action" and message_content == "quit":
                            redis.close()
                            return rc

        else:
            if format == "log":
                logger.info(
                    f"Task {t.task_id} is running in background. No more output. Check ARA for logs."
                )
            elif format == "script":
                print(f"{t.task_id}")

            return rc

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        environment = parsed_args.environment
        validator = parsed_args.validator[0]
        format = parsed_args.format
        timeout = parsed_args.timeout
        wait = not parsed_args.no_wait

        runtime = VALIDATE_PLAYBOOKS[validator]["runtime"]

        if "playbook" in VALIDATE_PLAYBOOKS[validator]:
            playbook = VALIDATE_PLAYBOOKS[validator]["playbook"]
        else:
            playbook = f"validate-{validator}"

        if runtime == "ceph-ansible":
            if not environment:
                environment = "ceph"
            t = ceph.run.delay(environment, playbook, arguments)
        elif runtime == "kolla-ansible":
            arguments.append("-e kolla_action=config_validate")
            if not environment:
                environment = "kolla"
            t = kolla.run.delay(environment, playbook, arguments)
        else:
            environment = VALIDATE_PLAYBOOKS[validator]["environment"]
            t = ansible.run.delay(environment, playbook, arguments)

        rc = self._handle_task(t, wait, format, timeout)

        return rc
