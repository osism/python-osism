import logging

from pottery import Redlock

from osism import utils
from osism.tasks import ansible


def for_device(name):
    device = utils.nb.dcim.devices.get(name=name)

    logging.info(f"Deploy configuration for device {device.name}")

    # Allow only one change per time
    lock = Redlock(key=f"lock_deploy_{device.name}", masters={utils.redis})
    lock.acquire()

    arguments = []
    arguments.append(f"-e device={device.name}")
    arguments.append(f"-l {device.name}")
    ansible.run.delay("netbox", "deploy", arguments)

    lock.release()
