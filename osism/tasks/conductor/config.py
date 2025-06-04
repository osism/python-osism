# SPDX-License-Identifier: Apache-2.0

from loguru import logger
import yaml

from osism.tasks import Config, openstack


def get_configuration():
    with open("/etc/conductor.yml") as fp:
        configuration = yaml.load(fp, Loader=yaml.SafeLoader)

        if not configuration:
            logger.warning(
                "The conductor configuration is empty. That's probably wrong"
            )
            return {}

        if Config.enable_ironic.lower() not in ["true", "yes"]:
            return configuration

        if "ironic_parameters" not in configuration:
            logger.error("ironic_parameters not found in the conductor configuration")
            return configuration

        if "driver_info" in configuration["ironic_parameters"]:
            if "deploy_kernel" in configuration["ironic_parameters"]["driver_info"]:
                result = openstack.image_get(
                    configuration["ironic_parameters"]["driver_info"]["deploy_kernel"]
                )
                configuration["ironic_parameters"]["driver_info"][
                    "deploy_kernel"
                ] = result.id

            if "deploy_ramdisk" in configuration["ironic_parameters"]["driver_info"]:
                result = openstack.image_get(
                    configuration["ironic_parameters"]["driver_info"]["deploy_ramdisk"]
                )
                configuration["ironic_parameters"]["driver_info"][
                    "deploy_ramdisk"
                ] = result.id

            if "cleaning_network" in configuration["ironic_parameters"]["driver_info"]:
                result = openstack.network_get(
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
                result = openstack.network_get(
                    configuration["ironic_parameters"]["driver_info"][
                        "provisioning_network"
                    ]
                )
                configuration["ironic_parameters"]["driver_info"][
                    "provisioning_network"
                ] = result.id

        return configuration
