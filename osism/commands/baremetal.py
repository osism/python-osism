# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from argparse import BooleanOptionalAction

import tempfile
import os
import subprocess
import threading
from loguru import logger
import openstack
from tabulate import tabulate
import json
import yaml
from openstack.baremetal import configdrive as configdrive_builder

from osism.commands import get_cloud_connection
from osism import utils
from osism.tasks.conductor.netbox import get_nb_device_query_list_ironic
from osism.tasks import netbox
from osism.utils.ssh import cleanup_ssh_known_hosts_for_node


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

        result = []
        for b in baremetal:
            # Get device role from NetBox
            device_role = "N/A"
            if utils.nb:
                try:
                    # Try to find device by name first
                    device = utils.nb.dcim.devices.get(name=b["name"])

                    # If not found by name, try by inventory_hostname custom field
                    if not device:
                        devices = utils.nb.dcim.devices.filter(
                            cf_inventory_hostname=b["name"]
                        )
                        if devices:
                            device = list(devices)[0]

                    # Get device role
                    if device and device.role and hasattr(device.role, "name"):
                        device_role = device.role.name
                except Exception as e:
                    logger.debug(f"Could not get device role for {b['name']}: {e}")

            result.append(
                [
                    b["name"],
                    device_role,
                    b["power_state"] if b["power_state"] is not None else "n/a",
                    b["provision_state"],
                    b["maintenance"],
                ]
            )

        result.sort(key=lambda x: x[0])

        print(
            tabulate(
                result,
                headers=[
                    "Name",
                    "Device Role",
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

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Deploy given baremetal node when in provision state available",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Deploy all baremetal nodes in provision state available",
            action="store_true",
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
        name = parsed_args.name
        rebuild = parsed_args.rebuild
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        if all_nodes and rebuild and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to rebuild all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            deploy_nodes = list(conn.baremetal.nodes(details=True))
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            deploy_nodes = [node]

        for node in deploy_nodes:
            if not node:
                continue

            if (
                node.provision_state in ["available", "deploy failed"]
                and not node["maintenance"]
            ):
                provision_state = "active"
            elif (
                node.provision_state == "error"
                or node.provision_state == "active"
                and not node["maintenance"]
                and rebuild
            ):
                provision_state = "rebuild"
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported state! Provision state: {node.provision_state}, maintenance mode: {node['maintenance']}"
                )
                continue

            # NOTE: Ironic removes "instance_info" on undeploy. It was saved to "extra" during sync and needs to be refreshed here.
            if (
                "instance_info" in node
                and not node["instance_info"]
                and "instance_info" in node["extra"]
                and node["extra"]["instance_info"]
            ):
                node = conn.baremetal.update_node(
                    node, instance_info=json.loads(node.extra["instance_info"])
                )

            try:
                conn.baremetal.validate_node(
                    node.id, required=("boot", "deploy", "power")
                )
            except openstack.exceptions.ValidationException:
                logger.warning(f"Node {node.name} ({node.id}) could not be validated")
                continue
            # NOTE: Prepare osism config drive
            try:
                # Get default vars from NetBox local_context_data if available
                default_vars = {}
                if utils.nb:
                    try:
                        # Try to find device by name first
                        device = utils.nb.dcim.devices.get(name=node.name)

                        # If not found by name, try by inventory_hostname custom field
                        if not device:
                            devices = utils.nb.dcim.devices.filter(
                                cf_inventory_hostname=node.name
                            )
                            if devices:
                                device = devices[0]

                        # Extract local_context_data if device found and has the field
                        if (
                            device
                            and hasattr(device, "local_context_data")
                            and device.local_context_data
                        ):
                            default_vars = device.local_context_data
                            logger.info(
                                f"Using NetBox local_context_data for node {node.name}"
                            )
                        else:
                            logger.debug(
                                f"No local_context_data found for node {node.name} in NetBox"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch NetBox data for node {node.name}: {e}"
                        )

                playbook = []
                play = {
                    "name": "Run bootstrap",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "vars": default_vars.copy(),
                    "roles": [
                        "osism.commons.hostname",
                        "osism.commons.hosts",
                        "osism.commons.operator",
                    ],
                    "tasks": [
                        {
                            "name": "Restart rsyslog service after hostname change",
                            "ansible.builtin.systemd": {
                                "name": "rsyslog",
                                "state": "restarted",
                            },
                        }
                    ],
                }
                play["vars"].update(
                    {"hostname_name": node.name, "hosts_type": "template"}
                )
                if (
                    "netplan_parameters" in node.extra
                    and node.extra["netplan_parameters"]
                ):
                    play["vars"].update(
                        {
                            "network_allow_service_restart": True,
                        }
                    )
                    play["vars"].update(json.loads(node.extra["netplan_parameters"]))
                    play["roles"].append("osism.commons.network")
                if "frr_parameters" in node.extra and node.extra["frr_parameters"]:
                    play["vars"].update(
                        {
                            "frr_dummy_interface": "loopback0",
                        }
                    )
                    play["vars"].update(json.loads(node.extra["frr_parameters"]))
                    play["roles"].append("osism.services.frr")
                playbook.append(play)
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with open(os.path.join(tmp_dir, "playbook.yml"), "w") as file:
                        yaml.dump(
                            playbook,
                            file,
                            default_flow_style=False,
                            explicit_start=True,
                            indent=2,
                            sort_keys=False,
                        )
                    config_drive = configdrive_builder.pack(tmp_dir)
            except Exception as exc:
                logger.warning(
                    f"Failed to build config drive for {node.name} ({node.id}): {exc}"
                )
                continue
            try:
                conn.baremetal.set_node_provision_state(
                    node.id, provision_state, config_drive=config_drive
                )
            except Exception as exc:
                logger.warning(
                    f"Node {node.name} ({node.id}) could not be moved to active state: {exc}"
                )
                continue


class BaremetalDump(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalDump, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            type=str,
            help="Dump deployment playbook for given baremetal node",
        )
        parser.add_argument(
            "--ironic",
            default=False,
            action="store_true",
            help="Fetch data from Ironic instead of NetBox (shows actual deployment state)",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name
        use_ironic = parsed_args.ironic

        try:
            if use_ironic:
                # Fetch data from Ironic (shows actual deployment state)
                conn = get_cloud_connection()
                node = conn.baremetal.find_node(name, ignore_missing=True, details=True)

                if not node:
                    logger.error(f"Could not find node {name} in Ironic")
                    return

                # Get default vars from NetBox local_context_data if available
                default_vars = {}
                if utils.nb:
                    try:
                        # Try to find device by name first
                        device = utils.nb.dcim.devices.get(name=node.name)

                        # If not found by name, try by inventory_hostname custom field
                        if not device:
                            devices = utils.nb.dcim.devices.filter(
                                cf_inventory_hostname=node.name
                            )
                            if devices:
                                device = devices[0]

                        # Extract local_context_data if device found and has the field
                        if (
                            device
                            and hasattr(device, "local_context_data")
                            and device.local_context_data
                        ):
                            default_vars = device.local_context_data
                            logger.info(
                                f"Using NetBox local_context_data for node {node.name}"
                            )
                        else:
                            logger.debug(
                                f"No local_context_data found for node {node.name} in NetBox"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch NetBox data for node {node.name}: {e}"
                        )

                playbook = []
                play = {
                    "name": "Run bootstrap",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "vars": default_vars.copy(),
                    "roles": [
                        "osism.commons.hostname",
                        "osism.commons.hosts",
                        "osism.commons.operator",
                    ],
                    "tasks": [
                        {
                            "name": "Restart rsyslog service after hostname change",
                            "ansible.builtin.systemd": {
                                "name": "rsyslog",
                                "state": "restarted",
                            },
                        }
                    ],
                }
                play["vars"].update(
                    {"hostname_name": node.name, "hosts_type": "template"}
                )

                # Get netplan_parameters from Ironic node extra (JSON string, needs parsing)
                if (
                    "netplan_parameters" in node.extra
                    and node.extra["netplan_parameters"]
                ):
                    play["vars"].update(
                        {
                            "network_allow_service_restart": True,
                        }
                    )
                    play["vars"].update(json.loads(node.extra["netplan_parameters"]))
                    play["roles"].append("osism.commons.network")

                # Get frr_parameters from Ironic node extra (JSON string, needs parsing)
                if "frr_parameters" in node.extra and node.extra["frr_parameters"]:
                    play["vars"].update(
                        {
                            "frr_dummy_interface": "loopback0",
                        }
                    )
                    play["vars"].update(json.loads(node.extra["frr_parameters"]))
                    play["roles"].append("osism.services.frr")

                playbook.append(play)

                # Output playbook to stdout
                print(
                    yaml.dump(
                        playbook,
                        default_flow_style=False,
                        explicit_start=True,
                        indent=2,
                        sort_keys=False,
                    )
                )
            else:
                # Fetch data from NetBox (default behavior, may show newer data)
                # Check if NetBox connection is available
                if not utils.nb:
                    logger.error("NetBox connection not available")
                    return

                # Try to find device by name first
                device = utils.nb.dcim.devices.get(name=name)

                # If not found by name, try by inventory_hostname custom field
                if not device:
                    devices = utils.nb.dcim.devices.filter(cf_inventory_hostname=name)
                    if devices:
                        device = devices[0]

                # If device not found, error out
                if not device:
                    logger.error(f"Could not find device {name} in NetBox")
                    return

                # Get default vars from NetBox local_context_data if available
                default_vars = {}
                if hasattr(device, "local_context_data") and device.local_context_data:
                    default_vars = device.local_context_data
                    logger.info(
                        f"Using NetBox local_context_data for device {device.name}"
                    )
                else:
                    logger.debug(
                        f"No local_context_data found for device {device.name} in NetBox"
                    )

                playbook = []
                play = {
                    "name": "Run bootstrap",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "vars": default_vars.copy(),
                    "roles": [
                        "osism.commons.hostname",
                        "osism.commons.hosts",
                        "osism.commons.operator",
                    ],
                    "tasks": [
                        {
                            "name": "Restart rsyslog service after hostname change",
                            "ansible.builtin.systemd": {
                                "name": "rsyslog",
                                "state": "restarted",
                            },
                        }
                    ],
                }
                play["vars"].update(
                    {"hostname_name": device.name, "hosts_type": "template"}
                )

                # Get netplan_parameters from NetBox custom fields (already a dict, no JSON parsing needed)
                if (
                    "netplan_parameters" in device.custom_fields
                    and device.custom_fields["netplan_parameters"]
                ):
                    play["vars"].update(
                        {
                            "network_allow_service_restart": True,
                        }
                    )
                    play["vars"].update(device.custom_fields["netplan_parameters"])
                    play["roles"].append("osism.commons.network")

                # Get frr_parameters from NetBox custom fields (already a dict, no JSON parsing needed)
                if (
                    "frr_parameters" in device.custom_fields
                    and device.custom_fields["frr_parameters"]
                ):
                    play["vars"].update(
                        {
                            "frr_dummy_interface": "loopback0",
                        }
                    )
                    play["vars"].update(device.custom_fields["frr_parameters"])
                    play["roles"].append("osism.services.frr")

                playbook.append(play)

                # Output playbook to stdout
                print(
                    yaml.dump(
                        playbook,
                        default_flow_style=False,
                        explicit_start=True,
                        indent=2,
                        sort_keys=False,
                    )
                )
        except Exception as exc:
            logger.error(f"Failed to generate playbook for {name}: {exc}")


class BaremetalUndeploy(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalUndeploy, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Undeploy given baremetal node",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Undeploy all baremetal nodes",
            action="store_true",
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
        name = parsed_args.name
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        if all_nodes and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to undeploy all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            deploy_nodes = list(conn.baremetal.nodes())
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=False)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            deploy_nodes = [node]

        for node in deploy_nodes:
            if not node:
                continue

            if node.provision_state in [
                "active",
                "wait call-back",
                "deploy failed",
                "error",
            ]:
                try:
                    node = conn.baremetal.set_node_provision_state(node.id, "undeploy")
                    logger.info(
                        f"Successfully initiated undeploy for node {node.name} ({node.id})"
                    )

                    # Clean up SSH known_hosts entries for the undeployed node
                    logger.info(f"Cleaning up SSH known_hosts entries for {node.name}")
                    result = cleanup_ssh_known_hosts_for_node(node.name)
                    if result:
                        logger.info(
                            f"SSH known_hosts cleanup completed successfully for {node.name}"
                        )
                    else:
                        logger.warning(
                            f"SSH known_hosts cleanup completed with warnings for {node.name}"
                        )

                except Exception as exc:
                    logger.warning(
                        f"Node {node.name} ({node.id}) could not be moved to available state: {exc}"
                    )
                    continue
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported provision state"
                )


class BaremetalPing(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalPing, self).get_parser(prog_name)
        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Ping specific baremetal node by name",
        )
        return parser

    def _ping_host(self, host, results, host_name):
        """Ping a host 3 times and store results."""
        try:
            result = subprocess.run(
                ["ping", "-c", "3", "-W", "5", host],
                capture_output=True,
                text=True,
                timeout=20,
            )

            if result.returncode == 0:
                output_lines = result.stdout.strip().split("\n")
                stats_line = [line for line in output_lines if "packet loss" in line]
                if stats_line:
                    loss_info = stats_line[0]
                    if "0% packet loss" in loss_info:
                        status = "SUCCESS"
                    else:
                        status = f"PARTIAL ({loss_info.split(',')[2].strip()})"
                else:
                    status = "SUCCESS"

                time_lines = [
                    line
                    for line in output_lines
                    if "round-trip" in line or "rtt" in line
                ]
                if time_lines:
                    time_info = (
                        time_lines[0].split("=")[-1].strip()
                        if "=" in time_lines[0]
                        else "N/A"
                    )
                else:
                    time_info = "N/A"
            else:
                status = "FAILED"
                time_info = "N/A"

        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            Exception,
        ) as e:
            status = "ERROR"
            time_info = str(e)[:50]

        results[host_name] = {"host": host, "status": status, "time_info": time_info}

    def take_action(self, parsed_args):
        name = parsed_args.name

        if not utils.nb:
            logger.error("NetBox connection not available")
            return

        conn = get_cloud_connection()

        try:
            if name:
                devices = [utils.nb.dcim.devices.get(name=name)]
                if not devices[0]:
                    logger.error(f"Device {name} not found in NetBox")
                    return
            else:
                # Use the NETBOX_FILTER_CONDUCTOR_IRONIC setting to get devices
                devices = set()
                nb_device_query_list = get_nb_device_query_list_ironic()
                for nb_device_query in nb_device_query_list:
                    devices |= set(netbox.get_devices(**nb_device_query))
                devices = list(devices)

                # Additionally filter by power state and provision state
                filtered_devices = []
                for device in devices:
                    if (
                        hasattr(device, "custom_fields")
                        and device.custom_fields
                        and device.custom_fields.get("power_state") == "power on"
                        and device.custom_fields.get("provision_state") == "active"
                    ):
                        filtered_devices.append(device)
                devices = filtered_devices

            if not devices:
                logger.info(
                    "No devices found matching criteria (managed-by-ironic, power on, active)"
                )
                return

            ping_candidates = []
            for device in devices:
                if device.primary_ip4:
                    ip_address = str(device.primary_ip4.address).split("/")[0]
                    ping_candidates.append({"name": device.name, "ip": ip_address})
                else:
                    logger.warning(f"Device {device.name} has no primary IPv4 address")

            if not ping_candidates:
                logger.info("No devices found with primary IPv4 addresses")
                return

            logger.info(f"Pinging {len(ping_candidates)} nodes (3 pings each)...")

            results = {}
            threads = []

            for candidate in ping_candidates:
                thread = threading.Thread(
                    target=self._ping_host,
                    args=(candidate["ip"], results, candidate["name"]),
                )
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            table_data = []
            success_count = 0
            failed_count = 0

            for device_name in sorted(results.keys()):
                result = results[device_name]
                table_data.append(
                    [device_name, result["host"], result["status"], result["time_info"]]
                )

                if result["status"] == "SUCCESS":
                    success_count += 1
                elif result["status"].startswith("PARTIAL"):
                    failed_count += 1
                else:
                    failed_count += 1

            print(
                tabulate(
                    table_data,
                    headers=["Name", "IP Address", "Status", "Time Info"],
                    tablefmt="psql",
                )
            )

            print(
                f"\nSummary: {success_count} successful, {failed_count} failed/partial out of {len(ping_candidates)} total"
            )

        except Exception as e:
            logger.error(f"Error during ping operation: {e}")
            return


