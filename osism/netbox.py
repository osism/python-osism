import argparse
import logging

from cliff.command import Command
import redis

from osism.tasks import ansible, netbox, reconciler


class Run(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Ansible')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the role has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        pass


class Sync(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument('--no-wait', default=False, help='Do not wait until the sync has been completed', action='store_true')
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        reconciler.sync_inventory_with_netbox.delay()

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe("netbox-sync-inventory-with-netbox")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Init(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Init, self).get_parser(prog_name)
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Ansible')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the role has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        wait = not parsed_args.no_wait

        ansible.run.delay("netbox", "init", arguments)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe("netbox-init")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Import(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Import, self).get_parser(prog_name)
        parser.add_argument('--vendors', help='Vendors from which all available device types are to be imported', required=False)
        parser.add_argument(
            '--no-library',
            default=False,
            help='Do not import device types from the device type library, use the config repository',
            action='store_true'
        )
        parser.add_argument('--no-wait', default=False, help='Do not wait until the role has been applied', action='store_true')
        return parser

    def take_action(self, parsed_args):
        vendors = parsed_args.vendors
        wait = not parsed_args.no_wait
        library = not parsed_args.no_library

        netbox.import_device_types.delay(vendors, library)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe("netbox-import-device-types")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Manage(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
        parser.add_argument('--type', type=str, help='Type of the resource to manage', required=False, default='rack')
        parser.add_argument('name', nargs=1, type=str, help='Name of the resource to manage')
        parser.add_argument('arguments', nargs=argparse.REMAINDER, help='Other arguments for Ansible')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the changes have been made', action='store_true')
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait
        type_of_resource = parsed_args.type

        ansible.run.delay("netbox", f"{type_of_resource}-{name}", arguments)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe(f"netbox-{type_of_resource}-{name}")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Connect(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Connect, self).get_parser(prog_name)
        parser.add_argument('--type', type=str, help='Type of the resource to connect', required=False, default='rack')
        parser.add_argument('name', nargs=1, type=str, help='Name of the resource to connect')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the changes have been made', action='store_true')
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait
        type_of_resource = parsed_args.type

        netbox.connect.delay(name, type_of_resource)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe(f"netbox-connect-{type_of_resource}-{name}")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Disable(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Disable, self).get_parser(prog_name)
        parser.add_argument('name', nargs=1, type=str, help='Name of the device to check for unused interfaces')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the changes have been made', action='store_true')
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait

        netbox.disable.delay(name)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe(f"netbox-disable-{name}")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")


class Generate(Command):

    log = logging.getLogger(__name__)

    def get_parser(self, prog_name):
        parser = super(Generate, self).get_parser(prog_name)
        parser.add_argument('name', nargs=1, type=str, help='Name of the device to check for unused interfaces')
        parser.add_argument('--no-wait', default=False, help='Do not wait until the changes have been made', action='store_true')
        parser.add_argument('--template', type=str, help='Name of the template to use', required=False)
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        template = parsed_args.template
        wait = not parsed_args.no_wait

        netbox.generate.delay(name, template)

        if wait:
            r = redis.Redis(host="redis", port="6379")
            p = r.pubsub()

            # NOTE: use task_id or request_id in future
            p.subscribe(f"netbox-generate-{name}")

            while True:
                for m in p.listen():
                    if type(m["data"]) == bytes:
                        if m["data"].decode("utf-8") == "QUIT":
                            r.close()
                            # NOTE: Use better solution
                            return
                        print(m["data"].decode("utf-8"), end="")
