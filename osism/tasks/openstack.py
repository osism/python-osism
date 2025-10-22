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
                logger.info(
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
                logger.info(
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
                logger.info(f"Successfully loaded password for cloud '{cloud}'")
                return password_str
            else:
                logger.warning(
                    f"Password key '{password_key}' is empty after conversion"
                )
                return None
        else:
            logger.warning(f"Password key '{password_key}' not found in secrets file")
            return None

    except Exception as exc:
        logger.error(f"Failed to load/decrypt password for cloud '{cloud}': {exc}")
        return None


def setup_cloud_environment(cloud):
    """
    Set up cloud configuration environment for OpenStack commands.

    Creates secure.yml with cloud password and copies clouds.yaml to /tmp,
    then changes working directory to /tmp.

    Args:
        cloud (str): The cloud profile name

    Returns:
        tuple: (temp_files_to_cleanup, original_cwd, success)
    """
    temp_files_to_cleanup = []
    original_cwd = os.getcwd()

    if not cloud:
        logger.warning("No cloud parameter provided, skipping cloud configuration")
        return temp_files_to_cleanup, original_cwd, False

    password = get_cloud_password(cloud)
    if not password:
        logger.warning(
            f"Could not load password for cloud '{cloud}', skipping cloud configuration"
        )
        return temp_files_to_cleanup, original_cwd, False

    try:
        # Create secure.yml in /tmp
        secure_yml_path = "/tmp/secure.yml"
        secure_yml_content = {"clouds": {cloud: {"auth": {"password": password}}}}

        with open(secure_yml_path, "w") as f:
            yaml.dump(secure_yml_content, f)
        temp_files_to_cleanup.append(secure_yml_path)

        # Try both .yaml and .yml extensions
        if os.path.exists("/etc/openstack/clouds.yaml"):
            shutil.copy2("/etc/openstack/clouds.yaml", "/tmp/clouds.yaml")
            temp_files_to_cleanup.append("/tmp/clouds.yaml")
        elif os.path.exists("/etc/openstack/clouds.yml"):
            shutil.copy2("/etc/openstack/clouds.yml", "/tmp/clouds.yml")
            temp_files_to_cleanup.append("/tmp/clouds.yml")
        else:
            logger.warning("Could not find /etc/openstack/clouds.yaml or clouds.yml")

        # Change working directory to /tmp
        os.chdir("/tmp")

        logger.debug(f"Successfully set up cloud environment for '{cloud}'")
        return temp_files_to_cleanup, original_cwd, True

    except Exception as exc:
        logger.error(f"Failed to set up cloud environment for '{cloud}': {exc}")
        return temp_files_to_cleanup, original_cwd, False


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
    temp_files_to_cleanup, original_cwd, cloud_setup_success = setup_cloud_environment(
        cloud
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
        temp_files_to_cleanup, original_cwd, cloud_setup_success = (
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
    temp_files_to_cleanup, original_cwd, cloud_setup_success = setup_cloud_environment(
        cloud
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
    temp_files_to_cleanup, original_cwd, cloud_setup_success = setup_cloud_environment(
        cloud
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
