import argparse
import subprocess

from cliff.command import Command


class Images(Command):
    def get_parser(self, prog_name):
        parser = super(Images, self).get_parser(prog_name)
        parser.add_argument(
            "arguments",
            nargs=argparse.REMAINDER,
            type=str,
            help="Arguments to add (all arguments of the openstack-image-manager-command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        joined_arguments = " ".join(parsed_args.arguments)
        arguments = joined_arguments.replace("-- ", "")
        subprocess.call(
            f"/usr/local/bin/openstack-image-manager --images=/etc/images {arguments}",
            shell=True,
            env={
                "OS_CLIENT_CONFIG_FILE": "/opt/configuration/environments/openstack/clouds.yml"
            },
        )
