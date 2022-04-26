import logging

import git
from pottery import Redlock

from osism import utils
from osism.plugins import routeros, routeros_testing


def for_device(name, parameters={}):

    device = utils.nb.dcim.devices.get(name=name)

    if "device_type" not in device.custom_fields or device.custom_fields["device_type"] != "switch":
        return

    if "Managed by OSISM" not in [str(x) for x in device.tags]:
        return

    if "deployment_enabled" in device.custom_fields and not bool(device.custom_fields["deployment_enabled"]):
        return

    if "deployment_type" not in device.custom_fields:
        return

    # Allow only one change per time
    lock = Redlock(key=f"lock_diff_{name}", masters={utils.redis}, auto_release_time=120)
    lock.acquire()

    logging.info(f"Diff configuration for device {device.name} with plugin {device.custom_fields['deployment_type']}")

    if device.custom_fields["deployment_type"] == "routeros":
        current_configuration = routeros.get_configuration(device)
    elif device.custom_fields["deployment_type"] == "routeros_testing":
        current_configuration = routeros_testing.get_configuration(device)
    else:
        logging.error(f"Deployment type x for device {device.name} not supported")
        current_configuration = None

    repo = git.Repo.init(path="/state")

    try:
        last_configuration = repo.git.show(f"{repo.head.commit.hexsha}:{device.name}.cfg.j2")
    except git.exc.GitCommandError:
        last_configuration = None

    if device.custom_fields["deployment_type"] == "routeros":
        routeros.diff(device, last_configuration, current_configuration)
    elif device.custom_fields["deployment_type"] == "routeros_testing":
        routeros_testing.diff(device, last_configuration, current_configuration)
    else:
        logging.error(f"Deployment type x for device {device.name} not supported")

    lock.release()
