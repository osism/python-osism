import subprocess

from cliff.command import Command


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument("type", nargs=1, type=str, help="Type of the worker")
        return parser

    def take_action(self, parsed_args):
        queue = parsed_args.type[0]

        if queue in ["openstack", "netbox", "conductor"]:
            tasks = queue
        else:
            tasks = queue[:-8]

        p = subprocess.Popen(
            f"celery -A osism worker -n {queue} --loglevel=INFO -Q {queue}",
            shell=True,
        )
        p.wait()
