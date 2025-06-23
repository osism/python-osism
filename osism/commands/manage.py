# SPDX-License-Identifier: Apache-2.0

import json
import os
from datetime import datetime
from re import findall
from urllib.parse import urljoin

from cliff.command import Command
import docker
from jinja2 import Template
from loguru import logger
import paramiko
import requests

from osism.data import TEMPLATE_IMAGE_CLUSTERAPI, TEMPLATE_IMAGE_OCTAVIA
from osism.tasks import openstack, ansible, handle_task
from osism import utils

SUPPORTED_CLUSTERAPI_K8S_IMAGES = ["1.31", "1.32", "1.33"]


class ImageClusterapi(Command):
    def get_parser(self, prog_name):
        parser = super(ImageClusterapi, self).get_parser(prog_name)

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-k8s-capi-images/",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="admin",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not perform any changes (--dry-run passed to openstack-image-manager)",
        )
        parser.add_argument(
            "--tag",
            type=str,
            help="Name of the tag used to identify managed images (use openstack-image-manager's default if unset)",
            default=None,
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter the version to be managed (e.g. 1.32)",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        base_url = parsed_args.base_url
        cloud = parsed_args.cloud
        filter = parsed_args.filter
        tag = parsed_args.tag
        wait = not parsed_args.no_wait

        if filter:
            supported_cluterapi_k8s_images = [filter]
        else:
            supported_cluterapi_k8s_images = SUPPORTED_CLUSTERAPI_K8S_IMAGES

        result = []
        for kubernetes_release in supported_cluterapi_k8s_images:
            url = urljoin(base_url, f"last-{kubernetes_release}")

            response = requests.get(url)
            splitted = response.text.strip().split(" ")

            logger.info(f"date: {splitted[0]}")
            logger.info(f"image: {splitted[1]}")

            r = findall(r".*ubuntu-2204-kube-v(.*\..*\..*).qcow2", splitted[1])
            logger.info(f"version: {r[0].strip()}")

            url = urljoin(base_url, splitted[1])
            logger.info(f"url: {url}")

            logger.info(f"checksum_url: {url}.CHECKSUM")
            response_checksum = requests.get(f"{url}.CHECKSUM")
            splitted_checksum = response_checksum.text.strip().split(" ")
            logger.info(f"checksum: {splitted_checksum[0]}")

            template = Template(TEMPLATE_IMAGE_CLUSTERAPI)
            result.extend(
                [
                    template.render(
                        image_url=url,
                        image_checksum=f"sha256:{splitted_checksum[0]}",
                        image_version=r[0].strip(),
                        image_builddate=splitted[0],
                    )
                ]
            )

        args = [
            "--cloud",
            cloud,
            "--filter",
            "ubuntu-capi-image",
        ]
        if tag is not None:
            args.extend(["--tag", tag])
        if parsed_args.dry_run:
            args.append("--dry-run")

        task_signature = openstack.image_manager.si(*args, configs=result)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class ImageOctavia(Command):
    def get_parser(self, prog_name):
        parser = super(ImageOctavia, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )

        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="octavia",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-octavia-amphora-image/",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud
        base_url = parsed_args.base_url

        client = docker.from_env()
        container = client.containers.get("kolla-ansible")
        openstack_release = container.labels["de.osism.release.openstack"]
        url = urljoin(base_url, f"last-{openstack_release}")

        response = requests.get(url)
        splitted = response.text.strip().split(" ")

        logger.info(f"date: {splitted[0]}")
        logger.info(f"image: {splitted[1]}")

        url = urljoin(base_url, splitted[1])
        logger.info(f"url: {url}")

        logger.info(f"checksum_url: {url}.CHECKSUM")
        response_checksum = requests.get(f"{url}.CHECKSUM")
        splitted_checksum = response_checksum.text.strip().split(" ")
        logger.info(f"checksum: {splitted_checksum[0]}")

        template = Template(TEMPLATE_IMAGE_OCTAVIA)
        result = []
        result.extend(
            [
                template.render(
                    image_url=url,
                    image_checksum=f"sha256:{splitted_checksum[0]}",
                    image_version=splitted[0],
                    image_builddate=splitted[0],
                )
            ]
        )
        arguments = [
            "--cloud",
            cloud,
            "--deactivate",
        ]

        task_signature = openstack.image_manager.si(
            *arguments, configs=result, ignore_env=True
        )
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Images(Command):
    def get_parser(self, prog_name):
        parser = super(Images, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-image-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--dry-run",
            default=False,
            help="Do not perform any changes",
            action="store_true",
        )
        parser.add_argument(
            "--hide",
            default=True,
            help="Hide images that should be deleted",
            action="store_true",
        )
        parser.add_argument(
            "--delete",
            default=False,
            help="Delete images that should be deleted",
            action="store_true",
        )
        parser.add_argument(
            "--latest",
            default=False,
            help="Only import the latest version for images of type multi",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter images with a regex on their name",
            default=None,
        )
        parser.add_argument(
            "--images",
            type=str,
            help="Path to the directory containing all image files or path to single image file",
            default=None,
        )

        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        arguments = []
        if parsed_args.cloud:
            arguments.append("--cloud")
            arguments.append(parsed_args.cloud)
        if parsed_args.filter:
            arguments.append("--filter")
            arguments.append(parsed_args.filter)
        if parsed_args.delete:
            arguments.append("--delete")
            arguments.append("--yes-i-really-know-what-i-do")
        if parsed_args.dry_run:
            arguments.append("--dry-run")
        if parsed_args.latest:
            arguments.append("--latest")
        if parsed_args.hide:
            arguments.append("--hide")

        arguments.append("--images")
        if parsed_args.images:
            arguments.append(parsed_args.images)
        else:
            arguments.append("/etc/images")

        task_signature = openstack.image_manager.si(*arguments)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Flavors(Command):
    def get_parser(self, prog_name):
        parser = super(Flavors, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-flavor-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until flavor management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="admin"
        )
        parser.add_argument(
            "--name",
            type=str,
            help="Name of flavor definitions",
            default="scs",
            choices=["scs", "osism", "local", "url"],
        )
        parser.add_argument(
            "--url",
            type=str,
            help="Overwrite the default URL where the flavor definitions are available",
            default=None,
        )
        parser.add_argument(
            "--recommended",
            default=False,
            help="Also create recommended flavors",
            action="store_true",
        )

        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud
        name = parsed_args.name
        recommended = parsed_args.recommended
        url = parsed_args.url

        arguments = ["--name", name]
        if cloud:
            arguments.append("--cloud")
            arguments.append(cloud)

        if recommended:
            arguments.append("--recommended")

        if url:
            arguments.append("--url")
            arguments.append(url)

        task_signature = openstack.flavor_manager.si(*arguments)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (flavor-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Dnsmasq(Command):
    def get_parser(self, prog_name):
        parser = super(Dnsmasq, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until dnsmasq has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        wait = not parsed_args.no_wait

        task_signature = ansible.run.si("infrastructure", "dnsmasq", [])
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (dnsmasq) has been started and output is visible here."
            )

        return handle_task(task, wait, format="log", timeout=300)


class Sonic(Command):
    def get_parser(self, prog_name):
        parser = super(Sonic, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to manage"
        )
        parser.add_argument(
            "--reload",
            action="store_true",
            help="Execute config reload after config load to restart services",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        reload_config = parsed_args.reload
        today = datetime.now().strftime("%Y%m%d")

        try:
            # Get device from NetBox - try by name first, then by inventory_hostname
            device = utils.nb.dcim.devices.get(name=hostname)
            if not device:
                # Try to find by inventory_hostname custom field
                devices = utils.nb.dcim.devices.filter(cf_inventory_hostname=hostname)
                if devices:
                    device = devices[0]  # Take the first match
                    logger.info(f"Device found by inventory_hostname: {device.name}")
                else:
                    logger.error(
                        f"Device {hostname} not found in NetBox (searched by name and inventory_hostname)"
                    )
                    return 1

            # Get device configuration from local_context_data
            if (
                not hasattr(device, "local_context_data")
                or not device.local_context_data
            ):
                logger.error(f"Device {hostname} has no local_context_data in NetBox")
                return 1

            config_context = device.local_context_data

            # Save config context to local /tmp directory
            config_context_file = f"/tmp/config_db_{hostname}_{today}.json"
            try:
                with open(config_context_file, "w") as f:
                    json.dump(config_context, f, indent=2)
                logger.info(f"Config context saved to {config_context_file}")
            except Exception as e:
                logger.error(f"Failed to save config context: {e}")
                return 1

            # Extract SSH connection details
            ssh_host = None
            ssh_username = None

            # Try to get SSH details from config context
            if "management" in config_context:
                mgmt = config_context["management"]
                if "ip" in mgmt:
                    ssh_host = mgmt["ip"]
                if "username" in mgmt:
                    ssh_username = mgmt["username"]

            # Fallback: try to get OOB IP from NetBox
            if not ssh_host:
                from osism.tasks.conductor.netbox import get_device_oob_ip

                oob_result = get_device_oob_ip(device)
                if oob_result:
                    ssh_host = oob_result[0]

            if not ssh_host:
                logger.error(f"No SSH host found for device {hostname}")
                return 1

            if not ssh_username:
                ssh_username = "admin"  # Default SONiC username

            # SSH private key path
            ssh_key_path = "/ansible/secrets/id_rsa.operator"

            if not os.path.exists(ssh_key_path):
                logger.error(f"SSH private key not found at {ssh_key_path}")
                return 1

            logger.info(
                f"Connecting to {hostname} ({ssh_host}) to backup SONiC configuration"
            )

            # Create SSH connection
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                # Connect with private key
                ssh.connect(
                    hostname=ssh_host,
                    username=ssh_username,
                    key_filename=ssh_key_path,
                    timeout=30,
                )

                # Generate backup filename with date and increment on switch
                base_backup_path = f"/home/admin/config_db_{hostname}_{today}"
                backup_filename = f"{base_backup_path}_1.json"

                # Find next available filename on switch
                x = 1
                while True:
                    check_cmd = f"ls {base_backup_path}_{x}.json 2>/dev/null"
                    stdin, stdout, stderr = ssh.exec_command(check_cmd)
                    if stdout.read().decode().strip() == "":
                        backup_filename = f"{base_backup_path}_{x}.json"
                        break
                    x += 1

                logger.info(
                    f"Backing up current configuration on switch to {backup_filename}"
                )

                # Backup current configuration on switch
                backup_cmd = f"sudo cp /etc/sonic/config_db.json {backup_filename}"
                stdin, stdout, stderr = ssh.exec_command(backup_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    logger.error(
                        f"Failed to backup configuration on switch: {error_msg}"
                    )
                    return 1

                logger.info("Configuration backed up successfully on switch")

                # Upload local config context to switch /tmp directory
                switch_config_file = f"/tmp/config_db_{hostname}_current.json"
                logger.info(
                    f"Uploading config context to {switch_config_file} on switch"
                )

                # Use SFTP to upload the config context file
                sftp = ssh.open_sftp()
                try:
                    sftp.put(config_context_file, switch_config_file)
                    logger.info(
                        f"Config context successfully uploaded to {switch_config_file} on switch"
                    )
                except Exception as e:
                    logger.error(f"Failed to upload config context to switch: {e}")
                    return 1
                finally:
                    sftp.close()

                # Load and apply the new configuration
                logger.info("Loading and applying new configuration on switch")

                load_cmd = f"sudo config load -y {switch_config_file}"
                stdin, stdout, stderr = ssh.exec_command(load_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    logger.error(f"Failed to load configuration: {error_msg}")
                    return 1

                logger.info("Configuration loaded and applied successfully")

                # Optionally reload configuration to restart services
                config_operations_successful = True
                if reload_config:
                    logger.info("Reloading configuration to restart services")

                    reload_cmd = "sudo config reload -y"
                    stdin, stdout, stderr = ssh.exec_command(reload_cmd)
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status != 0:
                        error_msg = stderr.read().decode()
                        logger.error(f"Failed to reload configuration: {error_msg}")
                        config_operations_successful = False
                    else:
                        logger.info("Configuration reloaded successfully")

                # Save configuration only if load (and optionally reload) were successful
                if config_operations_successful:
                    logger.info("Saving configuration to persist changes")

                    save_cmd = "sudo config save -y"
                    stdin, stdout, stderr = ssh.exec_command(save_cmd)
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status != 0:
                        error_msg = stderr.read().decode()
                        logger.error(f"Failed to save configuration: {error_msg}")
                        return 1

                    logger.info("Configuration saved successfully")
                else:
                    logger.warning("Skipping config save due to reload failure")

                # Delete the temporary configuration file
                logger.info(f"Cleaning up temporary file {switch_config_file}")

                delete_cmd = f"rm {switch_config_file}"
                stdin, stdout, stderr = ssh.exec_command(delete_cmd)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    logger.warning(f"Failed to delete temporary file: {error_msg}")
                else:
                    logger.info("Temporary file deleted successfully")

                logger.info("SONiC configuration management completed successfully")
                logger.info(f"- Config context saved locally to: {config_context_file}")
                if reload_config and config_operations_successful:
                    logger.info("- Configuration loaded, reloaded, and saved on switch")
                elif config_operations_successful:
                    logger.info("- Configuration loaded and saved on switch")
                else:
                    logger.info(
                        "- Configuration loaded on switch (save skipped due to reload failure)"
                    )
                logger.info(f"- Backup created on switch: {backup_filename}")

                return 0

            except paramiko.AuthenticationException:
                logger.error(f"Authentication failed for {ssh_host}")
                return 1
            except paramiko.SSHException as e:
                logger.error(f"SSH connection failed: {e}")
                return 1
            except Exception as e:
                logger.error(f"Unexpected error during SSH operations: {e}")
                return 1
            finally:
                ssh.close()

        except Exception as e:
            logger.error(f"Error managing SONiC device {hostname}: {e}")
            return 1
