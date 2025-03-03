# SPDX-License-Identifier: Apache-2.0

import os
import time
from collections.abc import Callable
from typing import Any

from kombu import Connection, Exchange, Queue
from kombu.mixins import ConsumerMixin
from loguru import logger
import json
import requests

from osism import utils
from osism.tasks import netbox, openstack
from osism import settings

EXCHANGE_NAME = "ironic"
ROUTING_KEY = "ironic_versioned_notifications.info"
QUEUE_NAME = "osism-listener-ironic"
BROKER_URI = os.getenv("BROKER_URI")


class BaremetalEvents:
    # References:
    #
    # * https://docs.openstack.org/ironic/latest/admin/notifications.html#available-notifications
    # * https://docs.openstack.org/ironic/latest/user/states.html
    # * https://docs.openstack.org/ironic/latest/_images/states.svg

    def __init__(self) -> None:
        self._handler: dict[
            str, dict[str, dict[str, dict[str, Callable[[dict[Any, Any]], None]]]]
        ] = {
            "baremetal": {
                "node": {
                    "power_set": {"end": self.node_power_set_end},
                    "power_state_corrected": {
                        "success": self.node_power_state_corrected_success
                    },
                    "maintenance_set": {"end": self.node_maintenance_set_end},
                    "provision_set": {
                        "end": self.node_provision_set_end,
                        "success": self.node_provision_set_success,
                    },
                    "delete": {"end": self.node_delete_end},
                    "create": {"end": self.node_create_end},
                },
                "port": {
                    "create": {"end": self.port_create_end},
                    "update": {"end": self.port_update_end},
                },
            }
        }

    def get_object_data(self, payload: dict[Any, Any]) -> Any:
        return payload["ironic_object.data"]

    def get_handler(self, event_type: str) -> Callable[[dict[Any, Any]], None]:
        event_type_keys = event_type.split(".")
        try:
            handler = self._handler[event_type_keys[0]][event_type_keys[1]][
                event_type_keys[2]
            ][event_type_keys[3]]
        except KeyError:

            def default_handler(payload: dict[Any, Any]) -> None:
                object_data = self.get_object_data(payload)
                name = object_data["name"]
                logger.info(event_type + f" ## {name}")

            handler = default_handler
        return handler

    def node_power_set_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.power_set.end ## {name} ## {object_data['power_state']}"
        )
        netbox.set_state.delay(name, object_data["power_state"], "power")

    def node_power_state_corrected_success(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.power_state_corrected.success ## {name} ## {object_data['power_state']}"
        )
        netbox.set_state.delay(name, object_data["power_state"], "power")

    def node_maintenance_set_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.maintenance_set.end ## {name} ## {object_data['maintenance']}"
        )
        netbox.set_maintenance.delay(name, object_data["maintenance"])

    def node_provision_set_success(self, payload: dict[Any, Any]) -> None:
        # A provision status was successfully set, update it in the netbox
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.provision_set.success ## {name} ## {object_data['provision_state']}"
        )
        netbox.set_state.delay(name, object_data["provision_state"], "provision")

    def node_provision_set_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.provision_set.end ## {name} ## {object_data['provision_state']}"
        )
        netbox.set_state.delay(name, object_data["provision_state"], "provision")

        if (
            object_data["previous_provision_state"] == "inspect wait"
            and object_data["event"] == "done"
        ):
            netbox.set_state.delay(name, "introspected", "introspection")
            openstack.baremetal_set_node_provision_state.delay(name, "provide")

    def port_create_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.port.create.end ## {object_data['uuid']}")

        mac_address = object_data["address"]
        interface_a = utils.nb.dcim.interfaces.get(mac_address=mac_address)
        device_a = interface_a.device

        task = openstack.baremetal_get_network_interface_name.delay(
            device_a.name, mac_address
        )
        task.wait(timeout=None, interval=0.5)
        network_interface_name = task.get()

        netbox.update_network_interface_name.delay(
            object_data["address"], network_interface_name
        )

    def port_update_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.port.update.end ## {object_data['uuid']}")

        mac_address = object_data["address"]
        interface_a = utils.nb.dcim.interfaces.get(mac_address=mac_address)
        device_a = interface_a.device

        task = openstack.baremetal_get_network_interface_name.delay(
            device_a.name, mac_address
        )
        task.wait(timeout=None, interval=0.5)
        network_interface_name = task.get()

        netbox.update_network_interface_name.delay(
            object_data["address"], network_interface_name
        )

    def node_delete_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.node.delete.end ## {name}")

        netbox.set_state.delay(name, "unregistered", "ironic")
        netbox.set_state.delay(name, None, "provision")
        netbox.set_state.delay(name, None, "power")
        netbox.set_state.delay(name, None, "introspection")
        netbox.set_state.delay(name, None, "deployment")

        # remove internal flavor
        openstack.baremetal_delete_internal_flavor.delay(name)

    def node_create_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.node.create.end ## {name}")
        netbox.set_state.delay(name, "registered", "ironic")


