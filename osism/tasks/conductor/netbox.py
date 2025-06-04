# SPDX-License-Identifier: Apache-2.0

from loguru import logger
import yaml

from osism import settings
from osism.tasks import netbox


def get_nb_device_query_list():
    try:
        supported_nb_device_filters = [
            "site",
            "region",
            "site_group",
            "location",
            "rack",
            "tag",
            "state",
        ]
        nb_device_query_list = yaml.safe_load(settings.NETBOX_FILTER_CONDUCTOR)
        if type(nb_device_query_list) is not list:
            raise TypeError
        for nb_device_query in nb_device_query_list:
            if type(nb_device_query) is not dict:
                raise TypeError
            for key in list(nb_device_query.keys()):
                if key not in supported_nb_device_filters:
                    raise ValueError
                # NOTE: Only "location_id" and "rack_id" are supported by netbox
                if key in ["location", "rack"]:
                    value_name = nb_device_query.pop(key, "")
                    if key == "location":
                        value_id = netbox.get_location_id(value_name)
                    elif key == "rack":
                        value_id = netbox.get_rack_id(value_name)
                    if value_id:
                        nb_device_query.update({key + "_id": value_id})
                    else:
                        raise ValueError(f"Invalid name {value_name} for {key}")
    except (yaml.YAMLError, TypeError):
        logger.error(
            f"Setting NETBOX_FILTER_CONDUCTOR needs to be an array of mappings containing supported netbox device filters: {supported_nb_device_filters}"
        )
        nb_device_query_list = []
    except ValueError as exc:
        logger.error(f"Unknown value in NETBOX_FILTER_CONDUCTOR: {exc}")
        nb_device_query_list = []

    return nb_device_query_list
