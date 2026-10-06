# SPDX-License-Identifier: Apache-2.0

import argparse
import subprocess

from cliff.command import Command
from loguru import logger

STRESS_TOOL = "/openstack-simple-stress/openstack_simple_stress/main.py"


class _PassThroughParser(argparse.ArgumentParser):
    """Keep every argument this parser does not know for the stress tool."""

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        parsed, extra = self.parse_known_args(args, namespace)
        if "--" in extra:
            extra.remove("--")
        # Credentials are set up for parsed.cloud; a second --cloud would make
        # the tool run against a cloud whose credentials were never prepared.
        if any(a == "--cloud" or a.startswith("--cloud=") for a in extra):
            self.error("--cloud must come before '--'")
        parsed.tool_args = extra
        return parsed


class OpenStackStress(Command):
    """Run the OpenStack stress testing tool (openstack-simple-stress).

    All options except --cloud are passed to the tool unchanged. Options that
    the osism CLI itself uses (--debug, -h/--help, -v, -q, --version,
    --log-file) must follow a "--": e.g. "osism openstack stress -- --help"
    shows the tool's own options.
    """

    def get_parser(self, prog_name):
        parser = _PassThroughParser(
            prog=prog_name,
            description=self.get_description(),
            add_help=False,
        )
        parser.add_argument(
            "--cloud",
            default="simple-stress",
            help="Cloud name in clouds.yaml (default: %(default)s)",
        )
        return parser

    def take_action(self, parsed_args):
        """Execute the OpenStack stress testing tool"""

        from osism.tasks.openstack import get_cloud_helpers

        setup_cloud_environment, _, cleanup_cloud_environment = get_cloud_helpers()

        _, temp_files, original_cwd, success = setup_cloud_environment(
            parsed_args.cloud
        )
        if not success:
            logger.error(
                f"Failed to set up cloud environment for '{parsed_args.cloud}'"
            )
            return 1

        command = [
            "python3",
            STRESS_TOOL,
            "--cloud",
            parsed_args.cloud,
            *parsed_args.tool_args,
        ]

        logger.debug(
            f"Executing OpenStack stress test with command: {' '.join(command)}"
        )

        try:
            result = subprocess.run(command, check=False)
            return result.returncode
        except FileNotFoundError:
            logger.error(f"OpenStack stress tool not found at {STRESS_TOOL}")
            return 1
        except Exception as e:
            logger.error(f"Error executing OpenStack stress tool: {e}")
            return 1
        finally:
            cleanup_cloud_environment(temp_files, original_cwd)
