# SPDX-License-Identifier: Apache-2.0

import argparse
import os
import subprocess

from cliff.command import Command
from loguru import logger

from osism.data.enums import VALIDATE_PLAYBOOKS
from osism.tasks import ansible, ceph, kolla
from osism.tasks.openstack import cleanup_cloud_environment, setup_cloud_environment
from osism import utils


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

    def _handle_task(self, t, wait, format, timeout, playbook):
        if wait:
            try:
                return utils.fetch_task_output(t.id, timeout=timeout)
            except TimeoutError:
                logger.error(
                    f"Timeout while waiting for further output of task {t.task_id} (sync inventory)"
                )
        else:
            if format == "log":
                logger.info(
                    f"Task {t.task_id} (validate {playbook}) is running in background. No more output. Check ARA for logs."
                )
            elif format == "script":
                print(f"{t.task_id}")

            return 0

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

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

        rc = self._handle_task(t, wait, format, timeout, playbook)

        return rc


class Scs(Command):
    def get_parser(self, prog_name):
        parser = super(Scs, self).get_parser(prog_name)
        parser.add_argument(
            "--cloud",
            default="admin",
            type=str,
            help="Cloud name in clouds.yaml (default: %(default)s)",
        )
        parser.add_argument(
            "--version",
            default="v5.1",
            type=str,
            help="SCS version to check against (default: %(default)s)",
        )
        parser.add_argument(
            "--tests",
            default=None,
            type=str,
            help="Regex filter for test IDs (e.g. 'scs-0100|scs-0103')",
        )
        parser.add_argument(
            "--output",
            default=None,
            type=str,
            help="Path for YAML report output",
        )
        parser.add_argument(
            "--verbose",
            default=False,
            action="store_true",
            help="Verbose output",
        )
        parser.add_argument(
            "--debug",
            default=False,
            action="store_true",
            help="Debug logging",
        )
        parser.add_argument(
            "--sections",
            default=None,
            type=str,
            help="Comma-separated list of sections to check",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud

        password, temp_files, original_cwd, success = setup_cloud_environment(cloud)
        if not success:
            return 1

        try:
            command = [
                "python3",
                "/scs-tests/scs-compliance-check.py",
                "-s",
                cloud,
                "-a",
                f"os_cloud={cloud}",
                "-V",
                parsed_args.version,
            ]

            if parsed_args.verbose:
                command.append("-v")
            if parsed_args.debug:
                command.append("--debug")
            if parsed_args.tests:
                command.extend(["-t", parsed_args.tests])
            if parsed_args.output:
                command.extend(["-o", parsed_args.output])
            if parsed_args.sections:
                command.extend(["-S", parsed_args.sections])

            command.append("scs-compatible-iaas.yaml")

            env = os.environ.copy()
            env["OS_CLIENT_CONFIG_FILE"] = "/tmp/clouds.yaml"

            logger.debug(
                f"Executing SCS compliance check with command: {' '.join(command)}"
            )

            try:
                result = subprocess.run(
                    command, cwd="/scs-tests/", env=env, check=False
                )
                return result.returncode
            except FileNotFoundError:
                logger.error(
                    "SCS compliance check tool not found at /scs-tests/scs-compliance-check.py"
                )
                return 1
            except Exception as e:
                logger.error(f"Error executing SCS compliance check: {e}")
                return 1
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
