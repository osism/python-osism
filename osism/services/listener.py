import os
import logging

import json
from kombu import BrokerConnection
from kombu import Exchange
from kombu import Queue
from kombu.mixins import ConsumerMixin

from osism import utils
from osism.tasks import netbox, openstack

EXCHANGE_NAME = "ironic"
ROUTING_KEY = "ironic_versioned_notifications.info"
QUEUE_NAME = "osism-listener-ironic"
BROKER_URI = os.getenv("BROKER_URI")

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')


class NotificationsDump(ConsumerMixin):

    def __init__(self, connection):
        self.connection = connection
        return

    def get_consumers(self, consumer, channel):
        exchange = Exchange(EXCHANGE_NAME, type="topic", durable=False)
        queue = Queue(QUEUE_NAME, exchange, routing_key=ROUTING_KEY, durable=False, auto_delete=True, no_ack=True)
        return [consumer(queue, callbacks=[self.on_message])]

    def on_message(self, body, message):
        data = json.loads(body["oslo.message"])
        # logging.info(data)

        event_type = data["event_type"]
        payload = data["payload"]
        object_data = payload["ironic_object.data"]

        name = object_data["name"]

        # https://docs.openstack.org/ironic/latest/admin/notifications.html#available-notifications
        if event_type == "baremetal.node.power_set.end":
            logging.info(f"baremetal.node.power_set.end ## {name} ## {object_data['power_state']}")
            netbox.set_state.delay(name, object_data['power_state'], "power")

        elif event_type == "baremetal.node.maintenance_set.end":
            logging.info(f"baremetal.node.maintenance_set.end ## {name} ## {object_data['maintenance']}")
            netbox.set_maintenance.delay(name, object_data['maintenance'])

        elif event_type == "baremetal.node.provision_set.success":
            logging.info(f"baremetal.node.provision_set.success ## {name} ## {object_data['provision_state']}")
            netbox.set_state.delay(name, object_data['provision_state'], "provision")

        elif event_type == "baremetal.node.provision_set.end":
            logging.info(f"baremetal.node.provision_set.end ## {name} ## {object_data['provision_state']}")
            netbox.set_state.delay(name, object_data['provision_state'], "provision")

        elif event_type == "baremetal.port.create.end":
            logging.info(f"baremetal.port.create.end ## {object_data['uuid']}")
            netbox.update_network_interface_name.delay(object_data["address"])

        elif event_type == "baremetal.port.update.end":
            logging.info(f"baremetal.port.update.end ## {object_data['uuid']}")

            mac_address = object_data["address"]
            interface_a = utils.nb.dcim.interfaces.get(mac_address=mac_address)
            device_a = interface_a.device

            task = openstack.baremetal_get_network_interface_name.delay(device_a.name, mac_address)
            task.wait(timeout=None, interval=0.5)
            network_interface_name = task.get()
            netbox.update_network_interface_name.delay(object_data["address"], network_interface_name)

        else:
            logging.info(f"{event_type} ## {name}")

        logging.info(object_data)


def main():
    with BrokerConnection(BROKER_URI) as connection:
        NotificationsDump(connection).run()


if __name__ == "__main__":
    main()
