# SPDX-License-Identifier: Apache-2.0

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from kombu import Connection, Exchange, Queue
from kombu.mixins import ConsumerMixin
from loguru import logger
import json
import requests

from osism.tasks import netbox
from osism import settings

# Retry interval when exchange doesn't exist yet (in seconds)
EXCHANGE_RETRY_INTERVAL = 60

# Interval for checking for new exchanges after initial connection (in seconds)
EXCHANGE_DISCOVERY_INTERVAL = 60

# Multiple exchanges for different OpenStack services
EXCHANGES_CONFIG = {
    "ironic": {
        "exchange": "ironic",
        "routing_key": "ironic_versioned_notifications.info",
        "queue": "osism-listener-ironic",
    },
    "nova": {
        "exchange": "nova",
        "routing_key": "nova_versioned_notifications.info",
        "queue": "osism-listener-nova",
    },
    "neutron": {
        "exchange": "neutron",
        "routing_key": "neutron_versioned_notifications.info",
        "queue": "osism-listener-neutron",
    },
    "cinder": {
        "exchange": "cinder",
        "routing_key": "cinder_versioned_notifications.info",
        "queue": "osism-listener-cinder",
    },
    "keystone": {
        "exchange": "keystone",
        "routing_key": "keystone_versioned_notifications.info",
        "queue": "osism-listener-keystone",
    },
    "glance": {
        "exchange": "glance",
        "routing_key": "glance_versioned_notifications.info",
        "queue": "osism-listener-glance",
    },
}

# Legacy constants for backward compatibility
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
                        "start": self.node_provision_set_start,
                        "end": self.node_provision_set_end,
                        "success": self.node_provision_set_success,
                    },
                    "delete": {"end": self.node_delete_end},
                    "create": {"end": self.node_create_end},
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
        netbox.set_power_state.delay(name, object_data["power_state"])

    def node_power_state_corrected_success(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.power_state_corrected.success ## {name} ## {object_data['power_state']}"
        )
        netbox.set_power_state.delay(name, object_data["power_state"])

    def node_maintenance_set_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.maintenance_set.end ## {name} ## {object_data['maintenance']}"
        )
        netbox.set_maintenance.delay(name, state=object_data["maintenance"])

    def node_provision_set_success(self, payload: dict[Any, Any]) -> None:
        # A provision status was successfully set, update it in the NetBox
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.provision_set.success ## {name} ## {object_data['provision_state']}"
        )
        netbox.set_provision_state.delay(name, object_data["provision_state"])

    def node_provision_set_start(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.provision_set.start ## {name} ## {object_data['provision_state']}"
        )
        netbox.set_provision_state.delay(name, object_data["provision_state"])

    def node_provision_set_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(
            f"baremetal.node.provision_set.end ## {name} ## {object_data['provision_state']}"
        )
        netbox.set_provision_state.delay(name, object_data["provision_state"])

    def node_delete_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.node.delete.end ## {name}")
        netbox.set_provision_state.delay(name, None)
        netbox.set_power_state.delay(name, None)

    def node_create_end(self, payload: dict[Any, Any]) -> None:
        object_data = self.get_object_data(payload)
        name = object_data["name"]
        logger.info(f"baremetal.node.create.end ## {name}")
        netbox.set_provision_state.delay(name, object_data["provision_state"])
        netbox.set_power_state.delay(name, object_data["power_state"])


