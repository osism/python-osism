import logging
import os

from netmiko import ConnectHandler
from paramiko import AutoAddPolicy, SSHClient
from routeros_diff.parser import RouterOSConfig
from scp import SCPClient


def get_netmiko_connection(device):
    parameters = get_parameters(device)
    result = ConnectHandler(device_type="mikrotik_routeros", **parameters)
    return result


def get_scp_connection(device):
    parameters = get_parameters(device)

    ssh_parameters = {
        "hostname": parameters["host"],
        "username": parameters["username"],
        "password": parameters["password"]
    }

    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(**ssh_parameters)
    result = SCPClient(ssh.get_transport())
    return result


def get_configuration(device):
    conn = get_netmiko_connection(device)
    conn.send_command(f"/export file={device.name}")

    scp = get_scp_connection(device)
    scp.get(f"/{device.name}.rsc", f"/tmp/{device.name}.rsc")
    scp.close()

    with open(f"/tmp/{device.name}.rsc", 'r') as fp:
        result = fp.read()

    os.remove(f"/tmp/{device.name}.rsc")

    return result


def get_parameters(device):
    # FIXME: use get_context_data() in the future
    config_context = device.local_context_data

    result = {
        'host': config_context['deployment_address'],
        'username': config_context['deployment_user'],
        'password': config_context['deployment_password']
    }

    return result


def deploy(device, current_configuration, last_configuration):
    if not last_configuration:
        last_configuration = get_configuration(device)

    last = RouterOSConfig.parse(last_configuration)
    current = RouterOSConfig.parse(current_configuration)

    diff = str(current.diff(last))

    if diff:
        for line in diff.split('\n'):
            logging.info(f"diff - {device.name}: {line}")


def diff(device, current_configuration, last_configuration):
    if not last_configuration:
        last_configuration = get_configuration(device)

    last = RouterOSConfig.parse(last_configuration)
    current = RouterOSConfig.parse(current_configuration)

    diff = str(current.diff(last))
    for line in diff.split('\n'):
        logging.info(f"diff - {device.name}: {line}")
