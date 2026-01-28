# SPDX-License-Identifier: Apache-2.0

from celery import Celery
import os
import shutil
import tempfile
import yaml
from loguru import logger

from osism import utils
from osism.tasks import Config, run_command
from osism.tasks.conductor.utils import get_vault

app = Celery("openstack")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.openstack.image_get")
def image_get(self, image_name):
    conn = utils.get_openstack_connection()
    result = conn.image.find_image(image_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.network_get")
def network_get(self, network_name):
    conn = utils.get_openstack_connection()
    result = conn.network.find_network(network_name)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_create")
def baremetal_node_create(self, node_name, attributes=None):
    if attributes is None:
        attributes = {}
    attributes.update({"name": node_name})
    conn = utils.get_openstack_connection()
    result = conn.baremetal.create_node(**attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_delete")
def baremetal_node_delete(self, node_or_id):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.delete_node(node_or_id)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_update")
def baremetal_node_update(self, node_id_or_name, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.update_node(node_id_or_name, **attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_show")
def baremetal_node_show(self, node_id_or_name, ignore_missing=False):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.find_node(node_id_or_name, ignore_missing)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_list")
def baremetal_node_list(self):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.nodes()
    return list(result)


def get_baremetal_nodes():
    """Get all baremetal nodes with their details.

    This is a generalized function that can be used by both
    CLI commands and API endpoints to retrieve baremetal node information.

    Returns:
        list: List of dictionaries containing node information
    """
    conn = utils.get_openstack_connection()
    nodes = conn.baremetal.nodes(details=True)

    # Convert generator to list and extract relevant fields
    node_list = []
    for node in nodes:
        # OpenStack SDK returns Resource objects, not dicts - use attribute access
        node_info = {
            "uuid": getattr(node, "uuid", None) or getattr(node, "id", None),
            "name": getattr(node, "name", None),
            "power_state": getattr(node, "power_state", None),
            "provision_state": getattr(node, "provision_state", None),
            "maintenance": getattr(node, "maintenance", None),
            "instance_uuid": getattr(node, "instance_uuid", None),
            "driver": getattr(node, "driver", None),
            "resource_class": getattr(node, "resource_class", None),
            "properties": getattr(node, "properties", {}),
            "extra": getattr(node, "extra", {}),
            "last_error": getattr(node, "last_error", None),
            "created_at": getattr(node, "created_at", None),
            "updated_at": getattr(node, "updated_at", None),
        }
        node_list.append(node_info)

    return node_list


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_validate")
def baremetal_node_validate(self, node_id_or_name):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.validate_node(node_id_or_name, required=())
    return result


@app.task(
    bind=True,
    name="osism.tasks.openstack.baremetal_node_wait_for_nodes_provision_state",
)
def baremetal_node_wait_for_nodes_provision_state(self, node_id_or_name, state):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.wait_for_nodes_provision_state([node_id_or_name], state)
    if len(result) > 0:
        return result[0]
    else:
        return None


@app.task(bind=True, name="osism.tasks.openstack.baremetal_node_set_provision_state")
def baremetal_node_set_provision_state(self, node, state):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.set_node_provision_state(node, state)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_list")
def baremetal_port_list(self, details=False, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.ports(details=details, **attributes)
    return list(result)


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_create")
def baremetal_port_create(self, attributes=None):
    if attributes is None:
        attributes = {}
    conn = utils.get_openstack_connection()
    result = conn.baremetal.create_port(**attributes)
    return result


@app.task(bind=True, name="osism.tasks.openstack.baremetal_port_delete")
def baremetal_port_delete(self, port_or_id):
    conn = utils.get_openstack_connection()
    result = conn.baremetal.delete_port(port_or_id)
    return result


def get_cloud_password(cloud):
    """
    Load and decrypt the OpenStack password for a specific cloud profile
    from the secrets.yml file.

    This function supports both encrypted (Ansible Vault) and unencrypted
    secrets files. Encrypted files are decrypted using the vault password,
    while unencrypted files are read directly (development mode fallback).

    Args:
        cloud (str): The cloud profile name

    Returns:
        str: The decrypted password or None if not found/decryptable
    """
    if not cloud:
        logger.warning("No cloud parameter provided for password lookup")
        return None

    secrets_path = "/opt/configuration/environments/openstack/secrets.yml"
    # Replace hyphens with underscores for password key (admin-system -> admin_system)
    cloud_normalized = cloud.replace("-", "_")
    password_key = f"os_password_{cloud_normalized}"

    try:
        # Check if secrets file exists
        if not os.path.exists(secrets_path):
            logger.warning(f"Secrets file not found: {secrets_path}")
            return None

        # Get vault instance for decryption
        vault = get_vault()

        # Load the secrets file
        with open(secrets_path, "rb") as f:
            file_data = f.read()

        decrypted_secrets = None

        # Try to decrypt the file if it's vault encrypted
        try:
            if vault.is_encrypted(file_data):
                # File is encrypted, decrypt it
                decrypted_data = vault.decrypt(file_data).decode()
                logger.debug(f"Successfully decrypted secrets file: {secrets_path}")
            else:
                # File is not encrypted, use as-is
                decrypted_data = file_data.decode()
                logger.debug(
                    f"Secrets file is not encrypted (development mode): {secrets_path}"
                )

            # Parse the YAML content safely
            try:
                decrypted_secrets = yaml.safe_load(decrypted_data)
            except yaml.YAMLError as yaml_exc:
                logger.error(
                    f"Failed to parse YAML content from secrets file: {yaml_exc}"
                )
                return None

        except Exception as decrypt_exc:
            # If decryption fails, try reading as plain YAML (development fallback)
            logger.warning(
                f"Failed to decrypt secrets file, attempting to read as plain YAML: {decrypt_exc}"
            )
            try:
                with open(secrets_path, "r") as f:
                    decrypted_secrets = yaml.safe_load(f)
                logger.debug(
                    f"Successfully loaded unencrypted secrets file (development mode): {secrets_path}"
                )
            except Exception as plain_exc:
                logger.error(f"Failed to read secrets file as plain YAML: {plain_exc}")
                return None

        if not decrypted_secrets or not isinstance(decrypted_secrets, dict):
            logger.warning(
                f"Empty or invalid secrets file after decryption: {secrets_path}"
            )
            return None

        # Extract the password for the specified cloud - validate key format first
        if not password_key.isidentifier() or not password_key.startswith(
            "os_password_"
        ):
            logger.error(f"Invalid password key format: '{password_key}'")
            return None

        password = decrypted_secrets.get(password_key)

        if password is not None:
            # Convert password to string and strip whitespace
            password_str = str(password).strip()
            if password_str:
                logger.debug(f"Successfully loaded password for cloud '{cloud}'")
                return password_str
            else:
                logger.warning(
                    f"Password key '{password_key}' is empty after conversion"
                )
                return None
        else:
            logger.debug(f"Password key '{password_key}' not found in {secrets_path}")
            return None

    except Exception as exc:
        logger.error(f"Failed to load/decrypt password for cloud '{cloud}': {exc}")
        return None


def setup_cloud_environment(cloud):
    """
    Set up cloud configuration environment for OpenStack commands.

    Loads the password for the specified cloud profile. First tries to load
    from secrets.yml using os_password_<cloud> pattern. Falls back to using
    /etc/openstack/secure.yml if it exists (backward compatibility).

    Args:
        cloud (str): The cloud profile name

    Returns:
        tuple: (password, temp_files_to_cleanup, original_cwd, success)
               - password: for direct SDK usage, or None if using secure.yml fallback
               - temp_files_to_cleanup: list of temp files to clean up
               - original_cwd: original working directory
               - success: whether setup succeeded
    """
    temp_files_to_cleanup = []
    original_cwd = os.getcwd()

    if not cloud:
        logger.warning("No cloud parameter provided, skipping cloud configuration")
        return None, temp_files_to_cleanup, original_cwd, False

    # Try new approach: load password from secrets.yml
    password = get_cloud_password(cloud)

    # Fallback: check if /etc/openstack/secure.yml exists (backward compatibility)
    if not password:
        # Check for secure.yml
        if os.path.exists("/etc/openstack/secure.yml"):
            src_secure = "/etc/openstack/secure.yml"
            dst_secure = "/tmp/secure.yml"
        elif os.path.exists("/etc/openstack/secure.yaml"):
            src_secure = "/etc/openstack/secure.yaml"
            dst_secure = "/tmp/secure.yaml"
        else:
            cloud_normalized = cloud.replace("-", "_")
            logger.error(
                f"No credentials found for cloud '{cloud}'. "
                f"Set 'os_password_{cloud_normalized}' in "
                "/opt/configuration/environments/openstack/secrets.yml"
            )
            return None, temp_files_to_cleanup, original_cwd, False

        logger.debug(
            f"Using /opt/configuration/environments/openstack/secure.yml for cloud '{cloud}'"
        )

        # Copy clouds.yaml and secure.yml to /tmp for subprocess-based commands
        try:
            # Copy clouds.yaml
            if os.path.exists("/etc/openstack/clouds.yaml"):
                shutil.copy2("/etc/openstack/clouds.yaml", "/tmp/clouds.yaml")
                temp_files_to_cleanup.append("/tmp/clouds.yaml")
            elif os.path.exists("/etc/openstack/clouds.yml"):
                shutil.copy2("/etc/openstack/clouds.yml", "/tmp/clouds.yml")
                temp_files_to_cleanup.append("/tmp/clouds.yml")

            # Copy secure.yml
            shutil.copy2(src_secure, dst_secure)
            temp_files_to_cleanup.append(dst_secure)

            # Change working directory to /tmp so subprocesses find the config
            os.chdir("/tmp")

            return None, temp_files_to_cleanup, original_cwd, True
        except Exception as exc:
            logger.error(f"Failed to copy config files to /tmp: {exc}")
            return None, temp_files_to_cleanup, original_cwd, False

    # Password found - create temp config for subprocess-based commands
    try:
        # Determine the clouds config file
        if os.path.exists("/etc/openstack/clouds.yaml"):
            src_clouds = "/etc/openstack/clouds.yaml"
            dst_clouds = "/tmp/clouds.yaml"
        elif os.path.exists("/etc/openstack/clouds.yml"):
            src_clouds = "/etc/openstack/clouds.yml"
            dst_clouds = "/tmp/clouds.yml"
        else:
            # No clouds.yaml found - still return password for direct SDK usage
            logger.debug(f"No clouds.yaml found, but password loaded for '{cloud}'")
            return password, temp_files_to_cleanup, original_cwd, True

        # Load the clouds config
        with open(src_clouds, "r") as f:
            clouds_config = yaml.safe_load(f)

        # Inject the password into the cloud profile
        if "clouds" in clouds_config and cloud in clouds_config["clouds"]:
            if "auth" not in clouds_config["clouds"][cloud]:
                clouds_config["clouds"][cloud]["auth"] = {}
            clouds_config["clouds"][cloud]["auth"]["password"] = password
        else:
            logger.warning(f"Cloud profile '{cloud}' not found in clouds config")
            return None, temp_files_to_cleanup, original_cwd, False

        # Write the combined config to /tmp for subprocess-based commands
        with open(dst_clouds, "w") as f:
            yaml.dump(clouds_config, f)
        temp_files_to_cleanup.append(dst_clouds)

        # Create an empty secure.yml in /tmp to prevent SDK from reading
        # /etc/openstack/secure.yml which might have a different (wrong) password
        dst_secure = "/tmp/secure.yml"
        with open(dst_secure, "w") as f:
            yaml.dump({}, f)
        temp_files_to_cleanup.append(dst_secure)

        # Change working directory to /tmp so subprocesses find the config
        os.chdir("/tmp")

        logger.debug(f"Successfully set up cloud environment for '{cloud}'")
        return password, temp_files_to_cleanup, original_cwd, True

    except Exception as exc:
        logger.error(f"Failed to set up cloud environment for '{cloud}': {exc}")
        return None, temp_files_to_cleanup, original_cwd, False


def cleanup_cloud_environment(temp_files_to_cleanup, original_cwd):
    """
    Clean up temporary files and restore working directory.

    Args:
        temp_files_to_cleanup (list): List of temporary files to remove
        original_cwd (str): Original working directory to restore
    """
    # Restore working directory
    try:
        os.chdir(original_cwd)
    except Exception as exc:
        logger.warning(f"Could not restore original working directory: {exc}")

    # Clean up temporary files
    for temp_file in temp_files_to_cleanup:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.debug(f"Cleaned up temporary file: {temp_file}")
        except Exception as exc:
            logger.warning(f"Could not remove temporary file {temp_file}: {exc}")


def get_openstack_connection(cloud, password=None):
    """
    Create an OpenStack connection with proper error handling.

    Tries to connect with the provided password first. If authentication fails
    and a secure.yml exists, falls back to using credentials from secure.yml.

    Args:
        cloud (str): The cloud profile name
        password (str): Optional password to use for authentication

    Returns:
        openstack.Connection: The connection object

    Raises:
        SystemExit: On authentication or configuration errors
    """
    import openstack
    import keystoneauth1.exceptions

    secure_yml_exists = os.path.exists("/etc/openstack/secure.yml") or os.path.exists(
        "/etc/openstack/secure.yaml"
    )

    def try_connect(use_password):
        if use_password:
            return openstack.connect(cloud=cloud, auth={"password": use_password})
        else:
            return openstack.connect(cloud=cloud)

    def test_connection(conn):
        # Test the connection by getting the current project
        conn.current_project
        return conn

    # First attempt: use provided password if available
    if password:
        try:
            conn = try_connect(password)
            return test_connection(conn)
        except keystoneauth1.exceptions.http.Unauthorized:
            if secure_yml_exists:
                logger.debug(
                    f"Password from secrets.yml failed for cloud '{cloud}', "
                    "trying secure.yml fallback"
                )
            else:
                cloud_normalized = cloud.replace("-", "_")
                logger.error(
                    f"Authentication failed for cloud '{cloud}'. "
                    f"Check 'os_password_{cloud_normalized}' in "
                    "/opt/configuration/environments/openstack/secrets.yml"
                )
                raise SystemExit(1)
        except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions as exc:
            logger.error(f"Missing configuration for cloud '{cloud}': {exc}")
            raise SystemExit(1)
        except openstack.exceptions.SDKException as exc:
            logger.error(f"OpenStack SDK error for cloud '{cloud}': {exc}")
            raise SystemExit(1)

    # Second attempt (or first if no password): use secure.yml
    try:
        conn = try_connect(None)
        return test_connection(conn)
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions as exc:
        missing = str(exc)
        cloud_normalized = cloud.replace("-", "_")
        if "password" in missing.lower():
            logger.error(
                f"No password configured for cloud '{cloud}'. "
                f"Set 'os_password_{cloud_normalized}' in "
                "/opt/configuration/environments/openstack/secrets.yml"
            )
        else:
            logger.error(f"Missing configuration for cloud '{cloud}': {exc}")
        raise SystemExit(1)
    except keystoneauth1.exceptions.http.Unauthorized:
        cloud_normalized = cloud.replace("-", "_")
        logger.error(
            f"Authentication failed for cloud '{cloud}'. "
            f"Check 'os_password_{cloud_normalized}' in "
            "/opt/configuration/environments/openstack/secrets.yml"
        )
        raise SystemExit(1)
    except openstack.exceptions.SDKException as exc:
        logger.error(f"OpenStack SDK error for cloud '{cloud}': {exc}")
        raise SystemExit(1)


def run_openstack_command_with_cloud(
    request_id,
    command,
    cloud,
    arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
):
    """
    Execute an OpenStack command with cloud configuration setup.

    Args:
        request_id: Celery request ID
        command (str): Command to execute
        cloud (str): Cloud profile name
        arguments (list): Command arguments
        **kwargs: Additional arguments for run_command

    Returns:
        int: Command return code
    """
    password, temp_files_to_cleanup, original_cwd, cloud_setup_success = (
        setup_cloud_environment(cloud)
    )

    try:
        return run_command(
            request_id,
            command,
            {},
            *arguments,
            publish=publish,
            locking=locking,
            auto_release_time=auto_release_time,
            ignore_env=True,
        )
    finally:
        cleanup_cloud_environment(temp_files_to_cleanup, original_cwd)


@app.task(bind=True, name="osism.tasks.openstack.image_manager")
def image_manager(
    self,
    *arguments,
    configs=None,
    publish=True,
    locking=False,
    auto_release_time=3600,
    cloud=None,
):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    command = "/usr/local/bin/openstack-image-manager"

    if configs:
        # For configs case, we need to handle image directory setup and cloud configuration
        password, temp_files_to_cleanup, original_cwd, cloud_setup_success = (
            setup_cloud_environment(cloud)
        )

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                for config in configs:
                    with tempfile.NamedTemporaryFile(
                        mode="w+", suffix=".yml", dir=temp_dir, delete=False
                    ) as temp_file:
                        temp_file.write(config)

                sanitized_args = [
                    arg for arg in arguments if not arg.startswith("--images=")
                ]

                try:
                    images_index = sanitized_args.index("--images")
                    sanitized_args.pop(images_index)
                    sanitized_args.pop(images_index)
                except ValueError:
                    pass
                sanitized_args.extend(["--images", temp_dir])

                return run_command(
                    self.request.id,
                    command,
                    {},
                    *sanitized_args,
                    publish=publish,
                    locking=locking,
                    auto_release_time=auto_release_time,
                    ignore_env=True,
                )
        finally:
            cleanup_cloud_environment(temp_files_to_cleanup, original_cwd)
    else:
        # Simple case - use the generalized helper
        return run_openstack_command_with_cloud(
            self.request.id,
            command,
            cloud,
            arguments,
            publish=publish,
            locking=locking,
            auto_release_time=auto_release_time,
        )


@app.task(bind=True, name="osism.tasks.openstack.flavor_manager")
def flavor_manager(
    self,
    *arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
    cloud=None,
):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    command = "/usr/local/bin/openstack-flavor-manager"
    return run_openstack_command_with_cloud(
        self.request.id,
        command,
        cloud,
        arguments,
        publish=publish,
        locking=locking,
        auto_release_time=auto_release_time,
    )


@app.task(bind=True, name="osism.tasks.openstack.project_manager")
def project_manager(
    self,
    *arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
    cloud=None,
):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    command = "/usr/local/bin/python3"
    script_path = "/openstack-project-manager/openstack_project_manager/create.py"
    # Prepend script path to arguments
    full_arguments = [script_path] + list(arguments)

    # Setup cloud environment (changes to /tmp)
    password, temp_files_to_cleanup, original_cwd, cloud_setup_success = (
        setup_cloud_environment(cloud)
    )

    try:
        # Change to working directory required by openstack-project-manager
        os.chdir("/openstack-project-manager")

        return run_command(
            self.request.id,
            command,
            {},
            *full_arguments,
            publish=publish,
            locking=locking,
            auto_release_time=auto_release_time,
            ignore_env=True,
        )
    finally:
        cleanup_cloud_environment(temp_files_to_cleanup, original_cwd)


@app.task(bind=True, name="osism.tasks.openstack.project_manager_sync")
def project_manager_sync(
    self,
    *arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
    cloud=None,
):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    command = "/usr/local/bin/python3"
    script_path = "/openstack-project-manager/openstack_project_manager/manage.py"
    # Prepend script path to arguments
    full_arguments = [script_path] + list(arguments)

    # Setup cloud environment (changes to /tmp)
    password, temp_files_to_cleanup, original_cwd, cloud_setup_success = (
        setup_cloud_environment(cloud)
    )

    try:
        # Change to working directory required by openstack-project-manager
        os.chdir("/openstack-project-manager")

        return run_command(
            self.request.id,
            command,
            {},
            *full_arguments,
            publish=publish,
            locking=locking,
            auto_release_time=auto_release_time,
            ignore_env=True,
        )
    finally:
        cleanup_cloud_environment(temp_files_to_cleanup, original_cwd)
