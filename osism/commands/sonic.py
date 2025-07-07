# SPDX-License-Identifier: Apache-2.0

import json
import os
from datetime import datetime

from cliff.command import Command
from loguru import logger
import paramiko

from osism import utils


class Manage(Command):
    def get_parser(self, prog_name):
        parser = super(Manage, self).get_parser(prog_name)
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
