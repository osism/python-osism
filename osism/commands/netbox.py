import argparse
from glob import glob
from os.path import basename

from cliff.command import Command
from loguru import logger
from redis import Redis
from tabulate import tabulate

from osism.tasks import conductor, netbox, reconciler, ansible, openstack


redis = Redis(host="redis", port="6379")


class Run(Command):
    def get_parser(self, prog_name):
        parser = super(Run, self).get_parser(prog_name)
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        pass


class Bifrost(Command):
    def get_parser(self, prog_name):
        parser = super(Bifrost, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        ansible.run.apply_async(
            ("manager", "bifrost-command", "baremetal node list -f json"),
            link=netbox.synchronize_device_state.s(),
        )


class Ironic(Command):
    def get_parser(self, prog_name):
        parser = super(Ironic, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        # Get Ironic parameters from the conductor
        task = conductor.get_ironic_parameters.delay()
        task.wait(timeout=None, interval=0.5)
        ironic_parameters = task.get()

        # Add all unregistered systems from the Netbox in Ironic
        netbox.get_devices_not_yet_registered_in_ironic.apply_async(
            (), link=openstack.baremetal_create_nodes.s(ironic_parameters)
        )

        # Synchronize the current status in Ironic with the Netbox
        # openstack.baremetal_node_list.apply_async((), link=netbox.synchronize_device_state.s())

        # Remove systems from Ironic that are no longer present in the Netbox


class Sync(Command):
    def get_parser(self, prog_name):
        parser = super(Sync, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        task = reconciler.sync_inventory_with_netbox.delay()
        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Init(Command):
    def get_parser(self, prog_name):
        parser = super(Init, self).get_parser(prog_name)
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        wait = not parsed_args.no_wait

        task = ansible.run.delay("netbox-local", "init", arguments)

        if wait:
            logger.info(
                f"Task {task.task_id} is running. Wait. No more output. Check ARA for logs."
            )
            task.wait(timeout=None, interval=0.5)


class Import(Command):
    def get_parser(self, prog_name):
        parser = super(Import, self).get_parser(prog_name)
        parser.add_argument(
            "--vendors",
            help="Vendors from which all available device types are to be imported",
            required=False,
        )
        parser.add_argument(
            "--library",
            default=False,
            help="Do import device types from the device type library",
            action="store_true",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the role has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        vendors = parsed_args.vendors
        wait = not parsed_args.no_wait

        task = netbox.import_device_types.delay(vendors, parsed_args.library)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Manage(Command):
    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
        parser.add_argument(
            "--type",
            type=str,
            help="Type of the resource to manage",
            required=False,
            default="rack",
        )
        parser.add_argument(
            "name", nargs="?", type=str, help="Name of the resource to manage"
        )
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        arguments = parsed_args.arguments
        name = parsed_args.name
        type_of_resource = parsed_args.type
        wait = not parsed_args.no_wait

        if not name:
            logger.info("No name of an object to be managed was given")
            table = []
            for playbook_type in ["rack"]:
                playbooks = glob(
                    f"/opt/configuration/netbox/playbooks/{playbook_type}-*.yml"
                )
                for playbook in playbooks:
                    name = basename(playbook)[len(playbook_type) + 1 : -4]  # noqa E203
                    table.append([playbook_type, name])

            print(tabulate(table, headers=["Type", "Name"], tablefmt="psql"))
        else:
            task = ansible.run.delay(
                "netbox-local", f"{type_of_resource}-{name}", arguments
            )

            if wait:
                logger.info(
                    f"Task {task.task_id} is running. Wait. No more output. Check ARA for logs."
                )
                task.wait(timeout=None, interval=0.5)


class Connect(Command):
    def get_parser(self, prog_name):
        parser = super(Connect, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Name of the resource (a collection or a device) to connect",
        )
        parser.add_argument(
            "--collection",
            type=str,
            help="Name of the collection to connect",
            required=False,
        ),
        parser.add_argument(
            "--device", type=str, help="Name of the device to connect", required=False
        )
        parser.add_argument(
            "--enforce",
            default=False,
            help="Ignore the current transition of a device",
            action="store_true",
        )
        parser.add_argument(
            "--state", type=str, help="State to use", default=None, required=False
        )
        parser.add_argument(
            "--type",
            type=str,
            default="collection",
            help="Type of the resource to connection (when not using --collection or --device)",
            required=False,
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name
        collection = parsed_args.device
        device = parsed_args.device
        state = parsed_args.state
        type_of_resource = parsed_args.type
        enforce = parsed_args.enforce

        task = None

        if name:
            if type_of_resource == "collection":
                task = netbox.data.delay(name, "", state)
            elif type_of_resource == "device":
                task = netbox.data.delay("", name, state)
        else:
            task = netbox.data.delay(collection, device, state)
            name = f"{collection}-{device}"

        task.wait(timeout=None, interval=0.5)
        data = task.get()

        for device in data:
            t = netbox.connect.delay(device, state, data, enforce)
            logger.info(
                f"Task {t.task_id} for device {device} is running in background"
            )
        logger.info(
            "Tasks are running in background. No more output. Check Flower for logs."
        )


class Disable(Command):
    def get_parser(self, prog_name):
        parser = super(Disable, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs=1,
            type=str,
            help="Name of the device to check for unused interfaces",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait

        task = netbox.disable.delay(name)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Generate(Command):
    def get_parser(self, prog_name):
        parser = super(Generate, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs=1,
            type=str,
            help="Name of the device for which the configuration is to be generated.",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        parser.add_argument(
            "--template", type=str, help="Name of the template to use", required=False
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        template = parsed_args.template
        wait = not parsed_args.no_wait

        task = netbox.generate.delay(name, template)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Deploy(Command):
    def get_parser(self, prog_name):
        parser = super(Deploy, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs=1,
            type=str,
            help="Name of the device for which the configuration is to be deployed",
        )
        parser.add_argument(
            "arguments", nargs=argparse.REMAINDER, help="Other arguments for Ansible"
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        # arguments = parsed_args.arguments
        wait = not parsed_args.no_wait

        task = netbox.deploy.delay(name)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Check(Command):
    def get_parser(self, prog_name):
        parser = super(Check, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs=1,
            type=str,
            help="Name of the device for which the configuration is to be checked",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait

        task = netbox.check.delay(name)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Diff(Command):
    def get_parser(self, prog_name):
        parser = super(Diff, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs=1,
            type=str,
            help="Name of the device for which the configuration is to be diffed",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the changes have been made",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name[0]
        wait = not parsed_args.no_wait

        task = netbox.diff.delay(name)

        if wait:
            logger.info(f"Task {task.task_id} is running. Wait. No more output.")
            task.wait(timeout=None, interval=0.5)


class Ping(Command):
    def get_parser(self, prog_name):
        parser = super(Ping, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        task = netbox.ping.delay()
        task.wait(timeout=None, interval=0.5)
        result = task.get()
        print(result)
