# SPDX-License-Identifier: Apache-2.0

import subprocess

from cliff.command import Command


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--number-of-workers",
            "-n",
            default=16,
            type=int,
            help="Number of workers",
        )
        parser.add_argument("type", nargs=1, type=str, help="Type of the worker")
        return parser

    def take_action(self, parsed_args):
        queue = parsed_args.type[0]
        number_of_workers = parsed_args.number_of_workers

        if queue in ["openstack", "netbox", "conductor"]:
            tasks = queue
        else:
            tasks = queue[:-8]

        # NOTE: use python interface in the future, works for the moment
        if tasks == "osism":
            p = subprocess.Popen(
                f"celery -A osism.tasks.ansible worker -n {queue} --loglevel=INFO -Q {queue} -c {number_of_workers}",
                shell=True,
            )
        else:
            p = subprocess.Popen(
                f"celery -A osism.tasks.{tasks} worker -n {queue} --loglevel=INFO -Q {queue} -c {number_of_workers}",
                shell=True,
            )
        p.wait()
