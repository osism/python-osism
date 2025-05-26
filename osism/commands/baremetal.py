# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command

from loguru import logger
import openstack
from tabulate import tabulate
import json

from osism.commands import get_cloud_connection


class BaremetalList(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalList, self).get_parser(prog_name)
        parser.add_argument(
            "--provision-state",
            default=None,
            choices=["enroll", "managable", "available", "active", "error"],
            type=str,
            help="Only list nodes with the given provision state",
        )
        parser.add_argument(
            "--maintenance",
            default=False,
            action="store_true",
            help="Only list baremetal nodes in maintenance mode",
        )
        return parser

    def take_action(self, parsed_args):
        provision_state = parsed_args.provision_state
        maintenance = parsed_args.maintenance

        conn = get_cloud_connection()

        query = {}
        if provision_state:
            query.update(dict(provision_state=provision_state))
        if maintenance:
            query.update(dict(maintenance=maintenance))

        baremetal = conn.baremetal.nodes(**query)

        result = [
            [
                b["name"],
                b["power_state"],
                b["provision_state"],
                b["maintenance"],
            ]
            for b in baremetal
        ]

        print(
            tabulate(
                result,
                headers=[
                    "Name",
                    "Power State",
                    "Provision State",
                    "Maintenance",
                ],
                tablefmt="psql",
            )
        )


class BaremetalDeploy(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalDeploy, self).get_parser(prog_name)

        parser_exc_group = parser.add_mutually_exclusive_group(required=True)
        parser_exc_group.add_argument(
            "--all",
            default=False,
            help="Deploy all baremetal nodes in provision state available",
            action="store_true",
        )
        parser_exc_group.add_argument(
            "--name",
            default=[],
            help="Deploy given baremetal node when in provision state available. May be specified multiple times",
            action="append",
        )
        parser.add_argument(
            "--rebuild",
            default=False,
            help="Rebuild given nodes in active state",
            action="store_true",
        )
        parser.add_argument(
            "--yes-i-really-really-mean-it",
            default=False,
            help="Specify this in connection with '--rebuild --all' to actually rebuild all nodes",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        names = parsed_args.name
        rebuild = parsed_args.rebuild
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if all_nodes and rebuild and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to rebuild all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            deploy_nodes = list(conn.baremetal.nodes(details=True))
        else:
            deploy_nodes = [
                conn.baremetal.find_node(name, ignore_missing=True, details=True)
                for name in names
            ]

        for node_idx, node in enumerate(deploy_nodes):
            if not node:
                logger.warning(f"Could not find node {names[node_idx]}")
                continue

            if node.provision_state in ["available", "deploy failed"]:
                provision_state = "active"
            elif (
                node.provision_state == "error"
                or node.provision_state == "active"
                and rebuild
            ):
                provision_state = "rebuild"
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported provision state"
                )
                continue

            try:
                conn.baremetal.validate_node(
                    node.id, required=("boot", "deploy", "power")
                )
            except openstack.exceptions.ValidationException:
                logger.warning(f"Node {node.name} ({node.id}) could not be validated")
                continue
            try:
                config_drive = {"meta_data": {}}
                if (
                    "netplan_parameters" in node.extra
                    and node.extra["netplan_parameters"]
                ):
                    config_drive["meta_data"].update(
                        {
                            "netplan_parameters": json.loads(
                                node.extra["netplan_parameters"]
                            )
                        }
                    )
                if "frr_parameters" in node.extra and node.extra["frr_parameters"]:
                    config_drive["meta_data"].update(
                        {"frr_parameters": json.loads(node.extra["frr_parameters"])}
                    )
                conn.baremetal.set_node_provision_state(
                    node.id, provision_state, config_drive=config_drive
                )
            except Exception as exc:
                logger.warning(
                    f"Node {node.name} ({node.id}) could not be moved to active state: {exc}"
                )
                continue


class BaremetalUndeploy(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalUndeploy, self).get_parser(prog_name)

        parser_exc_group = parser.add_mutually_exclusive_group(required=True)
        parser_exc_group.add_argument(
            "--all",
            default=False,
            help="Undeploy all baremetal nodes",
            action="store_true",
        )
        parser_exc_group.add_argument(
            "--name",
            default=[],
            help="Undeploy given baremetal node. May be specified multiple times",
            action="append",
        )
        parser.add_argument(
            "--yes-i-really-really-mean-it",
            default=False,
            help="Specify this to actually undeploy all nodes",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        names = parsed_args.name
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if all_nodes and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to undeploy all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            deploy_nodes = list(conn.baremetal.nodes())
        else:
            deploy_nodes = [
                conn.baremetal.find_node(name, ignore_missing=True, details=False)
                for name in names
            ]

        for node_idx, node in enumerate(deploy_nodes):
            if not node:
                logger.warning(f"Could not find node {names[node_idx]}")
                continue

            if node.provision_state in ["active", "deploy failed", "error"]:
                try:
                    conn.baremetal.set_node_provision_state(node.id, "undeploy")
                except Exception as exc:
                    logger.warning(
                        f"Node {node.name} ({node.id}) could not be moved to available state: {exc}"
                    )
                    continue
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported provision state"
                )