class NotificationsDump(ConsumerMixin):
    def __init__(self, connection):
        self.connection = connection
        self.baremetal_events = BaremetalEvents()
        self.osism_api_session: None | requests.Session = None
        self.osism_baremetal_api_url: None | str = None
        if settings.OSISM_API_URL:
            logger.info("Setting up OSISM API")
            self.osism_api_session = requests.Session()
            self.osism_baremetal_api_url = (
                settings.OSISM_API_URL.rstrip("/") + "/notifications/baremetal"
            )
        return

    def get_consumers(self, consumer, channel):
        exchange = Exchange(EXCHANGE_NAME, type="topic", durable=False)
        queue = Queue(
            QUEUE_NAME,
            exchange,
            routing_key=ROUTING_KEY,
            durable=False,
            auto_delete=True,
            no_ack=True,
        )
        return [consumer(queue, callbacks=[self.on_message])]

    def on_message(self, body, message):
        data = json.loads(body["oslo.message"])
        # logger.info(data)

        if self.osism_api_session:
            tries = 1
            max_tries = 3
            while tries <= max_tries:
                logger.info(
                    f"Trying to deliver notification to {self.osism_baremetal_api_url} (Try: {tries}/{max_tries})\n"
                )
                try:
                    response = self.osism_api_session.post(
                        self.osism_baremetal_api_url,
                        timeout=5,
                        json=dict(
                            priority=data["priority"],
                            event_type=data["event_type"],
                            timestamp=data["timestamp"],
                            publisher_id=data["publisher_id"],
                            message_id=data["message_id"],
                            payload=data["payload"],
                        ),
                    )
                    if response.status_code == 204:
                        logger.info(
                            f"Successfully delivered notification to {self.osism_baremetal_api_url} (Try: {tries}/{max_tries})"
                        )
                        break
                    else:
                        response.raise_for_status()
                except requests.ConnectionError:
                    logger.error(f"Error connecting to {self.osism_baremetal_api_url}")
                except requests.Timeout:
                    logger.error(
                        f"Timeout reached while connecting to {self.osism_baremetal_api_url}"
                    )
                except requests.HTTPError as e:
                    logger.error(
                        f"Received HTTP status code {e.response.status_code} while connecting to {self.osism_baremetal_api_url}"
                    )
                    if e.response.status_code <= 500:
                        logger.error(
                            f"Received HTTP status code {e.response.status_code} indicates a client side error, giving up early"
                        )
                        break

                logger.error(
                    f"Failed to deliver notification to {self.osism_baremetal_api_url} ({tries}/{max_tries})"
                )
                tries += 1
                if tries > max_tries:
                    logger.error(
                        f"Giving up delivering notification to {self.osism_baremetal_api_url} with data:\n"
                        + json.dumps(data)
                    )
                else:
                    time.sleep(pow(3, tries - 1))

        else:
            handler = self.baremetal_events.get_handler(data["event_type"])
            handler(data["payload"])

        logger.info(self.baremetal_events.get_object_data(data["payload"]))


def main():
    while True:
        try:
            with Connection(BROKER_URI, connect_timeout=30.0) as connection:
                connection.connect()
                NotificationsDump(connection).run()
        except ConnectionRefusedError:
            logger.error("Connection with broker refused. Retry in 60 seconds.")
            time.sleep(60)


if __name__ == "__main__":
    main()
