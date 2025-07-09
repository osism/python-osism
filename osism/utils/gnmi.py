# SPDX-License-Identifier: Apache-2.0

import logging
import time
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class GnmiTelemetryCollector:
    """Collect telemetry data from SONiC switches via gNMI."""

    def __init__(self):
        self.logger = logger

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
            # TODO: Implement actual gNMI client connection
            # For now, return placeholder metrics
            self.logger.warning(
                f"gNMI collection not yet implemented for device {device_name}"
            )

            # Placeholder metrics structure
            metrics = {
                "device_info": {
                    "name": device_name,
                    "ip": device_ip,
                    "collection_time": datetime.now().isoformat(),
                    "status": "placeholder",
                },
                "interfaces": self._get_placeholder_interface_metrics(device_name),
                "system": self._get_placeholder_system_metrics(device_name),
                "bgp": self._get_placeholder_bgp_metrics(device_name),
            }

            return metrics

        except Exception as e:
            self.logger.error(
                f"Error collecting gNMI metrics from {device_name}: {str(e)}"
            )
            raise

    def _get_placeholder_interface_metrics(self, device_name: str) -> Dict[str, Any]:
        """Generate placeholder interface metrics."""
        return {
            "Ethernet0": {
                "admin_status": "UP",
                "oper_status": "UP",
                "in_octets": 1000000,
                "out_octets": 800000,
                "in_pkts": 5000,
                "out_pkts": 4000,
                "in_errors": 0,
                "out_errors": 0,
            },
            "Ethernet1": {
                "admin_status": "UP",
                "oper_status": "DOWN",
                "in_octets": 0,
                "out_octets": 0,
                "in_pkts": 0,
                "out_pkts": 0,
                "in_errors": 0,
                "out_errors": 0,
            },
        }

    def _get_placeholder_system_metrics(self, device_name: str) -> Dict[str, Any]:
        """Generate placeholder system metrics."""
        return {
            "uptime": 86400,  # 1 day in seconds
            "cpu_usage": 25.5,
            "memory_usage": 60.2,
            "temperature": 45.0,
        }

    def _get_placeholder_bgp_metrics(self, device_name: str) -> Dict[str, Any]:
        """Generate placeholder BGP metrics."""
        return {
            "neighbors": {
                "10.1.1.1": {
                    "state": "Established",
                    "uptime": 3600,
                    "received_prefixes": 100,
                    "sent_prefixes": 50,
                },
                "10.1.1.2": {
                    "state": "Idle",
                    "uptime": 0,
                    "received_prefixes": 0,
                    "sent_prefixes": 0,
                },
            }
        }


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