class BaremetalBurnIn(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalBurnIn, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Run burn-in on given baremetal node when in provision state available",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Run burn-in on all baremetal nodes in provision state available",
            action="store_true",
        )
        parser.add_argument(
            "--cpu",
            default=True,
            help="Enable CPU burn-in",
            action=BooleanOptionalAction,
        )
        parser.add_argument(
            "--memory",
            default=True,
            help="Enable memory burn-in",
            action=BooleanOptionalAction,
        )
        parser.add_argument(
            "--disk",
            default=True,
            help="Enable disk burn-in",
            action=BooleanOptionalAction,
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        name = parsed_args.name

        stressor = {}
        stressor["cpu"] = parsed_args.cpu
        stressor["memory"] = parsed_args.memory
        stressor["disk"] = parsed_args.disk

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        clean_steps = []
        for step, activated in stressor.items():
            if activated:
                clean_steps.append({"step": "burnin_" + step, "interface": "deploy"})
        if not clean_steps:
            logger.error(
                f"Please specify at least one of {', '.join(stressor.keys())} for burn-in"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            burn_in_nodes = list(conn.baremetal.nodes(details=True))
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            burn_in_nodes = [node]

        for node in burn_in_nodes:
            if not node:
                continue

            if node.provision_state in ["available"]:
                # NOTE: Burn-In is available in the "manageable" provision state, so we move the node into this state
                try:
                    node = conn.baremetal.set_node_provision_state(node.id, "manage")
                    node = conn.baremetal.wait_for_nodes_provision_state(
                        [node.id], "manageable"
                    )[0]
                except Exception as exc:
                    logger.warning(
                        f"Node {node.name} ({node.id}) could not be moved to manageable state: {exc}"
                    )
                    continue

            if node.provision_state in ["manageable"]:
                try:
                    conn.baremetal.set_node_provision_state(
                        node.id, "clean", clean_steps=clean_steps
                    )
                except Exception as exc:
                    logger.warning(
                        f"Burn-In of node {node.name} ({node.id}) failed: {exc}"
                    )
                    continue
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported state! Provision state: {node.provision_state}, maintenance mode: {node['maintenance']}"
                )
                continue


class BaremetalClean(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalClean, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Clean given baremetal node when in provision state available",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Clean all baremetal nodes in provision state available",
            action="store_true",
        )
        parser.add_argument(
            "--yes-i-really-really-mean-it",
            default=False,
            help="Specify this to actually clean all nodes",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        name = parsed_args.name
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        if all_nodes and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to clean all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        clean_steps = [{"interface": "deploy", "step": "erase_devices"}]

        conn = get_cloud_connection()

        if all_nodes:
            clean_nodes = list(conn.baremetal.nodes(details=True))
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            clean_nodes = [node]

        for node in clean_nodes:
            if not node:
                continue

            if node.provision_state in ["available"]:
                # NOTE: Clean is available in the "manageable" provision state, so we move the node into this state
                try:
                    node = conn.baremetal.set_node_provision_state(node.id, "manage")
                    node = conn.baremetal.wait_for_nodes_provision_state(
                        [node.id], "manageable"
                    )[0]
                except Exception as exc:
                    logger.warning(
                        f"Node {node.name} ({node.id}) could not be moved to manageable state: {exc}"
                    )
                    continue

            if node.provision_state in ["manageable"]:
                try:
                    conn.baremetal.set_node_provision_state(
                        node.id, "clean", clean_steps=clean_steps
                    )
                    logger.info(
                        f"Successfully initiated clean for node {node.name} ({node.id})"
                    )
                except Exception as exc:
                    logger.warning(
                        f"Clean of node {node.name} ({node.id}) failed: {exc}"
                    )
                    continue
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported state! Provision state: {node.provision_state}, maintenance mode: {node['maintenance']}"
                )


class BaremetalProvide(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalProvide, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Provide given baremetal node when in provision state manageable",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Provide all baremetal nodes in provision state manageable",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        name = parsed_args.name

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        conn = get_cloud_connection()

        if all_nodes:
            provide_nodes = list(conn.baremetal.nodes(details=True))
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            provide_nodes = [node]

        for node in provide_nodes:
            if not node:
                continue

            if node.provision_state == "manageable" and not node["maintenance"]:
                try:
                    conn.baremetal.set_node_provision_state(node.id, "provide")
                    logger.info(
                        f"Successfully initiated provide for node {node.name} ({node.id})"
                    )
                except Exception as exc:
                    logger.warning(
                        f"Node {node.name} ({node.id}) could not be moved to available state: {exc}"
                    )
                    continue
            else:
                logger.warning(
                    f"Node {node.name} ({node.id}) not in supported state! Provision state: {node.provision_state}, maintenance mode: {node['maintenance']}"
                )


class BaremetalMaintenanceSet(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalMaintenanceSet, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Set maintenance on given baremetal node",
        )
        parser.add_argument(
            "--reason",
            default=None,
            type=str,
            help="Reason for maintenance",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name
        reason = parsed_args.reason

        conn = get_cloud_connection()
        node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
        if not node:
            logger.warning(f"Could not find node {name}")
            return
        try:
            conn.baremetal.set_node_maintenance(node, reason=reason)
        except Exception as exc:
            logger.error(
                f"Setting maintenance mode on node {node.name} ({node.id}) failed: {exc}"
            )


class BaremetalMaintenanceUnset(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalMaintenanceUnset, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Unset maintenance on given baremetal node",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name

        conn = get_cloud_connection()
        node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
        if not node:
            logger.warning(f"Could not find node {name}")
            return
        try:
            conn.baremetal.unset_node_maintenance(node)
        except Exception as exc:
            logger.error(
                f"Unsetting maintenance mode on node {node.name} ({node.id}) failed: {exc}"
            )


class BaremetalPowerOn(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalPowerOn, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Power on given baremetal node",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name

        if not name:
            logger.error("Please specify a node name")
            return

        conn = get_cloud_connection()
        node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
        if not node:
            logger.warning(f"Could not find node {name}")
            return

        try:
            conn.baremetal.set_node_power_state(node.id, "power on")
            logger.info(f"Successfully powered on node {node.name} ({node.id})")
        except Exception as exc:
            logger.error(f"Failed to power on node {node.name} ({node.id}): {exc}")


class BaremetalPowerOff(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalPowerOff, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Power off given baremetal node",
        )
        return parser

    def take_action(self, parsed_args):
        name = parsed_args.name

        if not name:
            logger.error("Please specify a node name")
            return

        conn = get_cloud_connection()
        node = conn.baremetal.find_node(name, ignore_missing=True, details=True)
        if not node:
            logger.warning(f"Could not find node {name}")
            return

        try:
            conn.baremetal.set_node_power_state(node.id, "power off")
            logger.info(f"Successfully powered off node {node.name} ({node.id})")
        except Exception as exc:
            logger.error(f"Failed to power off node {node.name} ({node.id}): {exc}")


class BaremetalDelete(Command):
    def get_parser(self, prog_name):
        parser = super(BaremetalDelete, self).get_parser(prog_name)

        parser.add_argument(
            "name",
            nargs="?",
            type=str,
            help="Delete given baremetal node",
        )
        parser.add_argument(
            "--all",
            default=False,
            help="Delete all baremetal nodes",
            action="store_true",
        )
        parser.add_argument(
            "--yes-i-really-really-mean-it",
            default=False,
            help="Specify this to actually delete all nodes",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        all_nodes = parsed_args.all
        name = parsed_args.name
        yes_i_really_really_mean_it = parsed_args.yes_i_really_really_mean_it

        if not all_nodes and not name:
            logger.error("Please specify a node name or use --all")
            return

        if all_nodes and not yes_i_really_really_mean_it:
            logger.error(
                "Please confirm that you wish to delete all nodes by specifying '--yes-i-really-really-mean-it'"
            )
            return

        conn = get_cloud_connection()

        if all_nodes:
            delete_nodes = list(conn.baremetal.nodes())
        else:
            node = conn.baremetal.find_node(name, ignore_missing=True, details=False)
            if not node:
                logger.warning(f"Could not find node {name}")
                return
            delete_nodes = [node]

        for node in delete_nodes:
            if not node:
                continue

            try:
                # Delete ports first (safe deletion pattern)
                logger.info(f"Deleting ports for node {node.name} ({node.id})")
                ports = conn.baremetal.ports(node_uuid=node.id)
                for port in ports:
                    try:
                        conn.baremetal.delete_port(port.id, ignore_missing=True)
                        logger.debug(f"Deleted port {port.id} for node {node.name}")
                    except Exception as exc:
                        logger.warning(
                            f"Failed to delete port {port.id} for node {node.name}: {exc}"
                        )

                # Delete the node from Ironic
                logger.info(f"Deleting node {node.name} ({node.id}) from Ironic")
                conn.baremetal.delete_node(node.id, ignore_missing=True)
                logger.info(
                    f"Successfully deleted node {node.name} ({node.id}) from Ironic"
                )

                # Clear NetBox states after successful Ironic deletion
                if utils.nb:
                    logger.info(
                        f"Clearing NetBox states for node {node.name} on primary NetBox"
                    )
                    try:
                        device = utils.nb.dcim.devices.get(name=node.name)
                        if device:
                            device.custom_fields.update(
                                {"provision_state": None, "power_state": None}
                            )
                            device.save()
                            logger.info(
                                f"Successfully cleared NetBox states for {node.name}"
                            )
                        else:
                            logger.warning(
                                f"Device {node.name} not found in primary NetBox"
                            )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to clear NetBox states for {node.name} on primary NetBox: {exc}"
                        )

                # Clear NetBox states on secondary instances
                for secondary_nb in utils.secondary_nb_list:
                    logger.info(
                        f"Clearing NetBox states for node {node.name} on secondary NetBox {secondary_nb.base_url}"
                    )
                    try:
                        device = secondary_nb.dcim.devices.get(name=node.name)
                        if device:
                            device.custom_fields.update(
                                {"provision_state": None, "power_state": None}
                            )
                            device.save()
                            logger.info(
                                f"Successfully cleared NetBox states for {node.name} on {secondary_nb.base_url}"
                            )
                        else:
                            logger.warning(
                                f"Device {node.name} not found in secondary NetBox {secondary_nb.base_url}"
                            )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to clear NetBox states for {node.name} on {secondary_nb.base_url}: {exc}"
                        )

            except Exception as exc:
                logger.error(f"Failed to delete node {node.name} ({node.id}): {exc}")
                continue
