# SPDX-License-Identifier: Apache-2.0

import os
import subprocess

from cliff.command import Command
from loguru import logger
import yaml

from osism.tasks import conductor, netbox, handle_task
from osism import utils


class Ironic(Command):
    def get_parser(self, prog_name):
        parser = super(Ironic, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--task-timeout",
            default=os.environ.get("OSISM_TASK_TIMEOUT", 300),
            type=int,
            help="Timeout for a scheduled task that has not been executed yet",
        )
        parser.add_argument(
            "--force-update",
            help="Force update of baremetal nodes (Used to update non-comparable items like passwords)",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        task_timeout = parsed_args.task_timeout

        task = conductor.sync_ironic.delay(force_update=parsed_args.force_update)
        if wait:
            logger.info(
                f"Task {task.task_id} (sync ironic) is running in background. Output comming soon."
            )
            try:
                return utils.fetch_task_output(task.id, timeout=task_timeout)
            except TimeoutError:
                logger.error(
                    f"Timeout while waiting for further output of task {task.task_id} (sync ironic)"
                )
        else:
            logger.info(
                f"Task {task.task_id} (sync ironic) is running in background. No more output."
            )


class Sync(Command):
    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        task = conductor.sync_netbox.delay()
        if wait:
            logger.info(
                f"Task {task.task_id} (sync netbox) is running. Wait. No more output."
            )
            task.wait(timeout=None, interval=0.5)


class Manage(Command):
    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the management of the NetBox has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--no-netbox-wait",
            default=False,
            help="Do not wait for the NetBox API to be ready",
            action="store_true",
        )
        parser.add_argument(
            "--parallel",
            type=str,
            default=None,
            help="Process up to n files in parallel",
        )
        parser.add_argument(
            "--limit",
            type=str,
            default=None,
            help="Limit files by prefix",
        )
        parser.add_argument(
            "--skipdtl",
            default=False,
            help="Skip devicetype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipmtl",
            default=False,
            help="Skip moduletype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipres",
            default=False,
            help="Skip resources",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        arguments = ["run"]

        if parsed_args.no_netbox_wait:
            arguments.append("--no-wait")
        else:
            arguments.append("--wait")

        if parsed_args.parallel:
            arguments.append("--parallel")
            arguments.append(parsed_args.parallel)

        if parsed_args.limit:
            arguments.append("--limit")
            arguments.append(parsed_args.limit)

        if parsed_args.skipdtl:
            arguments.append("--skipdtl")
        else:
            arguments.append("--no-skipdtl")

        if parsed_args.skipmtl:
            arguments.append("--skipmtl")
        else:
            arguments.append("--no-skipmtl")

        if parsed_args.skipres:
            arguments.append("--skipres")
        else:
            arguments.append("--no-skipres")

        task_signature = netbox.manage.si(*arguments)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (netbox-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Versions(Command):
    def get_parser(self, prog_name):
        parser = super(Versions, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        task = netbox.ping.delay()
        task.wait(timeout=None, interval=0.5)
        result = task.get()
        print(result)


class Console(Command):
    def get_parser(self, prog_name):
        parser = super(Console, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            nargs=1,
            choices=["info", "search", "filter", "shell"],
            help="Type of the console (default: %(default)s)",
        )
        parser.add_argument(
            "arguments", nargs="*", type=str, default="", help="Additional arguments"
        )

        return parser

    def take_action(self, parsed_args):
        type_console = parsed_args.type[0]
        arguments = " ".join(
            [f"'{item}'" if " " in item else item for item in parsed_args.arguments]
        )

        home_dir = os.path.expanduser("~")
        nbcli_dir = os.path.join(home_dir, ".nbcli")
        if not os.path.exists(nbcli_dir):
            os.mkdir(nbcli_dir)

        nbcli_file = os.path.join(nbcli_dir, "user_config.yml")
        if not os.path.exists(nbcli_file):
            try:
                with open("/run/secrets/NETBOX_TOKEN", "r") as fp:
                    token = fp.read().strip()
            except FileNotFoundError:
                token = None

            url = os.environ.get("NETBOX_API", None)

            if not token or not url:
                logger.error("NetBox integration not configured.")
                return

            subprocess.call(
                ["/usr/local/bin/nbcli", "init"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.remove(nbcli_file)

            nbcli_config = {
                "pynetbox": {
                    "url": url,
                    "token": token,
                },
                "requests": {"verify": False},
                "nbcli": {"filter_limit": 50},
                "user": {},
            }
            with open(nbcli_file, "w") as fp:
                yaml.dump(nbcli_config, fp, default_flow_style=False)

        subprocess.call(f"/usr/local/bin/nbcli {type_console} {arguments}", shell=True)
