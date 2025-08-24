# SPDX-License-Identifier: Apache-2.0

"""
Event bridge for sharing events between RabbitMQ listener and WebSocket manager.
This module provides a Redis-based way to forward events from the listener service
to the WebSocket manager across different containers.
"""

import threading
import queue
import logging
import json
import os
from typing import Dict, Any

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger("osism.event_bridge")


class EventBridge:
    """Redis-based bridge for forwarding events between RabbitMQ listener and WebSocket manager across containers."""

    def __init__(self):
        self._event_queue = queue.Queue()
        self._websocket_manager = None
        self._processor_thread = None
        self._subscriber_thread = None
        self._shutdown_event = threading.Event()
        self._redis_client = None
        self._redis_subscriber = None

        # Initialize Redis connection
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection."""
        if not REDIS_AVAILABLE:
            logger.warning(
                "Redis not available - event bridge will use local queue only"
            )
            return

        try:
            redis_host = os.getenv("REDIS_HOST", "redis")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_db = int(os.getenv("REDIS_DB", "0"))

            self._redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=None,  # No timeout for blocking operations
                health_check_interval=30,
            )

            # Test connection
            self._redis_client.ping()
            logger.info(f"Connected to Redis at {redis_host}:{redis_port}")

            # Create subscriber for WebSocket manager (API container)
            self._redis_subscriber = self._redis_client.pubsub()

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis_client = None
            self._redis_subscriber = None

    def set_websocket_manager(self, websocket_manager):
        """Set the WebSocket manager instance and start Redis subscriber."""
        self._websocket_manager = websocket_manager
        logger.info("WebSocket manager connected to event bridge")

        # Start Redis subscriber thread if Redis is available
        if self._redis_client and not self._subscriber_thread:
            self._start_redis_subscriber()

        # Start local processor thread if not already running
        if not self._processor_thread or not self._processor_thread.is_alive():
            self._start_processor_thread()

    def add_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Add an event to be forwarded to WebSocket clients via Redis."""
        try:
            event_data = {"event_type": event_type, "payload": payload}

            if self._redis_client:
                # Publish to Redis for cross-container communication
                try:
                    message = json.dumps(event_data)
                    subscribers = self._redis_client.publish("osism:events", message)
                    logger.info(
                        f"Published event to Redis: {event_type} (subscribers: {subscribers})"
                    )

                    if subscribers == 0:
                        logger.warning(f"No Redis subscribers for event: {event_type}")

                except Exception as redis_error:
                    logger.error(f"Failed to publish event to Redis: {redis_error}")
                    # Try to reconnect Redis
                    try:
                        self._init_redis()
                        if self._redis_client:
                            message = json.dumps(event_data)
                            subscribers = self._redis_client.publish(
                                "osism:events", message
                            )
                            logger.info(
                                f"Published event to Redis after reconnect: {event_type} (subscribers: {subscribers})"
                            )
                        else:
                            raise Exception("Redis reconnection failed")
                    except Exception as reconnect_error:
                        logger.error(f"Redis reconnection failed: {reconnect_error}")
                        # Fallback to local queue
                        self._event_queue.put_nowait(event_data)
                        logger.debug(
                            f"Added event to local fallback queue: {event_type}"
                        )
            else:
                # Local queue fallback
                self._event_queue.put_nowait(event_data)
                logger.debug(f"Added event to local queue: {event_type}")

        except queue.Full:
            logger.warning("Event bridge queue is full, dropping event")
        except Exception as e:
            logger.error(f"Error adding event to bridge: {e}")

    def _start_redis_subscriber(self):
        """Start Redis subscriber thread for receiving events from other containers."""
        self._subscriber_thread = threading.Thread(
            target=self._redis_subscriber_loop, name="RedisEventSubscriber", daemon=True
        )
        self._subscriber_thread.start()
        logger.info("Started Redis event subscriber thread")

    def _start_processor_thread(self):
        """Start the background thread that processes local events."""
        self._processor_thread = threading.Thread(
            target=self._process_events, name="EventBridgeProcessor", daemon=True
        )
        self._processor_thread.start()
        logger.info("Started event bridge processor thread")

    def _redis_subscriber_loop(self):
        """Redis subscriber loop for receiving events from other containers with auto-reconnect."""
        retry_count = 0
        max_retries = 5
        retry_delay = 5  # seconds

        while not self._shutdown_event.is_set() and retry_count < max_retries:
            try:
                if not self._redis_subscriber:
                    logger.error("Redis subscriber not available")
                    return

                logger.info(
                    f"Starting Redis subscriber (attempt {retry_count + 1}/{max_retries})"
                )
                self._redis_subscriber.subscribe("osism:events")
                logger.info("Subscribed to Redis events channel")
                retry_count = 0  # Reset retry count on successful connection

                # Use get_message with timeout instead of listen() to avoid hanging
                while not self._shutdown_event.is_set():
                    try:
                        # Check for messages with timeout
                        message = self._redis_subscriber.get_message(timeout=10.0)

                        if message is None:
                            continue  # Timeout, check shutdown and continue

                        if message["type"] == "message":
                            try:
                                event_data = json.loads(message["data"])
                                logger.info(
                                    f"Received event from Redis: {event_data.get('event_type')}"
                                )

                                if self._websocket_manager:
                                    # Process event directly
                                    self._process_single_event(event_data)
                                else:
                                    # Add to local queue for later processing
                                    self._event_queue.put_nowait(event_data)

                            except json.JSONDecodeError as e:
                                logger.error(
                                    f"Failed to decode Redis event message: {e}"
                                )
                            except Exception as e:
                                logger.error(f"Error processing Redis event: {e}")

                    except Exception as get_msg_error:
                        logger.error(f"Error getting Redis message: {get_msg_error}")
                        break  # Break inner loop to trigger reconnect

            except Exception as e:
                retry_count += 1
                logger.error(
                    f"Redis subscriber error (attempt {retry_count}/{max_retries}): {e}"
                )

                if retry_count < max_retries:
                    logger.info(
                        f"Retrying Redis subscription in {retry_delay} seconds..."
                    )
                    self._shutdown_event.wait(retry_delay)

                    # Recreate Redis connection
                    try:
                        self._init_redis()
                    except Exception as init_error:
                        logger.error(f"Failed to reinitialize Redis: {init_error}")

            finally:
                if self._redis_subscriber:
                    try:
                        self._redis_subscriber.close()
                    except Exception:
                        pass  # Ignore errors during cleanup

        if retry_count >= max_retries:
            logger.error("Max Redis reconnection attempts reached, giving up")
        else:
            logger.info("Redis subscriber stopped")

    def _process_single_event(self, event_data: Dict[str, Any]):
        """Process a single event with WebSocket manager."""
        if not self._websocket_manager:
            logger.warning("No WebSocket manager available, dropping event")
            return

        try:
            import asyncio

            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Process the event
            loop.run_until_complete(
                self._websocket_manager.broadcast_event_from_notification(
                    event_data["event_type"], event_data["payload"]
                )
            )

            loop.close()
            logger.debug(f"Processed event via bridge: {event_data['event_type']}")

        except Exception as e:
            logger.error(f"Error processing event via bridge: {e}")

    def _process_events(self):
        """Background thread that processes events from the local queue."""
        logger.info("Event bridge processor started")

        while not self._shutdown_event.is_set():
            try:
                # Get event with timeout to check shutdown periodically
                try:
                    event_data = self._event_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                self._process_single_event(event_data)
                self._event_queue.task_done()

            except Exception as e:
                logger.error(f"Unexpected error in event bridge processor: {e}")

        logger.info("Event bridge processor stopped")

    def shutdown(self):
        """Shutdown the event bridge."""
        logger.info("Shutting down event bridge")
        self._shutdown_event.set()

        # Close Redis subscriber
        if self._redis_subscriber:
            try:
                self._redis_subscriber.close()
            except Exception as e:
                logger.error(f"Error closing Redis subscriber: {e}")

        # Wait for threads to finish
        if self._processor_thread and self._processor_thread.is_alive():
            self._processor_thread.join(timeout=5.0)

        if self._subscriber_thread and self._subscriber_thread.is_alive():
            self._subscriber_thread.join(timeout=5.0)


# Global event bridge instance
event_bridge = EventBridge()
