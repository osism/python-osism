# SPDX-License-Identifier: Apache-2.0

import subprocess

from cliff.command import Command
from loguru import logger


class OpenStackStress(Command):
    """Run OpenStack stress testing tool"""

    def get_parser(self, prog_name):
        parser = super(OpenStackStress, self).get_parser(prog_name)

        # Boolean flags
        parser.add_argument(
            "--no-cleanup",
            action="store_true",
            help="Do not clean up resources after test",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug mode",
        )
        parser.add_argument(
            "--no-delete",
            action="store_true",
            help="Do not delete resources",
        )
        parser.add_argument(
            "--no-volume",
            action="store_true",
            help="Do not create volumes",
        )
        parser.add_argument(
            "--no-boot-volume",
            action="store_true",
            help="Do not use boot volumes",
        )
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Do not wait for resources",
        )

        # Integer parameters with defaults
        parser.add_argument(
            "--interval",
            type=int,
            default=10,
            help="Interval in seconds (default: %(default)s)",
        )
        parser.add_argument(
            "--number",
            type=int,
            default=1,
            help="Number of instances (default: %(default)s)",
        )
        parser.add_argument(
            "--parallel",
            type=int,
            default=1,
            help="Parallel operations (default: %(default)s)",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=600,
            help="Timeout in seconds (default: %(default)s)",
        )
        parser.add_argument(
            "--volume-number",
            type=int,
            default=1,
            help="Number of volumes per instance (default: %(default)s)",
        )
        parser.add_argument(
            "--volume-size",
            type=int,
            default=1,
            help="Volume size in GB (default: %(default)s)",
        )
        parser.add_argument(
            "--boot-volume-size",
            type=int,
            default=20,
            help="Boot volume size in GB (default: %(default)s)",
        )

        # String parameters with defaults
        parser.add_argument(
            "--cloud",
            type=str,
            default="simple-stress",
            help="Cloud name in clouds.yaml (default: %(default)s)",
        )
        parser.add_argument(
            "--flavor",
            type=str,
            default="SCS-1V-2",
            help="Flavor name (default: %(default)s)",
        )
        parser.add_argument(
            "--image",
            type=str,
            default="Ubuntu 24.04",
            help="Image name (default: %(default)s)",
        )
        parser.add_argument(
            "--subnet-cidr",
            type=str,
            default="10.100.0.0/16",
            help="Subnet CIDR (default: %(default)s)",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="simple-stress",
            help="Resource name prefix (default: %(default)s)",
        )
        parser.add_argument(
            "--compute-zone",
            type=str,
            default="nova",
            help="Compute availability zone (default: %(default)s)",
        )
        parser.add_argument(
            "--storage-zone",
            type=str,
            default="nova",
            help="Storage availability zone (default: %(default)s)",
        )
        parser.add_argument(
            "--affinity",
            type=str,
            default="soft-anti-affinity",
            choices=[
                "soft-affinity",
                "soft-anti-affinity",
                "affinity",
                "anti-affinity",
            ],
            help="Server group policy (default: %(default)s)",
        )
        parser.add_argument(
            "--volume-type",
            type=str,
            default="__DEFAULT__",
            help="Volume type (default: %(default)s)",
        )

        return parser

    def take_action(self, parsed_args):
        """Execute the OpenStack stress testing tool"""

        # Build the command
        command = [
            "python3",
            "/openstack-simple-stress/openstack_simple_stress/main.py",
        ]

        # Add boolean flags
        if parsed_args.no_cleanup:
            command.append("--no-cleanup")
        if parsed_args.debug:
            command.append("--debug")
        if parsed_args.no_delete:
            command.append("--no-delete")
        if parsed_args.no_volume:
            command.append("--no-volume")
        if parsed_args.no_boot_volume:
            command.append("--no-boot-volume")
        if parsed_args.no_wait:
            command.append("--no-wait")

        # Add integer parameters
        command.extend(["--interval", str(parsed_args.interval)])
        command.extend(["--number", str(parsed_args.number)])
        command.extend(["--parallel", str(parsed_args.parallel)])
        command.extend(["--timeout", str(parsed_args.timeout)])
        command.extend(["--volume-number", str(parsed_args.volume_number)])
        command.extend(["--volume-size", str(parsed_args.volume_size)])
        command.extend(["--boot-volume-size", str(parsed_args.boot_volume_size)])

        # Add string parameters
        command.extend(["--cloud", parsed_args.cloud])
        command.extend(["--flavor", parsed_args.flavor])
        command.extend(["--image", parsed_args.image])
        command.extend(["--subnet-cidr", parsed_args.subnet_cidr])
        command.extend(["--prefix", parsed_args.prefix])
        command.extend(["--compute-zone", parsed_args.compute_zone])
        command.extend(["--storage-zone", parsed_args.storage_zone])
        command.extend(["--affinity", parsed_args.affinity])
        command.extend(["--volume-type", parsed_args.volume_type])

        logger.debug(
            f"Executing OpenStack stress test with command: {' '.join(command)}"
        )

        # Execute the stress tool
        try:
            result = subprocess.run(command, check=False)
            return result.returncode
        except FileNotFoundError:
            logger.error(
                "OpenStack stress tool not found at /openstack-simple-stress/openstack_simple_stress/main.py"
            )
            return 1
        except Exception as e:
            logger.error(f"Error executing OpenStack stress tool: {e}")
            return 1
