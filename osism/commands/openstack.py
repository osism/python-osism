# SPDX-License-Identifier: Apache-2.0

import argparse
import subprocess

from cliff.command import Command
from loguru import logger


class _PassthroughParser(argparse.ArgumentParser):
    """Argument parser for a transparent OpenStack CLI passthrough.

    ``argparse.REMAINDER`` only starts capturing at the first *positional*
    token, so any OpenStack global option placed before the subcommand
    (``--os-interface``, ``--os-region-name``, ...) would be matched against
    this wrapper's own options and rejected. cliff calls ``parse_args()`` in
    ``App.run_subcommand``; delegating that to ``parse_known_args()`` lets the
    wrapper consume only its own options (``--cloud``) and forward everything
    else verbatim, preserving order.

    Note: cliff's *app-level* parser still consumes its own global options
    (``--debug``, ``-v``/``-q``, ``--log-file``) before this parser ever runs,
    so those cannot be forwarded to the OpenStack CLI.
    """

    def parse_args(self, args=None, namespace=None):
        namespace, arguments = self.parse_known_args(args, namespace)
        namespace.arguments = arguments
        return namespace


class Run(Command):
    """Run the OpenStack CLI against a configured cloud.

    Everything other than the ``--cloud`` selector is forwarded verbatim to
    the ``openstack`` CLI, including global options that precede the
    subcommand, e.g. ``osism openstack --os-region-name RegionOne server
    list``. Select the cloud profile with ``--cloud`` rather than
    ``--os-cloud``; the latter is injected automatically and rejected when
    passed through.
    """

    def get_parser(self, prog_name):
        # Build our own parser instead of super().get_parser(): we need the
        # _PassthroughParser class, allow_abbrev=False so a forwarded token
        # like "--clou" is not silently expanded to this wrapper's --cloud,
        # and add_help=False so -h/--help is forwarded to the OpenStack CLI.
        parser = _PassthroughParser(
            prog=prog_name,
            description=self.get_description(),
            add_help=False,
            allow_abbrev=False,
        )
        parser.add_argument(
            "--cloud",
            type=str,
            default="admin",
            help="Cloud name in clouds.yaml (default: %(default)s)",
        )
        return parser

    def take_action(self, parsed_args):
        from osism.tasks.openstack import get_cloud_helpers

        # The cloud profile is selected with --cloud; injecting it as
        # --os-cloud as well would be ambiguous and order-dependent. This is a
        # best-effort guard: it matches "--os-cloud"/"--os-cloud=" exactly and
        # does not catch an argparse-style abbreviation (e.g. "--os-clou") that
        # openstackclient might still expand downstream.
        if any(
            arg == "--os-cloud" or arg.startswith("--os-cloud=")
            for arg in parsed_args.arguments
        ):
            logger.error(
                "Do not pass '--os-cloud' through to the OpenStack CLI; "
                "use the '--cloud' option to select the cloud profile."
            )
            return 1

        setup_cloud_environment, _, cleanup_cloud_environment = get_cloud_helpers()

        _, temp_files, original_cwd, success = setup_cloud_environment(
            parsed_args.cloud
        )
        # setup_cloud_environment may have copied temp files and/or changed the
        # working directory before failing, so always clean up once it ran.
        try:
            if not success:
                logger.error(
                    f"Failed to set up cloud environment for '{parsed_args.cloud}'"
                )
                return 1

            command = ["openstack", "--os-cloud", parsed_args.cloud] + list(
                parsed_args.arguments
            )
            # Log only the leading subcommand tokens and an argument count: the
            # forwarded vector routinely carries secrets (e.g. 'user create
            # --password ...', '--secret ...') that must not end up in durable
            # debug logs.
            subcommand = []
            for arg in parsed_args.arguments:
                if arg.startswith("-"):
                    break
                subcommand.append(arg)
            logger.debug(
                "Running 'openstack {}' against cloud '{}' ({} argument(s))".format(
                    " ".join(subcommand) or "<no subcommand>",
                    parsed_args.cloud,
                    len(parsed_args.arguments),
                )
            )

            try:
                # No shell=True and command is a list, so the passed-through
                # arguments are exec'd directly without shell interpretation;
                # this is an intentional, transparent CLI passthrough.
                # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                result = subprocess.run(command, check=False)
                return result.returncode
            except FileNotFoundError:
                logger.error(
                    "OpenStack CLI ('openstack') not found. "
                    "Is python-openstackclient installed in the image?"
                )
                return 1
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
