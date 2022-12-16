from celery import Celery
from celery.signals import worker_process_init
import keystoneauth1
from loguru import logger
import openstack
from redis import Redis
import yaml

from osism.tasks import Config

app = Celery("conductor")
app.config_from_object(Config)


configuration = {}
redis = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global configuration
    global redis

    redis = Redis(host="redis", port="6379")

    # Parameters come from the environment, OS_*
    try:
        conn = openstack.connect()
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass

    with open("/etc/conductor.yml") as fp:
        configuration = yaml.load(fp, Loader=yaml.SafeLoader)

        if not configuration:
            logger.warning(
                "The conductor configuration is empty. That's probably wrong"
            )
            return

        # Resolve all IDs in the conductor.yml
        if Config.enable_ironic in ["True", "true", "Yes", "yes"]:

            if "ironic_parameters" not in configuration:
                logger.error(
                    "ironic_parameters not found in the conductor configuration"
                )
                return

            # TODO: use osism.tasks.openstack in the future
            if "driver_info" in configuration["ironic_parameters"]:
                if "deploy_kernel" in configuration["ironic_parameters"]["driver_info"]:
                    result = conn.image.find_image(
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_kernel"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "deploy_kernel"
                    ] = result.id

                if (
                    "deploy_ramdisk"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = conn.image.find_image(
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_ramdisk"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "deploy_ramdisk"
                    ] = result.id

                if (
                    "cleaning_network"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = conn.network.find_network(
                        configuration["ironic_parameters"]["driver_info"][
                            "cleaning_network"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "cleaning_network"
                    ] = result.id

                if (
                    "provisioning_network"
                    in configuration["ironic_parameters"]["driver_info"]
                ):
                    result = conn.network.find_network(
                        configuration["ironic_parameters"]["driver_info"][
                            "provisioning_network"
                        ]
                    )
                    configuration["ironic_parameters"]["driver_info"][
                        "provisioning_network"
                    ] = result.id


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.conductor.get_ironic_parameters")
def get_ironic_parameters(self):
    if "ironic_parameters" in configuration:
        return configuration["ironic_parameters"]

    return {}
