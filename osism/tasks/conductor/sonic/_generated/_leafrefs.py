# SPDX-License-Identifier: Apache-2.0
# AUTO-GENERATED — DO NOT EDIT BY HAND.
# Regenerate with: python tools/sonic_yang_to_pydantic.py
# flake8: noqa: E501
"""SONiC ConfigDB cross-table leafref constraints."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class LeafrefConstraint:
    """A leafref from ``source_table.source_field`` to one of ``targets``."""

    source_table: str
    source_field: str
    targets: Tuple[Tuple[str, str], ...]
    is_leaf_list: bool = False
    source_is_simple_key: bool = False


LEAFREFS: Tuple[LeafrefConstraint, ...] = (
    LeafrefConstraint(
        source_table="BGP_GLOBALS",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="BGP_GLOBALS_AF",
        source_field="import_vrf_route_map",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_GLOBALS_AF",
        source_field="route_download_filter",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_GLOBALS_AF_AGGREGATE_ADDR",
        source_field="policy",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_GLOBALS_AF_NETWORK",
        source_field="policy",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_GLOBALS_LISTEN_PREFIX",
        source_field="vrf_name",
        targets=(("BGP_GLOBALS", "vrf_name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR",
        source_field="local_addr",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR",
        source_field="neighbor",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR",
        source_field="vrf_name",
        targets=(("BGP_GLOBALS", "vrf_name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="default_rmap",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="filter_list_in",
        targets=(("AS_PATH_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="filter_list_out",
        targets=(("AS_PATH_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="prefix_list_in",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="prefix_list_out",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="route_map_in",
        targets=(("ROUTE_MAP_SET", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="route_map_out",
        targets=(("ROUTE_MAP_SET", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="unsuppress_map_name",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR_AF",
        source_field="vrf_name",
        targets=(("BGP_GLOBALS", "vrf_name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP",
        source_field="local_addr",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP",
        source_field="vrf_name",
        targets=(("BGP_GLOBALS", "vrf_name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="default_rmap",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="filter_list_in",
        targets=(("AS_PATH_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="filter_list_out",
        targets=(("AS_PATH_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="prefix_list_in",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="prefix_list_out",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="route_map_in",
        targets=(("ROUTE_MAP_SET", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="route_map_out",
        targets=(("ROUTE_MAP_SET", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="unsuppress_map_name",
        targets=(("ROUTE_MAP_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="BGP_PEER_GROUP_AF",
        source_field="vrf_name",
        targets=(("BGP_GLOBALS", "vrf_name"),),
    ),
    LeafrefConstraint(
        source_table="BUFFER_PG",
        source_field="port",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="BUFFER_PG",
        source_field="profile",
        targets=(("BUFFER_PROFILE", "name"),),
    ),
    LeafrefConstraint(
        source_table="BUFFER_PORT_EGRESS_PROFILE_LIST",
        source_field="port",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="BUFFER_PORT_EGRESS_PROFILE_LIST",
        source_field="profile_list",
        targets=(("BUFFER_PROFILE", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BUFFER_PORT_INGRESS_PROFILE_LIST",
        source_field="port",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="BUFFER_PORT_INGRESS_PROFILE_LIST",
        source_field="profile_list",
        targets=(("BUFFER_PROFILE", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="BUFFER_PROFILE",
        source_field="pool",
        targets=(("BUFFER_POOL", "name"),),
    ),
    LeafrefConstraint(
        source_table="BUFFER_QUEUE",
        source_field="port",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="BUFFER_QUEUE",
        source_field="profile",
        targets=(("BUFFER_PROFILE", "name"),),
    ),
    LeafrefConstraint(
        source_table="COPP_TRAP",
        source_field="trap_group",
        targets=(("COPP_GROUP", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ACL_IN",
        source_field="acl_group_id",
        targets=(("DASH_ACL_GROUP", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ACL_IN",
        source_field="eni",
        targets=(("DASH_ENI", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ACL_OUT",
        source_field="acl_group_id",
        targets=(("DASH_ACL_GROUP", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ACL_OUT",
        source_field="eni",
        targets=(("DASH_ENI", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ACL_RULE",
        source_field="acl_group_id",
        targets=(("DASH_ACL_GROUP", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ENI",
        source_field="qos",
        targets=(("DASH_QOS", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ENI",
        source_field="vnet",
        targets=(("DASH_VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_HA_GLOBAL_CONFIG",
        source_field="vnet_name",
        targets=(("VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ROUTE_TABLE",
        source_field="action_type",
        targets=(("DASH_ROUTING_TYPE", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ROUTE_TABLE",
        source_field="appliance",
        targets=(("DASH_APPLIANCE", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ROUTE_TABLE",
        source_field="eni",
        targets=(("DASH_ENI", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_ROUTE_TABLE",
        source_field="vnet",
        targets=(("DASH_VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_VNET_MAPPING_TABLE",
        source_field="routing_type",
        targets=(("DASH_ROUTING_TYPE", "name"),),
    ),
    LeafrefConstraint(
        source_table="DASH_VNET_MAPPING_TABLE",
        source_field="vnet",
        targets=(("DASH_VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="DEVICE_NEIGHBOR",
        source_field="local_port",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="DHCPV4_RELAY",
        source_field="server_vrf",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="DHCPV4_RELAY",
        source_field="source_interface",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="DHCP_SERVER_IPV4",
        source_field="customized_options",
        targets=(("DHCP_SERVER_IPV4_CUSTOMIZED_OPTIONS", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="DHCP_SERVER_IPV4",
        source_field="name",
        targets=(("MID_PLANE_BRIDGE", "bridge"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="DHCP_SERVER_IPV4_PORT",
        source_field="name",
        targets=(("DHCP_SERVER_IPV4", "name"),),
    ),
    LeafrefConstraint(
        source_table="DHCP_SERVER_IPV4_PORT",
        source_field="port",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("DPUS", "midplane_interface"),
        ),
    ),
    LeafrefConstraint(
        source_table="DHCP_SERVER_IPV4_PORT",
        source_field="ranges",
        targets=(("DHCP_SERVER_IPV4_RANGE", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="FG_NHG_MEMBER",
        source_field="FG_NHG",
        targets=(("FG_NHG", "name"),),
    ),
    LeafrefConstraint(
        source_table="FG_NHG_MEMBER",
        source_field="link",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
    ),
    LeafrefConstraint(
        source_table="FG_NHG_PREFIX",
        source_field="FG_NHG",
        targets=(("FG_NHG", "name"),),
    ),
    LeafrefConstraint(
        source_table="HIGH_FREQUENCY_TELEMETRY_GROUP",
        source_field="profile_name",
        targets=(("HIGH_FREQUENCY_TELEMETRY_PROFILE", "name"),),
    ),
    LeafrefConstraint(
        source_table="INTERFACE",
        source_field="name",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="INTERFACE",
        source_field="vnet_name",
        targets=(("VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="INTERFACE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="LLDP_PORT",
        source_field="ifname",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="LOOPBACK_INTERFACE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="MCLAG_DOMAIN",
        source_field="peer_link",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
    ),
    LeafrefConstraint(
        source_table="MCLAG_INTERFACE",
        source_field="if_name",
        targets=(("PORTCHANNEL", "name"),),
    ),
    LeafrefConstraint(
        source_table="MGMT_INTERFACE",
        source_field="name",
        targets=(("MGMT_PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="MIRROR_SESSION",
        source_field="dst_port",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="MIRROR_SESSION",
        source_field="policer",
        targets=(("POLICER", "name"),),
    ),
    LeafrefConstraint(
        source_table="MUX_CABLE",
        source_field="ifname",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="NEIGH",
        source_field="port",
        targets=(("PORTCHANNEL", "name"), ("PORT", "name")),
    ),
    LeafrefConstraint(
        source_table="NTP",
        source_field="src_intf",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
            ("MGMT_PORT", "name"),
        ),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="NTP_SERVER",
        source_field="key",
        targets=(("NTP_KEY", "id"),),
    ),
    LeafrefConstraint(
        source_table="NVGRE_TUNNEL_MAP",
        source_field="tunnel_name",
        targets=(("NVGRE_TUNNEL", "tunnel_name"),),
    ),
    LeafrefConstraint(
        source_table="PBH_HASH",
        source_field="hash_field_list",
        targets=(("PBH_HASH_FIELD", "hash_field_name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="PBH_RULE",
        source_field="hash",
        targets=(("PBH_HASH", "hash_name"),),
    ),
    LeafrefConstraint(
        source_table="PBH_RULE",
        source_field="table_name",
        targets=(("PBH_TABLE", "table_name"),),
    ),
    LeafrefConstraint(
        source_table="PBH_TABLE",
        source_field="interface_list",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="PFC_WD",
        source_field="ifname",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="PORT",
        source_field="macsec",
        targets=(("MACSEC_PROFILE", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORTCHANNEL_INTERFACE",
        source_field="name",
        targets=(("PORTCHANNEL", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="PORTCHANNEL_INTERFACE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORTCHANNEL_MEMBER",
        source_field="name",
        targets=(("PORTCHANNEL", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORTCHANNEL_MEMBER",
        source_field="port",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="dot1p_to_tc_map",
        targets=(("DOT1P_TO_TC_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="dscp_to_tc_map",
        targets=(("DSCP_TO_TC_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="ifname",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="pfc_to_pg_map",
        targets=(("PFC_PRIORITY_TO_PRIORITY_GROUP_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="pfc_to_queue_map",
        targets=(("MAP_PFC_PRIORITY_TO_QUEUE", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="scheduler",
        targets=(("SCHEDULER", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="tc_to_dscp_map",
        targets=(("TC_TO_DSCP_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="tc_to_pg_map",
        targets=(("TC_TO_PRIORITY_GROUP_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_QOS_MAP",
        source_field="tc_to_queue_map",
        targets=(("TC_TO_QUEUE_MAP", "name"),),
    ),
    LeafrefConstraint(
        source_table="PORT_STORM_CONTROL",
        source_field="ifname",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="QUEUE",
        source_field="ifname",
        targets=(("PORT", "name"),),
    ),
    LeafrefConstraint(
        source_table="QUEUE",
        source_field="scheduler",
        targets=(("SCHEDULER", "name"),),
    ),
    LeafrefConstraint(
        source_table="QUEUE",
        source_field="wred_profile",
        targets=(("WRED_PROFILE", "name"),),
    ),
    LeafrefConstraint(
        source_table="RADIUS_SERVER",
        source_field="src_intf",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
            ("MGMT_PORT", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_as_path",
        targets=(("AS_PATH_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_community",
        targets=(("COMMUNITY_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_ext_community",
        targets=(("EXTENDED_COMMUNITY_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_interface",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_ipv6_prefix_set",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_neighbor",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_next_hop_set",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_prefix_set",
        targets=(("PREFIX_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="match_src_vrf",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="set_community_ref",
        targets=(("COMMUNITY_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_MAP",
        source_field="set_ext_community_ref",
        targets=(("EXTENDED_COMMUNITY_SET", "name"),),
    ),
    LeafrefConstraint(
        source_table="ROUTE_REDISTRIBUTE",
        source_field="route_map",
        targets=(("ROUTE_MAP_SET", "name"),),
        is_leaf_list=True,
    ),
    LeafrefConstraint(
        source_table="ROUTE_REDISTRIBUTE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="SFLOW",
        source_field="agent_id",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name"), ("MGMT_PORT", "name")),
    ),
    LeafrefConstraint(
        source_table="SFLOW_SESSION",
        source_field="port",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="SRV6_MY_LOCATORS",
        source_field="vrf",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="SRV6_MY_SIDS",
        source_field="decap_vrf",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="SRV6_MY_SIDS",
        source_field="locator",
        targets=(("SRV6_MY_LOCATORS", "locator_name"),),
    ),
    LeafrefConstraint(
        source_table="SYSLOG_CONFIG_FEATURE",
        source_field="service",
        targets=(("FEATURE", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="SYSLOG_SERVER",
        source_field="vrf",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="TACPLUS",
        source_field="src_intf",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
            ("MGMT_PORT", "name"),
        ),
    ),
    LeafrefConstraint(
        source_table="TUNNEL",
        source_field="src_ip",
        targets=(("PEER_SWITCH", "address_ipv4"),),
    ),
    LeafrefConstraint(
        source_table="VLAN_INTERFACE",
        source_field="name",
        targets=(("VLAN", "name"),),
        source_is_simple_key=True,
    ),
    LeafrefConstraint(
        source_table="VLAN_INTERFACE",
        source_field="vnet_name",
        targets=(("VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="VLAN_INTERFACE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="VLAN_MEMBER",
        source_field="name",
        targets=(("VLAN", "name"),),
    ),
    LeafrefConstraint(
        source_table="VLAN_MEMBER",
        source_field="port",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
    ),
    LeafrefConstraint(
        source_table="VLAN_SUB_INTERFACE",
        source_field="vnet_name",
        targets=(("VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="VLAN_SUB_INTERFACE",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
    ),
    LeafrefConstraint(
        source_table="VNET",
        source_field="vxlan_tunnel",
        targets=(("VXLAN_TUNNEL", "name"),),
    ),
    LeafrefConstraint(
        source_table="VNET_ROUTE_TUNNEL",
        source_field="vnet_name",
        targets=(("VNET", "name"),),
    ),
    LeafrefConstraint(
        source_table="VXLAN_EVPN_NVO",
        source_field="source_vtep",
        targets=(("VXLAN_TUNNEL", "name"),),
    ),
    LeafrefConstraint(
        source_table="VXLAN_TUNNEL_MAP",
        source_field="name",
        targets=(("VXLAN_TUNNEL", "name"),),
    ),
)
