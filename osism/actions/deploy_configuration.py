import logging

import git
import jinja2
from pottery import Redlock

from osism import utils
from osism.plugins.deployment import routeros


def for_device(name, parameters={}):

    device = utils.nb.dcim.devices.get(name=name)

    if "device_type" not in device.custom_fields or device.custom_fields["device_type"] != "switch":
        return

    if "Managed by OSISM" not in [str(x) for x in device.tags]:
        return

    if "deployment_enabled" in device.custom_fields and not bool(device.custom_fields["deployment_enabled"]):
        return

    # Allow only one change per time
    lock = Redlock(key=f"lock_deploy_{name}", masters={utils.redis}, auto_release_time=120)
    lock.acquire()

    repo = git.Repo.init(path="/state")

    first = False

    if device.name in repo.tags:
        last_commit = repo.commit(device.name)
        current_commit = repo.head.commit
    else:
        first = True
        last_commit = repo.head.commit
        current_commit = repo.head.commit

    if device.name in repo.tags:
        repo.delete_tag(name)

    if not first and last_commit == current_commit:
        logging.info(f"No deployment for device {device.name} required")
    else:

        if not first:
            try:
                last_configuration = repo.git.show(f"{last_commit.hexsha}:{device.name}.cfg.j2")
            except git.exc.GitCommandError:
                last_configuration = None
        else:
            last_configuration = None

        try:
            current_configuration = repo.git.show(f"{current_commit.hexsha}:{device.name}.cfg.j2")
        except git.exc.GitCommandError:
            current_configuration = None

        if not current_configuration:
            logging.error(f"There is now prepared configuration for device {device.name}")
        else:

            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(current_configuration)
            rendered_current_configuration = t.render(**parameters)

            logging.info(f"Deploy configuration for device {device.name}")

            routeros.run(device, rendered_current_configuration, last_configuration)

    repo.create_tag(device.name, current_commit)

    lock.release()
