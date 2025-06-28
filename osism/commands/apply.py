# SPDX-License-Identifier: Apache-2.0

import argparse
import os

from celery import chain, group
from celery.result import GroupResult
from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism.data import enums
from osism.data.playbooks import MAP_ROLE2ENVIRONMENT, MAP_ROLE2RUNTIME
from osism.tasks import ansible, ceph, kolla, kubernetes, handle_task


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--environment",
            "-e",
            type=str,
            help="Environment that is to be used explicitly",
        )
        parser.add_argument(
            "--overwrite",
            type=str,
            help="Overwrite the environment after the mapping on the worker (has no effect on ceph and kolla environments)",
        )
        parser.add_argument(
            "--sub",
            type=str,
            help="Use a sub-environment (e.g. zone-a or zone-b)",
        )
        parser.add_argument(
            "--action",
            "-a",
            dest="action",
            type=str,
            help="Action to be applied (can only be used for OpenStack playbooks) (default: %(default)s)",
            choices=[
                "bootstrap",
                "config",
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
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        ),
        parser.add_argument(
            "--retry",
            "-r",
            default=os.environ.get("OSISM_APPLY_RETRY", 0),
            type=int,
            help="Retry the play up to x times if it has failed",
        )
        parser.add_argument(
            "--timeout",
            default=os.environ.get("OSISM_TASK_TIMEOUT", 300),
            type=int,
            help="Timeout to end if there is no output",
        )
        parser.add_argument(
            "--task-timeout",
            default=3600,
            type=int,
            help="Timeout for a scheduled task that has not been executed yet",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        parser.add_argument(
            "--dry-run",
            default=False,
            help="Dry run, do not initiate tasks (for collections only)",
            action="store_true",
        )
        parser.add_argument("role", nargs="?", type=str, help="Role to be applied")
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        return parser

    def handle_loadbalancer_task(self, t, wait, format, timeout):
        # process the parent task
        rc = handle_task(t.parent, wait, format, timeout)

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
                    f"Task {c.task_id} (loadbalancer) is running in background. No more output. Check ARA for logs."
                )

        # As explained above, it is neceesary to wait for all tasks.
        t.get()

        return rc

    def _handle_collection(
        self,
        data,
        counter,
        arguments,
        environment,
        overwrite,
        sub,
        collection,
        action,
        wait,
        format,
        timeout,
        task_timeout,
        retry,
        dry_run,
    ):
        g = []
        for item in data:
            # e.g. ["loadbalancer", ["mariadb"]]
            if type(item) == list:
                # e.g. "loadbalancer"
                logger.info(f"A [{counter}] {'-' * (counter + 1)} {item[0]}")

                if dry_run:
                    pt = ansible.noop.si()
                else:
                    pt = self._prepare_task(
                        arguments,
                        environment,
                        overwrite,
                        sub,
                        item[0],
                        action,
                        wait,
                        format,
                        timeout,
                        task_timeout,
                    )

                if len(item) > 1 and type(item[1]) == list:
                    logger.debug(f"X [{counter + 1}] --> {item[1]}")
                    st = self._handle_collection(
                        item[1],
                        counter + 1,
                        arguments,
                        environment,
                        overwrite,
                        sub,
                        collection,
                        action,
                        wait,
                        format,
                        timeout,
                        task_timeout,
                        retry,
                        dry_run,
                    )
                    g.append(chain(pt, st))
                else:
                    g.append(pt)
                    for inner_item in item[1:]:
                        if type(inner_item) == list:
                            logger.info(
                                f"B [{counter}] {'-' * (counter + 1)} {inner_item[0]}"
                            )

                            if dry_run:
                                pt = ansible.noop.si()
                            else:
                                pt = self._prepare_task(
                                    arguments,
                                    environment,
                                    overwrite,
                                    sub,
                                    inner_item[0],
                                    action,
                                    wait,
                                    format,
                                    timeout,
                                    task_timeout,
                                )

                            if len(inner_item) > 1 and type(inner_item[1]) == list:
                                logger.debug(f"X [{counter + 1}] --> {inner_item[1]}")
                                st = self._handle_collection(
                                    inner_item[1],
                                    counter + 1,
                                    arguments,
                                    environment,
                                    overwrite,
                                    sub,
                                    collection,
                                    action,
                                    wait,
                                    format,
                                    timeout,
                                    task_timeout,
                                    retry,
                                    dry_run,
                                )
                                g.append(chain(pt, st))
                            else:
                                g.append(pt)
                        else:
                            logger.info(
                                f"C [{counter}] {'-' * (counter + 1)} {inner_item}"
                            )
                            g.append(
                                self._prepare_task(
                                    arguments,
                                    environment,
                                    overwrite,
                                    sub,
                                    inner_item,
                                    action,
                                    wait,
                                    format,
                                    timeout,
                                    task_timeout,
                                )
                            )
            # e.g. "common"
            else:
                logger.info(f"D [{counter}] {'-' * (counter + 1)} {item}")
                g.append(
                    self._prepare_task(
                        arguments,
                        environment,
                        overwrite,
                        sub,
                        item,
                        action,
                        wait,
                        format,
                        timeout,
                        task_timeout,
                    )
                )

        if g:
            return group(g)

    def handle_collection(
        self,
        arguments,
        environment,
        overwrite,
        sub,
        collection,
        action,
        wait,
        format,
        timeout,
        task_timeout,
        retry,
        dry_run,
    ):
        if dry_run:
            logger.info(f"Dry run for collection {collection}. No tasks are scheduled.")
        else:
            logger.info(f"Collection {collection} is prepared for execution")

        t = self._handle_collection(
            enums.MAP_ROLE2ROLE[collection],
            0,
            arguments,
            environment,
            overwrite,
            sub,
            collection,
            action,
            wait,
            format,
            timeout,
            task_timeout,
            retry,
            dry_run,
        )
        if t:
            t.apply_async()
        if not dry_run:
            logger.info(
                f"All tasks of the collection {collection} are prepared for execution"
            )
            logger.info("Tasks are running in the background")

    def _prepare_task(
        self,
        arguments,
        environment,
        overwrite,
        sub,
        role,
        action,
        wait,
        format,
        timeout,
        task_timeout,
    ):
        # There is a special playbook ceph-ceph which should be called
        # with ceph. Therefore, the environment is set explicitly in
        # this case.
        if role == "ceph":
            environment = "ceph"

        if not environment:
            try:
                environment = MAP_ROLE2ENVIRONMENT[role]
            except:  # noqa: E722
                environment = "custom"

        if environment == "ceph":
            if sub:
                environment = f"{environment}.{sub}"
            if role.startswith("ceph-"):
                t = ceph.run.si(
                    environment, role[5:], arguments, auto_release_time=task_timeout
                )
            else:
                t = ceph.run.si(
                    environment, role, arguments, auto_release_time=task_timeout
                )
        elif environment == "kubernetes":
            if sub:
                environment = f"{environment}.{sub}"
            t = kubernetes.run.si(
                environment, role, arguments, auto_release_time=task_timeout
            )
        elif role == "loadbalancer-ng":
            if sub:
                environment = f"{environment}.{sub}"
            g = group(
                kolla.run.si(
                    environment, playbook, arguments, auto_release_time=task_timeout
                )
                for playbook in enums.LOADBALANCER_PLAYBOOKS
            )
            t = (
                kolla.run.si(
                    environment,
                    "loadbalancer-ng",
                    arguments,
                    auto_release_time=task_timeout,
                )
                | g
            )
        elif environment == "kolla":
            if sub:
                environment = f"{environment}.{sub}"

            if role.startswith("kolla-"):
                role = role[6:]

            if role in ["mariadb-ng", "rabbitmq-ng"]:
                kolla_arguments = [f"-e kolla_action_ng={action}"] + arguments
            else:
                kolla_arguments = [f"-e kolla_action={action}"] + arguments

            if (
                role not in ["common"]
                and "osism-ansible" in MAP_ROLE2RUNTIME
                and role in MAP_ROLE2RUNTIME["osism-ansible"]
            ):
                t = ansible.run.si(
                    environment, role, arguments, auto_release_time=task_timeout
                )
            else:
                t = kolla.run.si(
                    environment, role, kolla_arguments, auto_release_time=task_timeout
                )
        else:
            # Overwrite the environment
            if overwrite:
                environment = overwrite

            if environment in ["custom"] or role not in MAP_ROLE2ENVIRONMENT:
                logger.info(f"Trying to run play {role} in environment {environment}")

            t = ansible.run.si(
                environment, role, arguments, auto_release_time=task_timeout
            )

        return t

    def handle_role(
        self,
        arguments,
        environment,
        overwrite,
        sub,
        role,
        action,
        wait,
        format,
        timeout,
        task_timeout,
    ):
        t = self._prepare_task(
            arguments,
            environment,
            overwrite,
            sub,
            role,
            action,
            wait,
            format,
            timeout,
            task_timeout,
        )
        task = t.apply_async()

        logger.info(f"Task {task.task_id} ({role}) was prepared for execution.")

        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} ({role}) has been started and output is visible here."
            )

        if isinstance(task, GroupResult):
            rc = self.handle_loadbalancer_task(task, wait, format, timeout)
        else:
            rc = handle_task(task, wait, format, timeout)

        return rc

    def take_action(self, parsed_args):
        action = parsed_args.action
        arguments = parsed_args.arguments
        environment = parsed_args.environment
        format = parsed_args.format
        overwrite = parsed_args.overwrite
        role = parsed_args.role
        sub = parsed_args.sub
        retry = parsed_args.retry
        timeout = parsed_args.timeout
        task_timeout = parsed_args.task_timeout
        wait = not parsed_args.no_wait
        dry_run = parsed_args.dry_run

        rc = 0

        if not role:
            table = []
            for role in MAP_ROLE2ENVIRONMENT:
                table.append([role, MAP_ROLE2ENVIRONMENT[role]])
            logger.info(
                "No role given for execution. The roles listed in the table can be used."
            )
            print(tabulate(table, headers=["Role", "Environment"], tablefmt="psql"))

        else:
            for role in role.split("//"):
                outer_break = False
                if role in enums.MAP_ROLE2ROLE:
                    rc = self.handle_collection(
                        arguments,
                        environment,
                        overwrite,
                        sub,
                        role,
                        action,
                        wait,
                        format,
                        timeout,
                        task_timeout,
                        retry,
                        dry_run,
                    )
                    if rc != 0:
                        outer_break = True
                else:
                    for i in range(0, retry + 1):
                        rc = self.handle_role(
                            arguments,
                            environment,
                            overwrite,
                            sub,
                            role,
                            action,
                            wait,
                            format,
                            timeout,
                            task_timeout,
                        )
                        if rc != 0 and i == retry:
                            outer_break = True
                            break
                        elif rc == 0:
                            break
                if outer_break:
                    break

        return rc
