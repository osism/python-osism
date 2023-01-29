import argparse
import time

from celery import group
from celery.result import GroupResult
from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.core import enums
from osism.core.enums import MAP_ROLE2ENVIRONMENT
from osism.tasks import ansible, ceph, kolla
from osism.utils import redis


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--environment", type=str, help="Environment that is to be used explicitly"
        )
        parser.add_argument(
            "--action",
            "-a",
            dest="action",
            type=str,
            help="Action to be applied (can only be used for OpenStack playbooks) (default: %(default)s)",
            choices=[
                "deploy",
                "precheck",
                "pull",
                "reconfigure",
                "refresh-containers",
                "stop",
                "upgrade",
            ],
            default="deploy",
        )
        parser.add_argument("role", nargs="?", type=str, help="Role to be applied")
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
            "--timeout",
            default=300,
            type=int,
            help="Timeout to end if there is no output",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def _handle_loadbalancer(self, t, wait, format, timeout):
        # process the parent task
        rc = self._handle_task(t.parent, wait, format, timeout)

        # It is necessary to wait for all task even if this is not excpected by the
        # user because of the following exception thrown by the garbage collector.
        #
        # Exception ignored in: <function AsyncResult.__del__ at 0x7f8c91ac74c0>
        # Traceback (most recent call last):
        # [...]
        # ImportError: sys.meta_path is None, Python is likely shutting down

        if not wait:
            t.parent.get()

        # process the child tasks
        if format == "log":
            for c in t.children:
                logger.info(
                    f"Task {c.task_id} is running in background. No more output. Check ARA for logs."
                )

        # As explained above, it is neceesary to wait for all tasks.
        t.get()

        return rc

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

    def handle_role(self, arguments, environment, role, action, wait, format, timeout):
        if not environment:
            try:
                environment = enums.MAP_ROLE2ENVIRONMENT[role]
            except:  # noqa: E722
                environment = "custom"

        if environment == "ceph":
            if role.startswith("ceph-"):
                t = ceph.run.delay(role[5:], arguments)
            else:
                t = ceph.run.delay(role, arguments)
        elif environment == "kolla":
            kolla_arguments = [f"-e kolla_action={action}"] + arguments
            if role.startswith("kolla-"):
                t = kolla.run.delay(role[6:], kolla_arguments)
            else:
                t = kolla.run.delay(role, kolla_arguments)
        elif role == "loadbalancer-ng":
            g = group(
                kolla.run.si(playbook, arguments)
                for playbook in enums.LOADBALANCER_PLAYBOOKS
            )
            t = (kolla.run.s("loadbalancer-ng", arguments) | g).apply_async()
        else:
            t = ansible.run.delay(environment, role, arguments)

        if isinstance(t, GroupResult):
            rc = self._handle_loadbalancer(t, wait, format, timeout)
        else:
            rc = self._handle_task(t, wait, format, timeout)

        return rc

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        environment = parsed_args.environment
        action = parsed_args.action
        format = parsed_args.format
        role = parsed_args.role
        timeout = parsed_args.timeout
        wait = not parsed_args.no_wait

        rc = 0

        if not role:
            table = []
            for role in MAP_ROLE2ENVIRONMENT:
                table.append([role, MAP_ROLE2ENVIRONMENT[role]])
            logger.info(
                "No role given for execution. The roles listed in the table can be used."
            )
            print(tabulate(table, headers=["Role", "Environment"], tablefmt="psql"))
        elif role in enums.MAP_ROLE2ROLE:
            for r in enums.MAP_ROLE2ROLE[role]:
                rc = self.handle_role(
                    arguments, environment, action, r, wait, format, timeout
                )
                if rc != 0:
                    break
        else:
            rc = self.handle_role(
                arguments, environment, role, action, wait, format, timeout
            )

        return rc
