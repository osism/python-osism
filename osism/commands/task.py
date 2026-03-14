# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command


class Revoke(Command):
    def get_parser(self, prog_name):
        parser = super(Revoke, self).get_parser(prog_name)
        parser.add_argument("task", nargs=1, type=str, help="Task to revoke")
        return parser

    def take_action(self, parsed_args):
        from celery import Celery
        from osism.tasks import Config

        task = parsed_args.task

        app = Celery("task")
        app.config_from_object(Config)
        app.control.revoke(task, terminate=True)
