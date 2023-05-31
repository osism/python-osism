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
            p = redis.pubsub()
            p.subscribe(f"{t.task_id}")

            stoptime = time.time() + timeout
            while time.time() < stoptime:
                m = p.get_message(timeout=stoptime - time.time())
                if m:
                    stoptime = time.time() + timeout
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
                else:
                    logger.info(
                        f"No further output after {timeout} seconds. Therefore finish."
                    )
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
