# SPDX-License-Identifier: Apache-2.0

from loguru import logger
import validators
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

        if "instance_info" in configuration["ironic_parameters"]:
            if "image_source" in configuration["ironic_parameters"]["instance_info"]:
                image_source = configuration["ironic_parameters"]["instance_info"][
                    "image_source"
                ]
                if not validators.uuid(image_source) and not validators.url(
                    image_source
                ):
                    result = openstack.image_get(image_source)
                    if result:
                        configuration["ironic_parameters"]["instance_info"][
                            "image_source"
                        ] = result.id
                    else:
                        logger.warning(f"Could not resolve image ID for {image_source}")

        if "driver_info" in configuration["ironic_parameters"]:
            if "deploy_kernel" in configuration["ironic_parameters"]["driver_info"]:
                deploy_kernel = configuration["ironic_parameters"]["driver_info"][
                    "deploy_kernel"
                ]
                if not validators.uuid(deploy_kernel) and not validators.url(
                    deploy_kernel
                ):
                    result = openstack.image_get(deploy_kernel)
                    if result:
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_kernel"
                        ] = result.id
                    else:
                        logger.warning(
                            f"Could not resolve image ID for {deploy_kernel}"
                        )

            if "deploy_ramdisk" in configuration["ironic_parameters"]["driver_info"]:
                deploy_ramdisk = configuration["ironic_parameters"]["driver_info"][
                    "deploy_ramdisk"
                ]
                if not validators.uuid(deploy_ramdisk) and not validators.url(
                    deploy_ramdisk
                ):
                    result = openstack.image_get(deploy_ramdisk)
                    if result:
                        configuration["ironic_parameters"]["driver_info"][
                            "deploy_ramdisk"
                        ] = result.id
                    else:
                        logger.warning(
                            f"Could not resolve image ID for {deploy_ramdisk}"
                        )

            if "cleaning_network" in configuration["ironic_parameters"]["driver_info"]:
                cleaning_network = configuration["ironic_parameters"]["driver_info"][
                    "cleaning_network"
                ]
                result = openstack.network_get(cleaning_network)
                if result:
                    configuration["ironic_parameters"]["driver_info"][
                        "cleaning_network"
                    ] = result.id
                else:
                    logger.warning(
                        f"Could not resolve network ID for {cleaning_network}"
                    )

            if (
                "provisioning_network"
                in configuration["ironic_parameters"]["driver_info"]
            ):
                provisioning_network = configuration["ironic_parameters"][
                    "driver_info"
                ]["provisioning_network"]
                result = openstack.network_get(provisioning_network)
                if result:
                    configuration["ironic_parameters"]["driver_info"][
                        "provisioning_network"
                    ] = result.id
                else:
                    logger.warning(
                        f"Could not resolve network ID for {provisioning_network}"
                    )

        return configuration
