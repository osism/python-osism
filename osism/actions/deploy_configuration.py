from loguru import logger
from pottery import Redlock
import git
import jinja2

from osism import utils


def for_device(name, parameters={}, mode="deploy"):

    device = utils.nb.dcim.devices.get(name=name)

    if (
        "device_type" not in device.custom_fields
        or device.custom_fields["device_type"] != "switch"
    ):
        return

    if "Managed by OSISM" not in [str(x) for x in device.tags]:
        return

    if "deployment_enabled" in device.custom_fields and not bool(
        device.custom_fields["deployment_enabled"]
    ):
        return

    if "deployment_type" not in device.custom_fields:
        return

    # Allow only one change per time
    lock = Redlock(
        key=f"lock_deploy_{name}", masters={utils.redis}, auto_release_time=120
    )
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

    if device.name in repo.tags and mode == "deploy":
        repo.delete_tag(name)

    if not first and last_commit == current_commit and mode == "deploy":
        logger.info(f"No deployment for device {device.name} required")
    else:

        if not first:
            try:
                last_configuration = repo.git.show(
                    f"{last_commit.hexsha}:{device.name}.cfg.j2"
                )
            except git.exc.GitCommandError:
                last_configuration = None
        else:
            last_configuration = None

        try:
            current_configuration = repo.git.show(
                f"{current_commit.hexsha}:{device.name}.cfg.j2"
            )
        except git.exc.GitCommandError:
            current_configuration = None

        if not current_configuration:
            logger.error(
                f"There is now prepared configuration for device {device.name}"
            )
        else:

            t = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(
                current_configuration
            )
            rendered_current_configuration = t.render(**parameters)

            logger.info(
                f"{mode} configuration for device {device.name} with plugin {device.custom_fields['deployment_type']}"
            )

            deployment_type = device.custom_fields["deployment_type"]
            logger.error(
                f"Deployment type {deployment_type} for device {device.name} not supported"
            )

    if mode == "deploy":
        repo.create_tag(device.name, current_commit)

    lock.release()
