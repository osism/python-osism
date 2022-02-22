import os

from netmiko import ConnectHandler
from paramiko import AutoAddPolicy, SSHClient
from routeros_diff.parser import RouterOSConfig
from scp import SCPClient


def get_netmiko_connection(parameters):
    result = ConnectHandler(device_type="mikrotik_routeros", **parameters)
    return result


def get_scp_connection(parameters):

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


def get_last_configuration(name, parameters):
    conn = get_netmiko_connection(parameters)
    conn.send_command(f"/export file={name}")

    scp = get_scp_connection(parameters)
    scp.get(f"/{name}.rsc", f"/tmp/{name}.rsc")
    scp.close()

    with open(f"/tmp/{name}.rsc", 'r') as fp:
        result = fp.read()

    os.remove(f"/tmp/{name}.rsc")

    return result


def run(device, current_configuration, last_configuration):

    # FIXME: use get_context_data() in the future
    config_context = device.local_context_data

    parameters = {
        'host': config_context['deployment_address'],
        'username': config_context['deployment_user'],
        'password': config_context['deployment_password']
    }

    if not last_configuration:
        last_configuration = get_last_configuration(device.name, parameters)

    last = RouterOSConfig.parse(last_configuration)
    current = RouterOSConfig.parse(current_configuration)

    diff = str(current.diff(last))

    if diff:
        conn = get_netmiko_connection(parameters)
        conn.send_config_set(diff.split('\n'))
