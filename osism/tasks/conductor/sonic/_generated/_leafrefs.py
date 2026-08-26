# SPDX-License-Identifier: Apache-2.0
# AUTO-GENERATED — DO NOT EDIT BY HAND.
# Regenerate with: python tools/sonic_yang_to_pydantic.py
# flake8: noqa: E501
"""SONiC ConfigDB cross-table leafref constraints."""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class LeafrefConstraint:
    """A leafref from ``source_table.source_field`` to one of ``targets``.

    ``plain_arms`` holds the non-leafref arms of a YANG union, as anchored
    regexes. A union accepts a value if any arm does, so a value matching
    one of these is legal without resolving to a target; an arm matches
    when every pattern in it matches.
    """

    source_table: str
    source_field: str
    targets: Tuple[Tuple[str, str], ...]
    is_leaf_list: bool = False
    source_is_simple_key: bool = False
    plain_arms: Tuple[Tuple[str, ...], ...] = ()
    element_delimiter: Optional[str] = None


LEAFREFS: Tuple[LeafrefConstraint, ...] = (
    LeafrefConstraint(
        source_table="BGP_GLOBALS",
        source_field="vrf_name",
        targets=(("VRF", "name"),),
        source_is_simple_key=True,
        plain_arms=(("\\A(?:default)\\z",),),
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
        plain_arms=(
            (
                "\\A(?:(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?)\\z",
            ),
            (
                "\\A(?:((:|[0-9a-fA-F]{0,4}):)([0-9a-fA-F]{0,4}:){0,5}((([0-9a-fA-F]{0,4}:)?(:|[0-9a-fA-F]{0,4}))|(((25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])))(%[\\p{N}\\p{L}]+)?)\\z",
                "\\A(?:(([^:]+:){6}(([^:]+:[^:]+)|(.*\\..*)))|((([^:]+:)*[^:]+)?::(([^:]+:)*[^:]+)?)(%.+)?)\\z",
            ),
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
        ),
    ),
    LeafrefConstraint(
        source_table="BGP_NEIGHBOR",
        source_field="neighbor",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name")),
        plain_arms=(
            (
                "\\A(?:(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?)\\z",
            ),
            (
                "\\A(?:((:|[0-9a-fA-F]{0,4}):)([0-9a-fA-F]{0,4}:){0,5}((([0-9a-fA-F]{0,4}:)?(:|[0-9a-fA-F]{0,4}))|(((25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])))(%[\\p{N}\\p{L}]+)?)\\z",
                "\\A(?:(([^:]+:){6}(([^:]+:[^:]+)|(.*\\..*)))|((([^:]+:)*[^:]+)?::(([^:]+:)*[^:]+)?)(%.+)?)\\z",
            ),
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
        ),
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
        plain_arms=(
            (
                "\\A(?:(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?)\\z",
            ),
            (
                "\\A(?:((:|[0-9a-fA-F]{0,4}):)([0-9a-fA-F]{0,4}:){0,5}((([0-9a-fA-F]{0,4}:)?(:|[0-9a-fA-F]{0,4}))|(((25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])))(%[\\p{N}\\p{L}]+)?)\\z",
                "\\A(?:(([^:]+:){6}(([^:]+:[^:]+)|(.*\\..*)))|((([^:]+:)*[^:]+)?::(([^:]+:)*[^:]+)?)(%.+)?)\\z",
            ),
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
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
        plain_arms=(("\\A(?:NULL)\\z",),),
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
        element_delimiter=",",
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
        element_delimiter=",",
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
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
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
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
        ),
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
        plain_arms=(("\\A(?:CPU)\\z",),),
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
        plain_arms=(("\\A(?:Vlan[0-9]+)\\z",),),
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
        plain_arms=(("\\A(?:eth0)\\z",),),
        element_delimiter=";",
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
        plain_arms=(("\\A(?:GLOBAL)\\z",),),
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
        plain_arms=(("\\A(?:global)\\z",),),
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
        plain_arms=(("\\A(?:CPU)\\z",),),
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
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
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
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
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
        plain_arms=(
            (
                "\\A(?:(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?)\\z",
            ),
            (
                "\\A(?:((:|[0-9a-fA-F]{0,4}):)([0-9a-fA-F]{0,4}:){0,5}((([0-9a-fA-F]{0,4}:)?(:|[0-9a-fA-F]{0,4}))|(((25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])))(%[\\p{N}\\p{L}]+)?)\\z",
                "\\A(?:(([^:]+:){6}(([^:]+:[^:]+)|(.*\\..*)))|((([^:]+:)*[^:]+)?::(([^:]+:)*[^:]+)?)(%.+)?)\\z",
            ),
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
        ),
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
        plain_arms=(("\\A(?:default)\\z",),),
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
        plain_arms=(("\\A(?:default)\\z",),),
    ),
    LeafrefConstraint(
        source_table="SFLOW",
        source_field="agent_id",
        targets=(("PORT", "name"), ("PORTCHANNEL", "name"), ("MGMT_PORT", "name")),
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
        ),
    ),
    LeafrefConstraint(
        source_table="SFLOW_SESSION",
        source_field="port",
        targets=(("PORT", "name"),),
        source_is_simple_key=True,
        plain_arms=(("\\A(?:all)\\z",),),
    ),
    LeafrefConstraint(
        source_table="SRV6_MY_LOCATORS",
        source_field="vrf",
        targets=(("VRF", "name"),),
        plain_arms=(("\\A(?:default)\\z",),),
    ),
    LeafrefConstraint(
        source_table="SRV6_MY_SIDS",
        source_field="decap_vrf",
        targets=(("VRF", "name"),),
        plain_arms=(("\\A(?:default)\\z",),),
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
        source_table="TACPLUS",
        source_field="src_intf",
        targets=(
            ("PORT", "name"),
            ("PORTCHANNEL", "name"),
            ("LOOPBACK_INTERFACE", "name"),
            ("MGMT_PORT", "name"),
        ),
        plain_arms=(
            (
                "\\A(?:Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4]))\\z",
            ),
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


# Key leaves of every `list` in a table, in the order ConfigDB joins
# them into the row key with `|`. Lists are told apart by how many
# parts they have; no table declares two of the same length.
TABLE_KEY_FIELDS: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "AAA": (("type",),),
    "AS_PATH_SET": (("name",),),
    "AUTO_TECHSUPPORT_FEATURE": (("feature_name",),),
    "BGP_AGGREGATE_ADDRESS": (("aggregate-address",),),
    "BGP_ALLOWED_PREFIXES": (
        ("deployment", "id"),
        ("deployment", "id", "neighbor", "neighbor_type"),
        ("deployment", "id", "community"),
        ("deployment", "id", "neighbor", "neighbor_type", "community"),
    ),
    "BGP_GLOBALS": (("vrf_name",),),
    "BGP_GLOBALS_AF": (("vrf_name", "afi_safi"),),
    "BGP_GLOBALS_AF_AGGREGATE_ADDR": (("vrf_name", "afi_safi", "ip_prefix"),),
    "BGP_GLOBALS_AF_NETWORK": (("vrf_name", "afi_safi", "ip_prefix"),),
    "BGP_GLOBALS_LISTEN_PREFIX": (("vrf_name", "ip_prefix"),),
    "BGP_INTERNAL_NEIGHBOR": (("neighbor",),),
    "BGP_MONITORS": (("addr",),),
    "BGP_NEIGHBOR": (("neighbor",), ("vrf_name", "neighbor")),
    "BGP_NEIGHBOR_AF": (("vrf_name", "neighbor", "afi_safi"),),
    "BGP_PEER_GROUP": (("vrf_name", "peer_group_name"),),
    "BGP_PEER_GROUP_AF": (("vrf_name", "peer_group_name", "afi_safi"),),
    "BGP_PEER_RANGE": (("peer_range_name",),),
    "BGP_SENTINELS": (("sentinel_name",),),
    "BGP_VOQ_CHASSIS_NEIGHBOR": (("neighbor",),),
    "BREAKOUT_CFG": (("port",),),
    "BUFFER_PG": (("port", "pg_num"),),
    "BUFFER_POOL": (("name",),),
    "BUFFER_PORT_EGRESS_PROFILE_LIST": (("port",),),
    "BUFFER_PORT_INGRESS_PROFILE_LIST": (("port",),),
    "BUFFER_PROFILE": (("name",),),
    "BUFFER_QUEUE": (("port", "qindex"), ("hostname", "asic_name", "port", "qindex")),
    "CABLE_LENGTH": (("name",),),
    "CHASSIS_MODULE": (("name",),),
    "COMMUNITY_SET": (("name",),),
    "CONSOLE_PORT": (("name",),),
    "COPP_GROUP": (("name",),),
    "COPP_TRAP": (("name",),),
    "DASH_ACL_GROUP": (("name",),),
    "DASH_ACL_IN": (("eni", "stage"),),
    "DASH_ACL_OUT": (("eni", "stage"),),
    "DASH_ACL_RULE": (("acl_group_id", "name"),),
    "DASH_APPLIANCE": (("name",),),
    "DASH_ENI": (("name",),),
    "DASH_QOS": (("name",),),
    "DASH_ROUTE_TABLE": (("eni", "prefix"),),
    "DASH_ROUTING_TYPE": (("name",),),
    "DASH_VNET": (("name",),),
    "DASH_VNET_MAPPING_TABLE": (("vnet", "ip_addr"),),
    "DEBUG_COUNTER": (("name",),),
    "DEBUG_COUNTER_DROP_REASON": (("name", "reason"),),
    "DEFAULT_LOSSLESS_BUFFER_PARAMETER": (("name",),),
    "DEVICE_NEIGHBOR": (("peer_name",),),
    "DEVICE_NEIGHBOR_METADATA": (("name",),),
    "DHCPV4_RELAY": (("name",),),
    "DHCP_RELAY": (("name",),),
    "DHCP_SERVER": (("ip",),),
    "DHCP_SERVER_IPV4": (("name",),),
    "DHCP_SERVER_IPV4_CUSTOMIZED_OPTIONS": (("name",),),
    "DHCP_SERVER_IPV4_PORT": (("name", "port"),),
    "DHCP_SERVER_IPV4_RANGE": (("name",),),
    "DNS_NAMESERVER": (("ip",),),
    "DOT1P_TO_TC_MAP": (("name",),),
    "DPU": (("dpu_name",),),
    "DPUS": (("dpu_name",),),
    "DSCP_TO_FC_MAP": (("name",),),
    "DSCP_TO_TC_MAP": (("name",),),
    "EXP_TO_FC_MAP": (("name",),),
    "EXTENDED_COMMUNITY_SET": (("name",),),
    "FABRIC_PORT": (("name",),),
    "FEATURE": (("name",),),
    "FG_NHG": (("name",),),
    "FG_NHG_MEMBER": (("next_hop_ip",),),
    "FG_NHG_PREFIX": (("ip_prefix",),),
    "FLOW_COUNTER_ROUTE_PATTERN": (("ip_prefix",), ("vrf_name", "ip_prefix")),
    "GNMI_CLIENT_CERT": (("cert_cname",),),
    "HEARTBEAT": (("name",),),
    "HIGH_FREQUENCY_TELEMETRY_GROUP": (("profile_name", "group_name"),),
    "HIGH_FREQUENCY_TELEMETRY_PROFILE": (("name",),),
    "INTERFACE": (("name",), ("name", "ip-prefix")),
    "LDAP_SERVER": (("hostname",),),
    "LLDP_PORT": (("ifname",),),
    "LOGGER": (("name",),),
    "LOOPBACK_INTERFACE": (("name",), ("name", "ip-prefix")),
    "LOSSLESS_TRAFFIC_PATTERN": (("name",),),
    "MACSEC_PROFILE": (("name",),),
    "MAP_PFC_PRIORITY_TO_QUEUE": (("name",),),
    "MCLAG_DOMAIN": (("domain_id",),),
    "MCLAG_INTERFACE": (("domain_id", "if_name"),),
    "MCLAG_UNIQUE_IP": (("if_name",),),
    "MGMT_INTERFACE": (("name", "ip_prefix"),),
    "MIRROR_SESSION": (("name",),),
    "MPLS_TC_TO_TC_MAP": (("name",),),
    "MUX_CABLE": (("ifname",),),
    "NAT_BINDINGS": (("name",),),
    "NAT_POOL": (("name",),),
    "NEIGH": (("port", "neighbor"),),
    "NTP_KEY": (("id",),),
    "NTP_SERVER": (("server_address",),),
    "NVGRE_TUNNEL": (("tunnel_name",),),
    "NVGRE_TUNNEL_MAP": (("tunnel_name", "tunnel_map_name"),),
    "PBH_HASH": (("hash_name",),),
    "PBH_HASH_FIELD": (("hash_field_name",),),
    "PBH_RULE": (("table_name", "rule_name"),),
    "PBH_TABLE": (("table_name",),),
    "PEER_SWITCH": (("peer_switch",),),
    "PFC_PRIORITY_TO_PRIORITY_GROUP_MAP": (("name",),),
    "PFC_WD": (("ifname",),),
    "POLICER": (("name",),),
    "PORT": (("name",),),
    "PORTCHANNEL": (("name",),),
    "PORTCHANNEL_INTERFACE": (("name",), ("name", "ip_prefix")),
    "PORTCHANNEL_MEMBER": (("name", "port"),),
    "PORT_QOS_MAP": (("ifname",),),
    "PORT_STORM_CONTROL": (("ifname", "storm_type"),),
    "PREFIX": (
        ("name", "sequence_number", "ip_prefix", "masklength_range"),
        ("name", "ip_prefix", "masklength_range"),
    ),
    "PREFIX_LIST": (("prefix_type", "ip-prefix"),),
    "PREFIX_SET": (("name",),),
    "QUEUE": (("ifname", "qindex"), ("hostname", "asic_name", "ifname", "qindex")),
    "RADIUS_SERVER": (("ipaddress",),),
    "REMOTE_DPU": (("dpu_name",),),
    "ROUTE_MAP": (("name", "stmt_name"),),
    "ROUTE_MAP_SET": (("name",),),
    "ROUTE_REDISTRIBUTE": (
        ("vrf_name", "src_protocol", "dst_protocol", "addr_family"),
    ),
    "SCHEDULER": (("name",),),
    "SFLOW_COLLECTOR": (("name",),),
    "SFLOW_SESSION": (("port",),),
    "SNMP_AGENT_ADDRESS_CONFIG": (("agent_ip", "port", "vrf_name"),),
    "SNMP_COMMUNITY": (("name",),),
    "SNMP_USER": (("name",),),
    "SRV6_MY_LOCATORS": (("locator_name",),),
    "SRV6_MY_SIDS": (("locator", "ip_prefix"),),
    "STATIC_NAPT": (("global_ip", "ip_protocol", "global_l4_port"),),
    "STATIC_NAT": (("global_ip",),),
    "STATIC_ROUTE": (("prefix",), ("vrf_name", "prefix")),
    "STP": (("keyleaf",),),
    "STP_MST": (("keyleaf",),),
    "STP_MST_INST": (("instance",),),
    "STP_MST_PORT": (("inst_id", "ifname"),),
    "STP_PORT": (("ifname",),),
    "STP_VLAN": (("name",),),
    "STP_VLAN_PORT": (("vlan-name", "ifname"),),
    "SUBNET_DECAP": (("name",),),
    "SUPPRESS_ASIC_SDK_HEALTH_EVENT": (("severity",),),
    "SYSLOG_CONFIG_FEATURE": (("service",),),
    "SYSTEM_DEFAULTS": (("name",),),
    "SYSTEM_PORT": (("hostname", "asic_name", "ifname"),),
    "TACPLUS_SERVER": (("ipaddress",),),
    "TC_TO_DSCP_MAP": (("name",),),
    "TC_TO_PRIORITY_GROUP_MAP": (("name",),),
    "TC_TO_QUEUE_MAP": (("name",),),
    "TELEMETRY_CLIENT": (("prefix", "name"),),
    "TUNNEL": (("mux_tunnel",),),
    "VDPU": (("vdpu_id",),),
    "VLAN": (("name",),),
    "VLAN_INTERFACE": (("name",), ("name", "ip-prefix")),
    "VLAN_MEMBER": (("name", "port"),),
    "VLAN_SUB_INTERFACE": (("name",), ("name", "ip-prefix")),
    "VNET": (("name",),),
    "VNET_ROUTE_TUNNEL": (("vnet_name", "prefix"),),
    "VOQ_INBAND_INTERFACE": (("name",), ("name", "ip-prefix")),
    "VRF": (("name",),),
    "VXLAN_EVPN_NVO": (("name",),),
    "VXLAN_TUNNEL": (("name",),),
    "VXLAN_TUNNEL_MAP": (("name", "mapname"),),
    "WARM_RESTART": (("module",),),
    "WRED_PROFILE": (("name",),),
}
