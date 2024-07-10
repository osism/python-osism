# SPDX-License-Identifier: Apache-2.0

import multiprocessing
import subprocess

from cliff.command import Command


class Run(Command):
    def get_parser(self, prog_name):
        if multiprocessing.cpu_count() <= 8:
            number_of_workers_default = multiprocessing.cpu_count()
        else:
            number_of_workers_default = 8

        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "--number-of-workers",
            "-n",
            default=number_of_workers_default,
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
        elif queue == "osism-kubernetes":
            tasks = "kubernetes"
            queue = "kubernetes"
        # kolla-ansible, ceph-ansible, osism-ansible
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
