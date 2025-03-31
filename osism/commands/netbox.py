# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger

from osism.tasks import conductor, netbox, reconciler, openstack, handle_task


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


class Manage(Command):
    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the management of the netbox has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--no-netbox-wait",
            default=False,
            help="Do not wait for the netbox API to be ready",
            action="store_true",
        )
        parser.add_argument(
            "--parallel",
            type=str,
            default=None,
            help="Process up to n files in parallel",
        )
        parser.add_argument(
            "--limit",
            type=str,
            default=None,
            help="Limit files by prefix",
        )
        parser.add_argument(
            "--skipdtl",
            default=False,
            help="Skip devicetype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipmtl",
            default=False,
            help="Skip moduletype library",
            action="store_true",
        )
        parser.add_argument(
            "--skipres",
            default=False,
            help="Skip resources",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        arguments = []

        if parsed_args.no_netbox_wait:
            arguments.append("--no-wait")
        else:
            arguments.append("--wait")

        if parsed_args.parallel:
            arguments.append("--parallel")
            arguments.append(parsed_args.parallel)

        if parsed_args.limit:
            arguments.append("--limit")
            arguments.append(parsed_args.limit)

        if parsed_args.skipdtl:
            arguments.append("--skipdtl")
        else:
            arguments.append("--no-skipdtl")

        if parsed_args.skipmtl:
            arguments.append("--skipmtl")
        else:
            arguments.append("--no-skipmtl")

        if parsed_args.skipres:
            arguments.append("--skipres")
        else:
            arguments.append("--no-skipres")

        task_signature = netbox.manage.si(*arguments)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (netbox-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Ping(Command):
    def get_parser(self, prog_name):
        parser = super(Ping, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        task = netbox.ping.delay()
        task.wait(timeout=None, interval=0.5)
        result = task.get()
        print(result)
