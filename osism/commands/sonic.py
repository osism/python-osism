# SPDX-License-Identifier: Apache-2.0

import json
import logging
import os
from datetime import datetime

from cliff.command import Command
from loguru import logger
import paramiko
from prompt_toolkit import prompt
from tabulate import tabulate

from osism import utils
from osism.utils.ssh import (
    cleanup_ssh_known_hosts_for_node,
    ensure_known_hosts_file,
    KNOWN_HOSTS_PATH,
)

# Suppress paramiko logging messages globally
logging.getLogger("paramiko").setLevel(logging.ERROR)
logging.getLogger("paramiko.transport").setLevel(logging.ERROR)


class SonicCommandBase(Command):
    """Base class for SONiC commands with common functionality"""

    def _get_device_from_netbox(self, hostname):
        """Get device from NetBox by name or inventory_hostname"""
        device = utils.nb.dcim.devices.get(name=hostname)
        if not device:
            devices = utils.nb.dcim.devices.filter(cf_inventory_hostname=hostname)
            if devices:
                device = devices[0]
                logger.info(f"Device found by inventory_hostname: {device.name}")
            else:
                logger.error(
                    f"Device {hostname} not found in NetBox (searched by name and inventory_hostname)"
                )
                return None
        return device

    def _get_config_context(self, device, hostname):
        """Get and validate device configuration context"""
        if not hasattr(device, "local_context_data") or not device.local_context_data:
            logger.error(f"Device {hostname} has no local_context_data in NetBox")
            return None

        # Filter out keys that start with underscore
        filtered_context = {
            key: value
            for key, value in device.local_context_data.items()
            if not key.startswith("_")
        }

        return filtered_context

    def _save_config_context(self, config_context, hostname, today):
        """Save config context to local file"""
        config_context_file = f"/tmp/config_db_{hostname}_{today}.json"
        try:
            with open(config_context_file, "w") as f:
                json.dump(config_context, f, indent=2)
            logger.info(f"Config context saved to {config_context_file}")
            return config_context_file
        except Exception as e:
            logger.error(f"Failed to save config context: {e}")
            return None

    def _get_ssh_connection_details(self, config_context, device, hostname):
        """Extract SSH connection details from config context and NetBox"""
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
            return None, None

        if not ssh_username:
            ssh_username = "admin"  # Default SONiC username

        return ssh_host, ssh_username

    def _create_ssh_connection(self, ssh_host, ssh_username):
        """Create and return SSH connection"""
        ssh_key_path = "/ansible/secrets/id_rsa.operator"

        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH private key not found at {ssh_key_path}")
            return None

        # Ensure known_hosts file exists
        if not ensure_known_hosts_file():
            logger.warning(
                f"Could not initialize {KNOWN_HOSTS_PATH}, continuing with AutoAddPolicy"
            )

        ssh = paramiko.SSHClient()
        # Load system host keys from centralized known_hosts file
        try:
            ssh.load_host_keys(KNOWN_HOSTS_PATH)
        except FileNotFoundError:
            logger.debug(
                "Centralized known_hosts file not found, creating empty host key store"
            )
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            ssh.connect(
                hostname=ssh_host,
                username=ssh_username,
                key_filename=ssh_key_path,
                timeout=30,
            )
            return ssh
        except Exception as e:
            logger.error(f"Failed to create SSH connection: {e}")
            return None

    def _generate_backup_filename(self, ssh, hostname, today):
        """Generate unique backup filename on switch"""
        base_backup_path = f"/home/admin/config_db_{hostname}_{today}"
        x = 1
        while True:
            backup_filename = f"{base_backup_path}_{x}.json"
            check_cmd = f"ls {backup_filename} 2>/dev/null"
            stdin, stdout, stderr = ssh.exec_command(check_cmd)
            if stdout.read().decode().strip() == "":
                return backup_filename
            x += 1

    def _backup_current_config(self, ssh, backup_filename):
        """Backup current configuration on switch"""
        logger.info(f"Backing up current configuration on switch to {backup_filename}")
        backup_cmd = f"sudo cp /etc/sonic/config_db.json {backup_filename}"
        stdin, stdout, stderr = ssh.exec_command(backup_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to backup configuration on switch: {error_msg}")
            return False

        logger.info("Configuration backed up successfully on switch")
        return True

    def _upload_config_context(self, ssh, config_context_file, hostname):
        """Upload config context file to switch"""
        switch_config_file = f"/tmp/config_db_{hostname}_current.json"
        logger.info(f"Uploading config context to {switch_config_file} on switch")

        sftp = ssh.open_sftp()
        try:
            sftp.put(config_context_file, switch_config_file)
            logger.info(
                f"Config context successfully uploaded to {switch_config_file} on switch"
            )
            return switch_config_file
        except Exception as e:
            logger.error(f"Failed to upload config context to switch: {e}")
            return None
        finally:
            sftp.close()

    def _load_configuration(self, ssh, switch_config_file):
        """Load and apply configuration on switch"""
        logger.info("Loading and applying new configuration on switch")
        load_cmd = f"sudo config load -y {switch_config_file}"
        stdin, stdout, stderr = ssh.exec_command(load_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to load configuration: {error_msg}")
            return False

        logger.info("Configuration loaded and applied successfully")
        return True

    def _reload_configuration(self, ssh):
        """Reload configuration to restart services"""
        logger.info("Reloading configuration to restart services")
        reload_cmd = "sudo config reload -y"
        stdin, stdout, stderr = ssh.exec_command(reload_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to reload configuration: {error_msg}")
            return False

        logger.info("Configuration reloaded successfully")
        return True

    def _save_configuration(self, ssh):
        """Save configuration to persist changes"""
        logger.info("Saving configuration to persist changes")
        save_cmd = "sudo config save -y"
        stdin, stdout, stderr = ssh.exec_command(save_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to save configuration: {error_msg}")
            return False

        logger.info("Configuration saved successfully")
        return True

    def _cleanup_temp_file(self, ssh, switch_config_file):
        """Delete temporary configuration file"""
        logger.info(f"Cleaning up temporary file {switch_config_file}")
        delete_cmd = f"rm {switch_config_file}"
        stdin, stdout, stderr = ssh.exec_command(delete_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.warning(f"Failed to delete temporary file: {error_msg}")
        else:
            logger.info("Temporary file deleted successfully")

    def _get_ztp_status(self, ssh):
        """Get ZTP (Zero Touch Provisioning) status"""
        logger.info("Checking ZTP status")
        status_cmd = "show ztp status"
        stdin, stdout, stderr = ssh.exec_command(status_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to get ZTP status: {error_msg}")
            return None

        output = stdout.read().decode().strip()
        return output

    def _enable_ztp(self, ssh):
        """Enable ZTP (Zero Touch Provisioning)"""
        logger.info("Enabling ZTP")
        enable_cmd = "sudo config ztp enable"
        stdin, stdout, stderr = ssh.exec_command(enable_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to enable ZTP: {error_msg}")
            return False

        logger.info("ZTP enabled successfully")
        return True

    def _disable_ztp(self, ssh):
        """Disable ZTP (Zero Touch Provisioning)"""
        logger.info("Disabling ZTP")
        disable_cmd = "sudo config ztp disable"
        stdin, stdout, stderr = ssh.exec_command(disable_cmd)
        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            error_msg = stderr.read().decode()
            logger.error(f"Failed to disable ZTP: {error_msg}")
            return False

        logger.info("ZTP disabled successfully")
        return True


class Load(SonicCommandBase):
    """Load SONiC switch configuration"""

    def get_parser(self, prog_name):
        parser = super(Load, self).get_parser(prog_name)
        parser.add_argument(
            "hostname",
            type=str,
            help="Hostname of the SONiC switch to load configuration",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        today = datetime.now().strftime("%Y%m%d")

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Save config context locally
            config_context_file = self._save_config_context(
                config_context, hostname, today
            )
            if not config_context_file:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            logger.info(
                f"Connecting to {hostname} ({ssh_host}) to load SONiC configuration"
            )

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Generate backup filename
                backup_filename = self._generate_backup_filename(ssh, hostname, today)

                # Backup current configuration
                if not self._backup_current_config(ssh, backup_filename):
                    return 1

                # Upload config context
                switch_config_file = self._upload_config_context(
                    ssh, config_context_file, hostname
                )
                if not switch_config_file:
                    return 1

                # Load configuration
                if not self._load_configuration(ssh, switch_config_file):
                    return 1

                # Save configuration
                if not self._save_configuration(ssh):
                    return 1

                # Cleanup
                self._cleanup_temp_file(ssh, switch_config_file)

                logger.info("SONiC configuration load completed successfully")
                logger.info(f"- Config context saved locally to: {config_context_file}")
                logger.info("- Configuration loaded and saved on switch")
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
            logger.error(f"Error loading SONiC device {hostname}: {e}")
            return 1


class Backup(SonicCommandBase):
    """Backup SONiC switch configuration"""

    def get_parser(self, prog_name):
        parser = super(Backup, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to backup"
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        today = datetime.now().strftime("%Y%m%d")

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            logger.info(
                f"Connecting to {hostname} ({ssh_host}) to backup SONiC configuration"
            )

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Generate backup filename
                backup_filename = self._generate_backup_filename(ssh, hostname, today)

                # Backup current configuration
                if not self._backup_current_config(ssh, backup_filename):
                    return 1

                logger.info("SONiC configuration backup completed successfully")
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
            logger.error(f"Error backing up SONiC device {hostname}: {e}")
            return 1


class Ztp(SonicCommandBase):
    """Manage SONiC switch ZTP (Zero Touch Provisioning)"""

    def get_parser(self, prog_name):
        parser = super(Ztp, self).get_parser(prog_name)
        parser.add_argument(
            "action",
            choices=["status", "enable", "disable"],
            help="Action to perform: status (show ZTP status), enable (enable ZTP), or disable (disable ZTP)",
        )
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to manage ZTP"
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        action = parsed_args.action

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            if action == "enable":
                logger.info(f"Connecting to {hostname} ({ssh_host}) to enable ZTP")
            elif action == "disable":
                logger.info(f"Connecting to {hostname} ({ssh_host}) to disable ZTP")
            else:
                logger.info(
                    f"Connecting to {hostname} ({ssh_host}) to check ZTP status"
                )

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                if action == "enable":
                    # Enable ZTP
                    if not self._enable_ztp(ssh):
                        return 1
                    logger.info("ZTP management completed successfully")
                    logger.info("- ZTP has been enabled")

                elif action == "disable":
                    # Disable ZTP
                    if not self._disable_ztp(ssh):
                        return 1
                    logger.info("ZTP management completed successfully")
                    logger.info("- ZTP has been disabled")

                else:
                    # Get status only
                    status = self._get_ztp_status(ssh)
                    if status is None:
                        return 1
                    logger.info("ZTP status check completed successfully")
                    logger.info(f"- ZTP Status: {status}")

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
            logger.error(f"Error managing ZTP on SONiC device {hostname}: {e}")
            return 1


class Reload(SonicCommandBase):
    """Reload SONiC switch configuration"""

    def get_parser(self, prog_name):
        parser = super(Reload, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to reload"
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        today = datetime.now().strftime("%Y%m%d")

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Save config context locally
            config_context_file = self._save_config_context(
                config_context, hostname, today
            )
            if not config_context_file:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            logger.info(
                f"Connecting to {hostname} ({ssh_host}) to reload SONiC configuration"
            )

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Generate backup filename
                backup_filename = self._generate_backup_filename(ssh, hostname, today)

                # Backup current configuration
                if not self._backup_current_config(ssh, backup_filename):
                    return 1

                # Upload config context
                switch_config_file = self._upload_config_context(
                    ssh, config_context_file, hostname
                )
                if not switch_config_file:
                    return 1

                # Load configuration
                if not self._load_configuration(ssh, switch_config_file):
                    return 1

                # Reload configuration
                reload_successful = self._reload_configuration(ssh)

                # Save configuration only if reload was successful
                if reload_successful:
                    if not self._save_configuration(ssh):
                        return 1
                else:
                    logger.warning("Skipping config save due to reload failure")

                # Cleanup
                self._cleanup_temp_file(ssh, switch_config_file)

                logger.info("SONiC configuration reload completed successfully")
                logger.info(f"- Config context saved locally to: {config_context_file}")
                if reload_successful:
                    logger.info("- Configuration loaded, reloaded, and saved on switch")
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
            logger.error(f"Error reloading SONiC device {hostname}: {e}")
            return 1


class Reboot(SonicCommandBase):
    """Reboot SONiC switch"""

    def get_parser(self, prog_name):
        parser = super(Reboot, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to reboot"
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            logger.info(f"Connecting to {hostname} ({ssh_host}) to reboot SONiC switch")

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Reboot the switch
                logger.info("Rebooting SONiC switch")
                reboot_cmd = "sudo reboot"
                stdin, stdout, stderr = ssh.exec_command(reboot_cmd)

                # Note: We don't check exit status here because the connection will be terminated
                # by the reboot command before we can receive the status

                logger.info("SONiC switch reboot command executed successfully")
                logger.info("- Switch is rebooting now")
                logger.info("- Connection will be terminated by the reboot")

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
            logger.error(f"Error rebooting SONiC device {hostname}: {e}")
            return 1


class Reset(SonicCommandBase):
    """Factory reset SONiC switch using ONIE"""

    def get_parser(self, prog_name):
        parser = super(Reset, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to factory reset"
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force factory reset without confirmation prompt",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        hostname = parsed_args.hostname
        force = parsed_args.force

        if not force:
            logger.warning(
                "Factory reset will completely wipe the switch and require reinstallation!"
            )
            response = prompt("Are you sure you want to proceed? [yes/no]: ")
            if response.lower() not in ["yes", "y"]:
                logger.info("Factory reset cancelled by user")
                return 0

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            logger.info(
                f"Connecting to {hostname} ({ssh_host}) to perform factory reset"
            )

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Factory reset using ONIE uninstall
                logger.info("Initiating factory reset via ONIE uninstall")
                logger.warning("This will completely wipe the switch!")

                # Set ONIE mode to uninstall and boot into ONIE
                logger.info("Setting ONIE mode to uninstall")
                grub_cmd1 = (
                    "sudo grub-editenv /host/grub/grubenv set onie_mode=uninstall"
                )
                stdin, stdout, stderr = ssh.exec_command(grub_cmd1)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    logger.error(f"Failed to set ONIE mode: {error_msg}")
                    return 1

                logger.info("Setting next boot entry to ONIE")
                grub_cmd2 = "sudo grub-editenv /host/grub/grubenv set next_entry=ONIE"
                stdin, stdout, stderr = ssh.exec_command(grub_cmd2)
                exit_status = stdout.channel.recv_exit_status()

                if exit_status != 0:
                    error_msg = stderr.read().decode()
                    logger.error(f"Failed to set next boot entry: {error_msg}")
                    return 1

                logger.info("Rebooting into ONIE uninstall mode")
                reset_cmd = "sudo reboot"
                stdin, stdout, stderr = ssh.exec_command(reset_cmd)

                # Note: We don't check exit status here because the connection will be terminated
                # by the reboot command before we can receive the status

                logger.info("Factory reset command executed successfully")
                logger.info("- Switch is entering ONIE uninstall mode")
                logger.info("- All configuration and data will be wiped")
                logger.info("- Switch will need to be reinstalled after reset")
                logger.info("- Connection will be terminated by the reboot")

                # Clean up SSH known_hosts entries for the reset node
                logger.info(f"Cleaning up SSH known_hosts entries for {hostname}")
                result = cleanup_ssh_known_hosts_for_node(hostname)
                if result:
                    logger.info("- SSH known_hosts cleanup completed successfully")
                else:
                    logger.warning("- SSH known_hosts cleanup completed with warnings")

                # Set provision_state to 'ztp' in NetBox
                from osism.tasks import netbox

                logger.info("Setting provision_state to 'ztp' in NetBox")
                netbox.set_provision_state.delay(hostname, "ztp")

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
            logger.error(
                f"Error performing factory reset on SONiC device {hostname}: {e}"
            )
            return 1


class Show(SonicCommandBase):
    """Execute show commands on SONiC switch"""

    def get_parser(self, prog_name):
        parser = super(Show, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to query"
        )
        parser.add_argument(
            "command",
            nargs="*",
            help="Show command and parameters to execute (e.g., 'interfaces', 'version', 'ip route'). If not specified, executes 'show' to display available commands",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname
        command_parts = parsed_args.command if parsed_args.command else []

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            # Build the show command
            if command_parts:
                show_command = "show " + " ".join(command_parts)
            else:
                show_command = "show"
            logger.info(f"Executing command on {hostname} ({ssh_host}): {show_command}")

            # Create SSH connection
            ssh = self._create_ssh_connection(ssh_host, ssh_username)
            if not ssh:
                return 1

            try:
                # Execute the show command
                stdin, stdout, stderr = ssh.exec_command(show_command)
                exit_status = stdout.channel.recv_exit_status()

                # Read output
                output = stdout.read().decode().strip()
                error_output = stderr.read().decode().strip()

                if exit_status != 0:
                    logger.error(f"Command failed with exit code {exit_status}")
                    if error_output:
                        logger.error(f"Error output: {error_output}")
                    return 1

                # Print the command output
                if output:
                    print(output)
                else:
                    logger.info("Command executed successfully (no output)")

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
            logger.error(
                f"Error executing show command on SONiC device {hostname}: {e}"
            )
            return 1


class Console(SonicCommandBase):
    """Open interactive SSH console to SONiC switch"""

    def get_parser(self, prog_name):
        parser = super(Console, self).get_parser(prog_name)
        parser.add_argument(
            "hostname", type=str, help="Hostname of the SONiC switch to connect to"
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context for SSH connection details
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Get SSH connection details
            ssh_host, ssh_username = self._get_ssh_connection_details(
                config_context, device, hostname
            )
            if not ssh_host:
                return 1

            # SSH key path
            ssh_key_path = "/ansible/secrets/id_rsa.operator"

            if not os.path.exists(ssh_key_path):
                logger.error(f"SSH private key not found at {ssh_key_path}")
                return 1

            # Ensure known_hosts file exists
            if not ensure_known_hosts_file():
                logger.warning(
                    f"Could not initialize {KNOWN_HOSTS_PATH}, SSH may show warnings"
                )

            logger.info(f"Connecting to {hostname} ({ssh_host}) via SSH console")

            # Execute SSH command using os.system to provide interactive terminal
            ssh_command = f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile={KNOWN_HOSTS_PATH} {ssh_username}@{ssh_host}"

            logger.info("Starting SSH session...")
            logger.info("To exit the console, type 'exit' or press Ctrl+D")

            # Execute the SSH command
            exit_code = os.system(ssh_command)

            if exit_code == 0:
                logger.info("SSH session ended successfully")
                return 0
            else:
                logger.error(f"SSH session failed with exit code {exit_code}")
                return 1

        except Exception as e:
            logger.error(f"Error connecting to SONiC device {hostname}: {e}")
            return 1


class Dump(SonicCommandBase):
    """Dump SONiC switch configuration from NetBox config context"""

    def get_parser(self, prog_name):
        parser = super(Dump, self).get_parser(prog_name)
        parser.add_argument(
            "hostname",
            type=str,
            help="Hostname of the SONiC switch to dump configuration",
        )
        return parser

    def take_action(self, parsed_args):
        hostname = parsed_args.hostname

        try:
            # Get device from NetBox
            device = self._get_device_from_netbox(hostname)
            if not device:
                return 1

            # Get device configuration context
            config_context = self._get_config_context(device, hostname)
            if not config_context:
                return 1

            # Print configuration to console (always pretty-printed)
            print(json.dumps(config_context, indent=2))

            return 0

        except Exception as e:
            logger.error(
                f"Error dumping configuration for SONiC device {hostname}: {e}"
            )
            return 1


class List(Command):
    """List SONiC switches with their details"""

    def get_parser(self, prog_name):
        parser = super(List, self).get_parser(prog_name)
        parser.add_argument(
            "device",
            nargs="?",
            default=None,
            type=str,
            help="Optional device name to filter by (same as sonic sync parameter)",
        )
        return parser

    def take_action(self, parsed_args):
        from osism.tasks import conductor
        from osism.tasks.conductor.sonic.constants import SUPPORTED_HWSKUS

        device_name = parsed_args.device

        try:
            task = conductor.get_sonic_devices.delay(device_name=device_name)
            devices = task.wait()

            logger.info(f"Found {len(devices)} devices matching criteria")

            # Prepare table data
            table_data = []
            headers = [
                "Name",
                "Device Role",
                "OOB IP",
                "Primary IP",
                "HWSKU",
                "Version",
                "Provision State",
            ]

            for device in devices:
                name = device.get("name")
                hwsku = device.get("hwsku")

                if hwsku is None:
                    provision_state = "No HWSKU"
                elif hwsku not in SUPPORTED_HWSKUS:
                    provision_state = "Unsupported HWSKU"
                    logger.warning(
                        f"Device {name} has unsupported HWSKU: {hwsku}. "
                        f"Supported HWSKUs: {', '.join(SUPPORTED_HWSKUS)}"
                    )
                else:
                    provision_state = device.get("provision_state") or "N/A"

                table_data.append(
                    [
                        name,
                        device.get("role_name") or "N/A",
                        device.get("oob_ip") or "N/A",
                        device.get("primary_ip") or "N/A",
                        hwsku or "N/A",
                        device.get("version") or "N/A",
                        provision_state,
                    ]
                )

            # Sort by device name
            table_data.sort(key=lambda x: x[0])

            # Print the table
            if table_data:
                print(tabulate(table_data, headers=headers, tablefmt="psql"))
                print(f"\nTotal: {len(table_data)} devices")
            else:
                print("No SONiC devices found matching the criteria")

            return 0

        except Exception as e:
            logger.error(f"Error listing SONiC devices: {e}")
            return 1


class Validate(SonicCommandBase):
    """Validate SONiC config_db.json against the bundled YANG models.

    Configurations can be sourced from a local file, NetBox local context,
    the on-disk export directory, or generated on-the-fly from NetBox.
    """

    def get_parser(self, prog_name):
        parser = super(Validate, self).get_parser(prog_name)
        parser.add_argument(
            "hostname",
            nargs="*",
            default=[],
            type=str,
            help=(
                "One or more hostnames. Required for --from-netbox / --generate; "
                "optional for --from-export-dir (filters by filename)."
            ),
        )
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--file",
            dest="file",
            type=str,
            help="Validate a single config_db.json file at this path.",
        )
        source.add_argument(
            "--from-netbox",
            dest="from_netbox",
            action="store_true",
            help="Validate the sonic_config stored in NetBox local_context_data.",
        )
        source.add_argument(
            "--from-export-dir",
            dest="from_export_dir",
            nargs="?",
            const="",
            default=None,
            help=(
                "Validate config files from the SONiC export directory "
                "(default: SONIC_EXPORT_DIR setting)."
            ),
        )
        source.add_argument(
            "--generate",
            dest="generate",
            action="store_true",
            help="Generate config from NetBox in-memory and validate it.",
        )
        parser.add_argument(
            "--yang-dir",
            dest="yang_dir",
            type=str,
            default=None,
            help="Override YANG model directory (default: SONIC_YANG_MODELS_DIR).",
        )
        parser.add_argument(
            "--format",
            dest="output_format",
            choices=["text", "json"],
            default="text",
            help="Output format (default: text).",
        )
        return parser

    def take_action(self, parsed_args):
        try:
            from osism.tasks.conductor.sonic.validator import (
                ValidatorUnavailable,
                load_yang_context,
                validate_config,
            )
        except ImportError as exc:
            logger.error(f"Validator module unavailable: {exc}")
            return 2

        try:
            ctx = load_yang_context(parsed_args.yang_dir)
        except ValidatorUnavailable as exc:
            logger.error(str(exc))
            return 2
        except Exception as exc:
            logger.error(f"Failed to load YANG models: {exc}")
            return 2

        try:
            sources = self._collect_sources(parsed_args)
        except ValueError as exc:
            logger.error(str(exc))
            return 2

        if not sources:
            logger.error("No configurations found to validate.")
            return 2

        results = []
        worst_rc = 0
        for label, config in sources:
            if config is None:
                results.append((label, None))
                worst_rc = max(worst_rc, 2)
                continue
            result = validate_config(config, ctx=ctx)
            results.append((label, result))
            if not result.valid:
                worst_rc = max(worst_rc, 1)

        if parsed_args.output_format == "json":
            payload = {
                label: (
                    result.to_dict()
                    if result
                    else {
                        "valid": False,
                        "errors": [{"message": "config not available"}],
                    }
                )
                for label, result in results
            }
            print(json.dumps(payload, indent=2))
        else:
            self._print_text_report(results)

        return worst_rc

    def _collect_sources(self, parsed_args):
        """Return a list of (label, config_dict_or_None) tuples to validate."""
        if parsed_args.file:
            with open(parsed_args.file, "r") as fh:
                return [(parsed_args.file, json.load(fh))]

        if parsed_args.from_netbox:
            if not parsed_args.hostname:
                raise ValueError("--from-netbox requires at least one hostname.")
            return [
                (hostname, self._config_from_netbox(hostname))
                for hostname in parsed_args.hostname
            ]

        if parsed_args.from_export_dir is not None:
            from osism import settings

            export_dir = parsed_args.from_export_dir or settings.SONIC_EXPORT_DIR
            return self._configs_from_export_dir(export_dir, parsed_args.hostname)

        if parsed_args.generate:
            if not parsed_args.hostname:
                raise ValueError("--generate requires at least one hostname.")
            return [
                (f"{hostname} (generated)", self._config_from_generate(hostname))
                for hostname in parsed_args.hostname
            ]

        raise ValueError("No configuration source specified.")

    def _config_from_netbox(self, hostname):
        device = self._get_device_from_netbox(hostname)
        if not device:
            return None
        ctx = self._get_config_context(device, hostname)
        if not ctx:
            return None
        config = ctx.get("sonic_config")
        if not config:
            logger.error(
                f"Device {hostname} has no 'sonic_config' in local_context_data."
            )
            return None
        return config

    def _configs_from_export_dir(self, export_dir, hostnames):
        if not os.path.isdir(export_dir):
            raise ValueError(f"Export directory not found: {export_dir}")

        from osism import settings

        prefix = settings.SONIC_EXPORT_PREFIX
        suffix = settings.SONIC_EXPORT_SUFFIX

        wanted = set(hostnames) if hostnames else None
        sources = []
        for name in sorted(os.listdir(export_dir)):
            if not (name.startswith(prefix) and name.endswith(suffix)):
                continue
            identifier = (
                name[len(prefix) : -len(suffix)] if suffix else name[len(prefix) :]
            )
            if wanted is not None and identifier not in wanted:
                continue
            path = os.path.join(export_dir, name)
            try:
                with open(path, "r") as fh:
                    sources.append((path, json.load(fh)))
            except (OSError, json.JSONDecodeError) as exc:
                logger.error(f"Could not read {path}: {exc}")
                sources.append((path, None))
        return sources

    def _config_from_generate(self, hostname):
        from osism.tasks.conductor.sonic.config_generator import generate_sonic_config
        from osism.tasks.conductor.sonic.constants import SUPPORTED_HWSKUS

        device = self._get_device_from_netbox(hostname)
        if not device:
            return None
        hwsku = None
        if (
            hasattr(device, "custom_fields")
            and device.custom_fields.get("sonic_parameters")
            and device.custom_fields["sonic_parameters"].get("hwsku")
        ):
            hwsku = device.custom_fields["sonic_parameters"]["hwsku"]
        if not hwsku:
            logger.error(f"Device {hostname} has no HWSKU configured.")
            return None
        if hwsku not in SUPPORTED_HWSKUS:
            logger.error(
                f"Device {hostname} HWSKU '{hwsku}' is not supported "
                f"(supported: {', '.join(SUPPORTED_HWSKUS)})."
            )
            return None
        config_version = None
        if device.custom_fields.get("sonic_parameters", {}).get("config_version"):
            config_version = device.custom_fields["sonic_parameters"]["config_version"]
        return generate_sonic_config(device, hwsku, None, config_version)

    def _print_text_report(self, results):
        ok = sum(1 for _, r in results if r and r.valid)
        fail = sum(1 for _, r in results if r is None or not r.valid)
        for label, result in results:
            if result is None:
                print(f"[ERROR] {label}: configuration not available")
                continue
            if result.valid:
                print(f"[OK]    {label}")
            else:
                print(f"[FAIL]  {label}: {len(result.errors)} error(s)")
                for err in result.errors:
                    if err.path:
                        print(f"        - {err.message} ({err.path})")
                    else:
                        print(f"        - {err.message}")
        print(f"\nSummary: {ok} valid, {fail} failed, {len(results)} total")