class NotificationsDump(ConsumerMixin):
    def __init__(self, connection):
        self.connection = connection
        self.baremetal_events = BaremetalEvents()
        self.osism_api_session: None | requests.Session = None
        self.osism_baremetal_api_url: None | str = None
        self.websocket_manager = None
        self._available_exchanges: dict[str, dict] = {}
        self._discovery_thread: threading.Thread | None = None
        self._stop_discovery = threading.Event()
        self._new_exchanges_found = threading.Event()

        if settings.OSISM_API_URL:
            logger.info("Setting up OSISM API")
            self.osism_api_session = requests.Session()
            self.osism_baremetal_api_url = (
                settings.OSISM_API_URL.rstrip("/") + "/notifications/baremetal"
            )

        # Import event_bridge for WebSocket forwarding
        try:
            from osism.services.event_bridge import event_bridge

            self.event_bridge = event_bridge
            logger.info("Event bridge connected to RabbitMQ listener")
        except ImportError:
            logger.warning("Event bridge not available")
            self.event_bridge = None

        return

    def _get_exchange_properties(self, channel, exchange_name: str) -> dict | None:
        """
        Check if an exchange exists and retrieve its properties.
        Uses passive declaration to check existence without creating the exchange.

        Returns exchange properties dict if exists, None otherwise.
        """
        try:
            # Use exchange_declare with passive=True to check if exchange exists
            # This will raise an exception if the exchange doesn't exist
            channel.exchange_declare(
                exchange=exchange_name,
                type="topic",
                passive=True,
            )
            # Exchange exists, get its properties via RabbitMQ management API
            # or assume topic type since that's what OpenStack uses
            logger.info(f"Exchange '{exchange_name}' exists")
            return {"type": "topic", "durable": True}
        except Exception as e:
            # Exchange doesn't exist
            logger.debug(f"Exchange '{exchange_name}' does not exist: {e}")
            return None

    def _check_for_new_exchanges(self):
        """
        Check for newly available exchanges that aren't yet being consumed.
        Returns True if new exchanges were found.
        """
        new_found = False
        try:
            with self.connection.channel() as channel:
                for service_name, config in EXCHANGES_CONFIG.items():
                    if service_name in self._available_exchanges:
                        # Already consuming this exchange
                        continue
                    exchange_name = config["exchange"]
                    props = self._get_exchange_properties(channel, exchange_name)
                    if props:
                        self._available_exchanges[service_name] = {
                            **config,
                            "exchange_props": props,
                        }
                        logger.info(
                            f"New exchange '{exchange_name}' for {service_name} is now available"
                        )
                        new_found = True
        except Exception as e:
            logger.warning(f"Error checking for new exchanges: {e}")
        return new_found

    def _exchange_discovery_loop(self):
        """
        Background thread that periodically checks for new exchanges.
        When new exchanges are found, signals the main consumer to restart.
        """
        logger.info("Starting exchange discovery thread")
        while not self._stop_discovery.is_set():
            # Wait for the discovery interval
            if self._stop_discovery.wait(timeout=EXCHANGE_DISCOVERY_INTERVAL):
                # Stop was requested
                break

            # Check if all exchanges are already available
            if len(self._available_exchanges) >= len(EXCHANGES_CONFIG):
                logger.info(
                    "All configured exchanges are now available. "
                    "Stopping exchange discovery."
                )
                break

            logger.debug("Checking for new exchanges...")
            if self._check_for_new_exchanges():
                logger.info(
                    "New exchanges found. Signaling consumer restart to add new consumers."
                )
                self._new_exchanges_found.set()
                # Signal the consumer to stop so it can restart with new exchanges
                self.should_stop = True

        logger.info("Exchange discovery thread stopped")

    def _start_exchange_discovery(self):
        """Start the background exchange discovery thread."""
        if len(self._available_exchanges) >= len(EXCHANGES_CONFIG):
            # All exchanges already available, no need for discovery
            logger.info("All exchanges available, skipping discovery thread")
            return

        self._stop_discovery.clear()
        self._discovery_thread = threading.Thread(
            target=self._exchange_discovery_loop,
            name="exchange-discovery",
            daemon=True,
        )
        self._discovery_thread.start()

    def _stop_exchange_discovery(self):
        """Stop the background exchange discovery thread."""
        self._stop_discovery.set()
        if self._discovery_thread and self._discovery_thread.is_alive():
            self._discovery_thread.join(timeout=5)

    def _wait_for_exchanges(self):
        """
        Wait for at least one configured exchange to become available.
        Checks exchanges passively without creating them.
        """
        while not self._available_exchanges:
            logger.info("Checking for available exchanges...")
            self._check_for_new_exchanges()

            if not self._available_exchanges:
                logger.warning(
                    f"No exchanges available yet. Waiting {EXCHANGE_RETRY_INTERVAL} seconds before retry..."
                )
                time.sleep(EXCHANGE_RETRY_INTERVAL)

        logger.info(
            f"Found {len(self._available_exchanges)} available exchange(s): "
            f"{list(self._available_exchanges.keys())}"
        )

    def get_consumers(self, consumer, channel):
        consumers = []

        # Wait for exchanges to be available before creating consumers
        self._wait_for_exchanges()

        # Start background discovery for remaining exchanges
        self._start_exchange_discovery()

        # Create consumers only for available exchanges
        for service_name, config in self._available_exchanges.items():
            try:
                exchange_props = config["exchange_props"]
                # Create exchange object matching the existing exchange properties
                # Use passive=True to ensure we don't try to create/modify the exchange
                exchange = Exchange(
                    config["exchange"],
                    type=exchange_props.get("type", "topic"),
                    durable=exchange_props.get("durable", True),
                    passive=True,
                )
                # Create our own queue bound to the existing exchange
                # Don't set durable explicitly to use RabbitMQ's configured default
                # queue type (e.g., quorum queues in RabbitMQ 4)
                queue = Queue(
                    config["queue"],
                    exchange,
                    routing_key=config["routing_key"],
                    auto_delete=False,
                    no_ack=True,
                )
                consumers.append(consumer(queue, callbacks=[self.on_message]))
                logger.info(
                    f"Configured consumer for {service_name} exchange: {config['exchange']}"
                )
            except Exception as e:
                logger.error(f"Failed to configure consumer for {service_name}: {e}")

        if not consumers:
            logger.error(
                "No consumers could be configured. This should not happen after "
                "waiting for exchanges."
            )

        return consumers

    def on_message(self, body, message):
        data = json.loads(body["oslo.message"])

        # Log event with service type detection
        event_type = data.get("event_type", "")
        service_type = event_type.split(".")[0] if event_type else "unknown"

        # Enhanced logging for different event types
        payload_info = {}
        if "payload" in data:
            payload = data["payload"]

            # Extract relevant info based on service type
            if service_type == "baremetal" and "ironic_object.data" in payload:
                ironic_data = payload["ironic_object.data"]
                payload_info = {
                    k: v
                    for k, v in ironic_data.items()
                    if k in ["name", "provision_state", "power_state"]
                }
            elif service_type in ["compute", "nova"] and "nova_object.data" in payload:
                nova_data = payload["nova_object.data"]
                payload_info = {
                    k: v
                    for k, v in nova_data.items()
                    if k in ["uuid", "host", "state", "task_state"]
                }
            elif service_type in ["network", "neutron"]:
                # Neutron events might have different structures
                payload_info = {"service": "neutron"}
            else:
                # Generic payload info
                payload_info = {"service": service_type}

        logger.debug(f"{event_type}: {payload_info}")
        logger.info(f"Received {service_type} event: {event_type}")

        # Send event to WebSocket clients via event bridge
        if self.event_bridge:
            try:
                logger.debug(f"Forwarding event to WebSocket via bridge: {event_type}")
                self.event_bridge.add_event(data["event_type"], data["payload"])
                logger.debug(f"Successfully forwarded event to bridge: {event_type}")
            except Exception as e:
                logger.error(f"Error forwarding event to bridge: {e}")
                logger.error(
                    f"Event data was: {data['event_type']} - {data.get('payload', {}).get('ironic_object.data', {}).get('name', 'unknown')}"
                )

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


def main():
    # Track available exchanges across restarts
    available_exchanges: dict[str, dict] = {}

    while True:
        try:
            with Connection(BROKER_URI, connect_timeout=30.0) as connection:
                connection.connect()
                consumer = NotificationsDump(connection)
                # Restore previously discovered exchanges
                consumer._available_exchanges = available_exchanges
                consumer.run()
                # Save discovered exchanges for next iteration
                available_exchanges = consumer._available_exchanges
                # Stop discovery thread if running
                consumer._stop_exchange_discovery()

                # Check if we stopped due to new exchanges being found
                if consumer._new_exchanges_found.is_set():
                    logger.info(
                        "Restarting consumer to add new exchange consumers. "
                        f"Total exchanges: {len(available_exchanges)}"
                    )
                    consumer._new_exchanges_found.clear()
                    continue

        except ConnectionRefusedError:
            logger.error("Connection with broker refused. Retry in 60 seconds.")
            time.sleep(60)


if __name__ == "__main__":
    main()
