import subprocess

from cliff.command import Command


class Images(Command):
    def get_parser(self, prog_name):
        parser = super(Images, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-image-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--dry-run",
            default=False,
            help="Do not perform any changes",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter images with a regex on their name",
            default=None,
        )
        parser.add_argument(
            "--name",
            type=str,
            action="append",
            help="Name of the image to process, use repeatedly for multiple images",
        )

        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        filter = parsed_args.filter
        names = parsed_args.name
        dry_run = parsed_args.dry_run

        arguments = []
        if cloud:
            arguments.append(f"--cloud '{cloud}'")
        if filter:
            arguments.append(f"--filter '{filter}'")
        if dry_run:
            arguments.append("--dry-run")
        if names:
            for name in names:
                arguments.append(f"--name '{name}'")

        joined_arguments = " ".join(arguments)
        subprocess.call(
            f"/usr/local/bin/openstack-image-manager --images=/etc/images {joined_arguments}",
            shell=True,
            env={
                "OS_CLIENT_CONFIG_FILE": "/opt/configuration/environments/openstack/clouds.yml"
            },
        )
