# SPDX-License-Identifier: Apache-2.0

import argparse

from cliff.command import Command
from loguru import logger

from osism import utils


class _PassthroughParser(argparse.ArgumentParser):
    """Argument parser that forwards unrecognized arguments to Ansible.

    ``argparse.REMAINDER`` only starts capturing at the first *positional*
    token, but everything forwarded to Ansible here is option-like (``-e``,
    ``--limit``, ...) and there is no natural leading positional, so a
    remainder would reject exactly the arguments it exists to forward.
    Delegating ``parse_args()`` to ``parse_known_args()`` lets the parser
    consume only its own options and forward everything else verbatim,
    preserving order.
    """

    def parse_args(self, args=None, namespace=None):
        namespace, arguments = self.parse_known_args(args, namespace)
        namespace.arguments = arguments
        return namespace


class Sync(Command):
    def get_parser(self, prog_name):
        parser = _PassthroughParser(
            prog=prog_name,
            description=self.get_description(),
            allow_abbrev=False,
        )
        return parser

    def take_action(self, parsed_args):
        from osism.tasks import ansible, handle_task

        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        arguments = parsed_args.arguments

        t = ansible.run.delay(
            "manager", "configuration", arguments, auto_release_time=60
        )

        logger.info(
            f"Task {t.task_id} (sync configuration) was prepared for execution."
        )
        logger.info(
            f"It takes a moment until task {t.task_id} (sync configuration) has been started and output is visible here."
        )

        rc = handle_task(t, True, "log", 60)
        return rc
