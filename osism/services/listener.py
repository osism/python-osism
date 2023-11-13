# SPDX-License-Identifier: Apache-2.0

import os
import time

from kombu import Connection, Exchange, Queue
from kombu.mixins import ConsumerMixin
from loguru import logger
import json

from osism import utils
from osism.tasks import netbox, openstack

EXCHANGE_NAME = "ironic"
ROUTING_KEY = "ironic_versioned_notifications.info"
QUEUE_NAME = "osism-listener-ironic"
BROKER_URI = os.getenv("BROKER_URI")


class NotificationsDump(ConsumerMixin):
    def __init__(self, connection):
        self.connection = connection
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

        event_type = data["event_type"]
        payload = data["payload"]
        object_data = payload["ironic_object.data"]

        name = object_data["name"]

        # References:
        #
        # * https://docs.openstack.org/ironic/latest/admin/notifications.html#available-notifications
        # * https://docs.openstack.org/ironic/latest/user/states.html
        # * https://docs.openstack.org/ironic/latest/_images/states.svg

        if event_type == "baremetal.node.power_set.end":
            logger.info(
                f"baremetal.node.power_set.end ## {name} ## {object_data['power_state']}"
            )
            netbox.set_state.delay(name, object_data["power_state"], "power")

        elif event_type == "baremetal.node.power_state_corrected.success":
            logger.info(
                f"baremetal.node.power_state_corrected.success ## {name} ## {object_data['power_state']}"
            )
            netbox.set_state.delay(name, object_data["power_state"], "power")

        elif event_type == "baremetal.node.maintenance_set.end":
            logger.info(
                f"baremetal.node.maintenance_set.end ## {name} ## {object_data['maintenance']}"
            )
            netbox.set_maintenance.delay(name, object_data["maintenance"])

        elif event_type == "baremetal.node.provision_set.start":
            logger.info(
                f"baremetal.node.provision_set.start ## {name} ## {object_data['provision_state']}"
            )

            if object_data["event"] == "inspect":
                # system should be in state a
                netbox.connect.delay(name, "a")

            if object_data["provision_state"] == "cleaning":
                # system should be in state b
                netbox.connect.delay(name, "b")

            if object_data["provision_state"] == "available":
                # system should be in state c
                netbox.connect.delay(name, "c")

            if object_data["target_provision_state"] == "active":
                pass

        # A provision status was successfully set, update it in the netbox
        elif event_type == "baremetal.node.provision_set.success":
            logger.info(
                f"baremetal.node.provision_set.success ## {name} ## {object_data['provision_state']}"
            )
            netbox.set_state.delay(name, object_data["provision_state"], "provision")

            if object_data["provision_state"] == "manageable":
                # system should be in state c
                netbox.connect.delay(name, "c")

        elif event_type == "baremetal.node.provision_set.end":
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

            elif object_data["previous_provision_state"] == "wait call-back":
                pass

            elif (
                object_data["previous_provision_state"] == "cleaning"
                and object_data["provision_state"] == "available"
            ):  # noqa
                # system should be in state c
                netbox.connect.delay(name, "c")

        elif event_type == "baremetal.port.create.end":
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

        elif event_type == "baremetal.port.update.end":
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

        elif event_type == "baremetal.node.delete.end":
            logger.info(f"baremetal.node.delete.end ## {name}")

            netbox.set_state.delay(name, "unregistered", "ironic")
            netbox.set_state.delay(name, None, "provision")
            netbox.set_state.delay(name, None, "power")
            netbox.set_state.delay(name, None, "introspection")
            netbox.set_state.delay(name, None, "deployment")

            # system should be in state a
            netbox.connect.delay(name, "a")

            # remove internal flavor
            openstack.baremetal_delete_internal_flavor.delay(name)

        elif event_type == "baremetal.node.create.end":
            logger.info(f"baremetal.node.create.end ## {name}")
            netbox.set_state.delay(name, "registered", "ironic")

        else:
            logger.info(f"{event_type} ## {name}")

        logger.info(object_data)


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
