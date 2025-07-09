# SPDX-License-Identifier: Apache-2.0

import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

from pygnmi import gNMIclient


logger = logging.getLogger(__name__)


class GnmiTelemetryCollector:
    """Collect telemetry data from SONiC switches via gNMI."""

    def __init__(self, port: int = 9339, timeout: int = 30):
        self.logger = logger
        self.port = port
        self.timeout = timeout
        self.client: Optional[gNMIclient] = None

    def collect_metrics(
        self,
        device_name: str,
        device_ip: str,
        username: str = "admin",
        password: str = "",
    ) -> Dict[str, Any]:
        """
        Collect telemetry metrics from a SONiC device via gNMI.

        Args:
            device_name: Name of the device in NetBox
            device_ip: IP address of the device
            username: Username for gNMI authentication
            password: Password for gNMI authentication

        Returns:
            Dictionary containing collected metrics
        """
        try:
            # Connect to gNMI server
            self._connect(device_ip, username, password)

            # Collect actual metrics
            metrics = {
                "device_info": {
                    "name": device_name,
                    "ip": device_ip,
                    "collection_time": datetime.now().isoformat(),
                    "status": "success",
                },
                "interfaces": self._collect_interface_metrics(),
                "system": self._collect_system_metrics(),
                "bgp": self._collect_bgp_metrics(),
            }

            self.logger.info(f"Successfully collected gNMI metrics from {device_name}")
            return metrics

        except Exception as e:
            self.logger.error(
                f"Error collecting gNMI metrics from {device_name}: {str(e)}"
            )
            raise
        finally:
            self._disconnect()

    def _connect(self, device_ip: str, username: str, password: str) -> None:
        """Establish gNMI connection to the device."""
        try:
            self.client = gNMIclient(
                target=(device_ip, self.port),
                username=username,
                password=password,
                timeout=self.timeout,
                insecure=True,  # For SONiC switches without TLS
            )
            if self.client is None:
                raise RuntimeError("Failed to create gNMI client")
            self.client.connect()
            self.logger.debug(f"Connected to gNMI server at {device_ip}:{self.port}")
        except Exception as e:
            self.logger.error(f"Failed to connect to gNMI server: {str(e)}")
            raise

    def _disconnect(self) -> None:
        """Close gNMI connection."""
        if self.client:
            try:
                self.client.close()
                self.logger.debug("Disconnected from gNMI server")
            except Exception as e:
                self.logger.warning(f"Error disconnecting from gNMI server: {str(e)}")
            finally:
                self.client = None

    def _collect_interface_metrics(self) -> Dict[str, Any]:
        """Collect interface metrics via gNMI."""
        interfaces = {}

        try:
            # Get interface list using pygnmi
            interface_paths = [
                "/openconfig-interfaces:interfaces/interface[name=*]/name",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/admin-status",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/oper-status",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/in-octets",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/out-octets",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/in-pkts",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/out-pkts",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/in-errors",
                "/openconfig-interfaces:interfaces/interface[name=*]/state/counters/out-errors",
            ]

            assert self.client is not None, "gNMI client is not connected"
            result = self.client.get(path=interface_paths)

            if result:
                for path, value in result.items():
                    if "/interface[name=" in path:
                        # Extract interface name from path
                        interface_name = path.split("/interface[name=")[1].split("]")[0]

                        if interface_name not in interfaces:
                            interfaces[interface_name] = {
                                "admin_status": "DOWN",
                                "oper_status": "DOWN",
                                "in_octets": 0,
                                "out_octets": 0,
                                "in_pkts": 0,
                                "out_pkts": 0,
                                "in_errors": 0,
                                "out_errors": 0,
                            }

                        # Map values to interface metrics
                        if "/state/admin-status" in path:
                            interfaces[interface_name]["admin_status"] = (
                                "UP" if value == "UP" else "DOWN"
                            )
                        elif "/state/oper-status" in path:
                            interfaces[interface_name]["oper_status"] = (
                                "UP" if value == "UP" else "DOWN"
                            )
                        elif "/state/counters/in-octets" in path:
                            interfaces[interface_name]["in_octets"] = (
                                int(value) if value else 0
                            )
                        elif "/state/counters/out-octets" in path:
                            interfaces[interface_name]["out_octets"] = (
                                int(value) if value else 0
                            )
                        elif "/state/counters/in-pkts" in path:
                            interfaces[interface_name]["in_pkts"] = (
                                int(value) if value else 0
                            )
                        elif "/state/counters/out-pkts" in path:
                            interfaces[interface_name]["out_pkts"] = (
                                int(value) if value else 0
                            )
                        elif "/state/counters/in-errors" in path:
                            interfaces[interface_name]["in_errors"] = (
                                int(value) if value else 0
                            )
                        elif "/state/counters/out-errors" in path:
                            interfaces[interface_name]["out_errors"] = (
                                int(value) if value else 0
                            )

            return interfaces

        except Exception as e:
            self.logger.error(f"Error collecting interface metrics: {str(e)}")
            raise

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system metrics via gNMI."""
        try:
            # System metrics paths using pygnmi
            system_paths = [
                "/openconfig-system:system/state/boot-time",
                "/openconfig-system:system/cpus/cpu[index=*]/state/total/utilization",
                "/openconfig-system:system/memory/state/utilization",
            ]

            assert self.client is not None, "gNMI client is not connected"
            result = self.client.get(path=system_paths)

            metrics = {
                "uptime": 0,
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "temperature": 0.0,  # Placeholder - may need different path
            }

            current_time = time.time()

            if result:
                for path, value in result.items():
                    if "/state/boot-time" in path and value:
                        boot_time = (
                            int(value) / 1000000000
                        )  # Convert nanoseconds to seconds
                        metrics["uptime"] = int(current_time - boot_time)
                    elif "/state/total/utilization" in path and value:
                        metrics["cpu_usage"] = float(value)
                    elif "/memory/state/utilization" in path and value:
                        metrics["memory_usage"] = float(value)

            return metrics

        except Exception as e:
            self.logger.error(f"Error collecting system metrics: {str(e)}")
            raise

    def _collect_bgp_metrics(self) -> Dict[str, Any]:
        """Collect BGP metrics via gNMI."""
        try:
            # BGP neighbors paths using pygnmi
            bgp_paths = [
                "/openconfig-bgp:bgp/neighbors/neighbor[neighbor-address=*]/state/session-state",
                "/openconfig-bgp:bgp/neighbors/neighbor[neighbor-address=*]/state/uptime",
                "/openconfig-bgp:bgp/neighbors/neighbor[neighbor-address=*]/state/received-prefixes",
                "/openconfig-bgp:bgp/neighbors/neighbor[neighbor-address=*]/state/sent-prefixes",
            ]

            assert self.client is not None, "gNMI client is not connected"
            result = self.client.get(path=bgp_paths)
            neighbors = {}

            if result:
                for path, value in result.items():
                    if "/neighbor[neighbor-address=" in path:
                        # Extract neighbor address from path
                        neighbor_ip = path.split("/neighbor[neighbor-address=")[
                            1
                        ].split("]")[0]

                        if neighbor_ip not in neighbors:
                            neighbors[neighbor_ip] = {
                                "state": "Idle",
                                "uptime": 0,
                                "received_prefixes": 0,
                                "sent_prefixes": 0,
                            }

                        # Map values to BGP metrics
                        if "/state/session-state" in path and value:
                            neighbors[neighbor_ip]["state"] = value
                        elif "/state/uptime" in path and value:
                            neighbors[neighbor_ip]["uptime"] = int(value)
                        elif "/state/received-prefixes" in path and value:
                            neighbors[neighbor_ip]["received_prefixes"] = int(value)
                        elif "/state/sent-prefixes" in path and value:
                            neighbors[neighbor_ip]["sent_prefixes"] = int(value)

            return {"neighbors": neighbors}

        except Exception as e:
            self.logger.error(f"Error collecting BGP metrics: {str(e)}")
            raise


def format_prometheus_metrics(metrics: Dict[str, Any]) -> str:
    """
    Format collected metrics into Prometheus exposition format.

    Args:
        metrics: Dictionary containing collected metrics

    Returns:
        String in Prometheus exposition format
    """
    lines = []
    device_name = metrics.get("device_info", {}).get("name", "unknown")
    collection_time = time.time()

    # Device info
    lines.append("# HELP sonic_device_info Device information")
    lines.append("# TYPE sonic_device_info gauge")
    lines.append(f'sonic_device_info{{device="{device_name}"}} 1')
    lines.append("")

    # Collection timestamp
    lines.append(
        "# HELP sonic_collection_timestamp_seconds Unix timestamp of metrics collection"
    )
    lines.append("# TYPE sonic_collection_timestamp_seconds gauge")
    lines.append(f"sonic_collection_timestamp_seconds {collection_time}")
    lines.append("")

    # Interface metrics
    if "interfaces" in metrics:
        # Interface admin status
        lines.append(
            "# HELP sonic_interface_admin_status Interface administrative status (1=UP, 0=DOWN)"
        )
        lines.append("# TYPE sonic_interface_admin_status gauge")
        for iface, data in metrics["interfaces"].items():
            status = 1 if data.get("admin_status") == "UP" else 0
            lines.append(
                f'sonic_interface_admin_status{{device="{device_name}",interface="{iface}"}} {status}'
            )
        lines.append("")

        # Interface operational status
        lines.append(
            "# HELP sonic_interface_oper_status Interface operational status (1=UP, 0=DOWN)"
        )
        lines.append("# TYPE sonic_interface_oper_status gauge")
        for iface, data in metrics["interfaces"].items():
            status = 1 if data.get("oper_status") == "UP" else 0
            lines.append(
                f'sonic_interface_oper_status{{device="{device_name}",interface="{iface}"}} {status}'
            )
        lines.append("")

        # Interface counters
        counter_metrics = [
            ("in_octets", "Input octets"),
            ("out_octets", "Output octets"),
            ("in_pkts", "Input packets"),
            ("out_pkts", "Output packets"),
            ("in_errors", "Input errors"),
            ("out_errors", "Output errors"),
        ]

        for metric_name, description in counter_metrics:
            lines.append(f"# HELP sonic_interface_{metric_name}_total {description}")
            lines.append(f"# TYPE sonic_interface_{metric_name}_total counter")
            for iface, data in metrics["interfaces"].items():
                value = data.get(metric_name, 0)
                lines.append(
                    f'sonic_interface_{metric_name}_total{{device="{device_name}",interface="{iface}"}} {value}'
                )
            lines.append("")

    # System metrics
    if "system" in metrics:
        system_data = metrics["system"]

        # Uptime
        if "uptime" in system_data:
            lines.append("# HELP sonic_system_uptime_seconds System uptime in seconds")
            lines.append("# TYPE sonic_system_uptime_seconds gauge")
            lines.append(
                f'sonic_system_uptime_seconds{{device="{device_name}"}} {system_data["uptime"]}'
            )
            lines.append("")

        # CPU usage
        if "cpu_usage" in system_data:
            lines.append("# HELP sonic_system_cpu_usage_percent CPU usage percentage")
            lines.append("# TYPE sonic_system_cpu_usage_percent gauge")
            lines.append(
                f'sonic_system_cpu_usage_percent{{device="{device_name}"}} {system_data["cpu_usage"]}'
            )
            lines.append("")

        # Memory usage
        if "memory_usage" in system_data:
            lines.append(
                "# HELP sonic_system_memory_usage_percent Memory usage percentage"
            )
            lines.append("# TYPE sonic_system_memory_usage_percent gauge")
            lines.append(
                f'sonic_system_memory_usage_percent{{device="{device_name}"}} {system_data["memory_usage"]}'
            )
            lines.append("")

        # Temperature
        if "temperature" in system_data:
            lines.append(
                "# HELP sonic_system_temperature_celsius System temperature in Celsius"
            )
            lines.append("# TYPE sonic_system_temperature_celsius gauge")
            lines.append(
                f'sonic_system_temperature_celsius{{device="{device_name}"}} {system_data["temperature"]}'
            )
            lines.append("")

    # BGP metrics
    if "bgp" in metrics and "neighbors" in metrics["bgp"]:
        lines.append(
            "# HELP sonic_bgp_neighbor_state BGP neighbor state (1=Established, 0=Other)"
        )
        lines.append("# TYPE sonic_bgp_neighbor_state gauge")
        for neighbor_ip, neighbor_data in metrics["bgp"]["neighbors"].items():
            state = 1 if neighbor_data.get("state") == "Established" else 0
            lines.append(
                f'sonic_bgp_neighbor_state{{device="{device_name}",neighbor="{neighbor_ip}"}} {state}'
            )
        lines.append("")

        lines.append(
            "# HELP sonic_bgp_neighbor_uptime_seconds BGP neighbor uptime in seconds"
        )
        lines.append("# TYPE sonic_bgp_neighbor_uptime_seconds gauge")
        for neighbor_ip, neighbor_data in metrics["bgp"]["neighbors"].items():
            uptime = neighbor_data.get("uptime", 0)
            lines.append(
                f'sonic_bgp_neighbor_uptime_seconds{{device="{device_name}",neighbor="{neighbor_ip}"}} {uptime}'
            )
        lines.append("")

        lines.append(
            "# HELP sonic_bgp_neighbor_received_prefixes_total BGP prefixes received from neighbor"
        )
        lines.append("# TYPE sonic_bgp_neighbor_received_prefixes_total counter")
        for neighbor_ip, neighbor_data in metrics["bgp"]["neighbors"].items():
            prefixes = neighbor_data.get("received_prefixes", 0)
            lines.append(
                f'sonic_bgp_neighbor_received_prefixes_total{{device="{device_name}",neighbor="{neighbor_ip}"}} {prefixes}'
            )
        lines.append("")

        lines.append(
            "# HELP sonic_bgp_neighbor_sent_prefixes_total BGP prefixes sent to neighbor"
        )
        lines.append("# TYPE sonic_bgp_neighbor_sent_prefixes_total counter")
        for neighbor_ip, neighbor_data in metrics["bgp"]["neighbors"].items():
            prefixes = neighbor_data.get("sent_prefixes", 0)
            lines.append(
                f'sonic_bgp_neighbor_sent_prefixes_total{{device="{device_name}",neighbor="{neighbor_ip}"}} {prefixes}'
            )
        lines.append("")

    return "\n".join(lines)
