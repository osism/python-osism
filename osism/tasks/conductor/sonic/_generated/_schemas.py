# SPDX-License-Identifier: Apache-2.0
# AUTO-GENERATED — DO NOT EDIT BY HAND.
# Regenerate with: python tools/sonic_yang_to_pydantic.py
# flake8: noqa: E501
"""SONiC ConfigDB Pydantic schemas, generated from files/sonic/yang_models."""

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


# sonic-asic-sensors.yang :: sonic-asic-sensors :: ASIC_SENSORS
class AsicSensorsAsicSensorsPollerIntervalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    interval: Optional[Annotated[int, Field(ge=1, le=999)]] = 10


class AsicSensorsAsicSensorsPollerStatusRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    admin_status: Optional[Literal["enable", "disable"]] = "enable"


class AsicSensorsTable(
    RootModel[
        Dict[
            str,
            Union[
                AsicSensorsAsicSensorsPollerIntervalRow,
                AsicSensorsAsicSensorsPollerStatusRow,
            ],
        ]
    ]
):
    pass


# sonic-auto_techsupport.yang :: sonic-auto_techsupport :: AUTO_TECHSUPPORT
class AutoTechsupportGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    state: Optional[Literal["enabled", "disabled"]] = None
    rate_limit_interval: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    max_techsupport_limit: Optional[float] = None
    max_core_limit: Optional[float] = None
    available_mem_threshold: Optional[float] = 10.0
    min_available_mem: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 200
    since: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )


class AutoTechsupportTable(RootModel[Dict[str, AutoTechsupportGlobalRow]]):
    pass


# sonic-auto_techsupport.yang :: sonic-auto_techsupport :: AUTO_TECHSUPPORT_FEATURE
class AutoTechsupportFeatureListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    feature_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    state: Optional[Literal["enabled", "disabled"]] = None
    available_mem_threshold: Optional[float] = 10.0
    rate_limit_interval: Optional[Annotated[int, Field(ge=0, le=65535)]] = None


class AutoTechsupportFeatureTable(RootModel[Dict[str, AutoTechsupportFeatureListRow]]):
    pass


# sonic-banner.yang :: sonic-banner :: BANNER_MESSAGE
class BannerMessageGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    state: Optional[Literal["enabled", "disabled"]] = "disabled"
    login: Optional[str] = "Debian GNU/Linux 11"
    motd: Optional[str] = (
        "You are on\n ____   ___  _   _ _  ____\n/ ___| / _ \\| \\ | (_)/ ___|\n\\___ \\| | | |  \\| | | |\n ___) | |_| | |\\  | | |___\n|____/ \\___/|_| \\_|_|\\____|\n-- Software for Open Networking in the Cloud --\nUnauthorized access and/or use are prohibited.\nAll access and/or use are subject to monitoring.\nHelp:    https://sonic-net.github.io/SONiC/\n"
    )
    logout: Optional[str] = ""


class BannerMessageTable(RootModel[Dict[str, BannerMessageGlobalRow]]):
    pass


# sonic-bgp-aggregate-address.yang :: sonic-bgp-aggregate-address :: BGP_AGGREGATE_ADDRESS
class BgpAggregateAddressListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    aggregate_address: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="aggregate-address")
    bbr_required: Optional[bool] = Field(default=False, alias="bbr-required")
    summary_only: Optional[bool] = Field(default=False, alias="summary-only")
    as_set: Optional[bool] = Field(default=False, alias="as-set")
    aggregate_address_prefix_list: Optional[
        Annotated[
            str,
            StringConstraints(min_length=0, max_length=128, pattern="[0-9a-zA-Z_-]*"),
        ]
    ] = Field(default="", alias="aggregate-address-prefix-list")
    contributing_address_prefix_list: Optional[
        Annotated[
            str,
            StringConstraints(min_length=0, max_length=128, pattern="[0-9a-zA-Z_-]*"),
        ]
    ] = Field(default="", alias="contributing-address-prefix-list")


class BgpAggregateAddressTable(RootModel[Dict[str, BgpAggregateAddressListRow]]):
    pass


# sonic-bgp-allowed-prefix.yang :: sonic-bgp-allowed-prefix :: BGP_ALLOWED_PREFIXES
class BgpAllowedPrefixesListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deployment: Optional[Annotated[str, StringConstraints(pattern="DEPLOYMENT_ID")]] = (
        None
    )
    id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    default_action: Optional[Literal["permit", "deny"]] = None
    prefixes_v4: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))( (le|ge) (([0-9])|([1-2][0-9])|(3[0-2])))?"
                ),
            ]
        ]
    ] = None
    prefixes_v6: Optional[List[str]] = None


class BgpAllowedPrefixesNeighListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deployment: Optional[Annotated[str, StringConstraints(pattern="DEPLOYMENT_ID")]] = (
        None
    )
    id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    neighbor: Optional[Annotated[str, StringConstraints(pattern="NEIGHBOR_TYPE")]] = (
        None
    )
    neighbor_type: Optional[str] = None
    default_action: Optional[Literal["permit", "deny"]] = None
    prefixes_v4: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))( (le|ge) (([0-9])|([1-2][0-9])|(3[0-2])))?"
                ),
            ]
        ]
    ] = None
    prefixes_v6: Optional[List[str]] = None


class BgpAllowedPrefixesComListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deployment: Optional[Annotated[str, StringConstraints(pattern="DEPLOYMENT_ID")]] = (
        None
    )
    id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    community: Optional[str] = None
    default_action: Optional[Literal["permit", "deny"]] = None
    prefixes_v4: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))( (le|ge) (([0-9])|([1-2][0-9])|(3[0-2])))?"
                ),
            ]
        ]
    ] = None
    prefixes_v6: Optional[List[str]] = None


class BgpAllowedPrefixesNeighComListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    deployment: Optional[Annotated[str, StringConstraints(pattern="DEPLOYMENT_ID")]] = (
        None
    )
    id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    neighbor: Optional[Annotated[str, StringConstraints(pattern="NEIGHBOR_TYPE")]] = (
        None
    )
    neighbor_type: Optional[str] = None
    community: Optional[str] = None
    default_action: Optional[Literal["permit", "deny"]] = None
    prefixes_v4: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))( (le|ge) (([0-9])|([1-2][0-9])|(3[0-2])))?"
                ),
            ]
        ]
    ] = None
    prefixes_v6: Optional[List[str]] = None


class BgpAllowedPrefixesTable(
    RootModel[
        Dict[
            str,
            Union[
                BgpAllowedPrefixesListRow,
                BgpAllowedPrefixesNeighListRow,
                BgpAllowedPrefixesComListRow,
                BgpAllowedPrefixesNeighComListRow,
            ],
        ]
    ]
):
    pass


# sonic-bgp-bbr.yang :: sonic-bgp-bbr :: BGP_BBR
class BgpBbrAllRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: Optional[Literal["enabled", "disabled"]] = "enabled"


class BgpBbrTable(RootModel[Dict[str, BgpBbrAllRow]]):
    pass


# sonic-bgp-device-global.yang :: sonic-bgp-device-global :: BGP_DEVICE_GLOBAL
class BgpDeviceGlobalStateRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tsa_enabled: Optional[bool] = False
    wcmp_enabled: Optional[bool] = False
    idf_isolation_state: Optional[
        Literal["isolated_no_export", "isolated_withdraw_all", "unisolated"]
    ] = "unisolated"


class BgpDeviceGlobalTable(RootModel[Dict[str, BgpDeviceGlobalStateRow]]):
    pass


# sonic-bgp-global.yang :: sonic-bgp-global :: BGP_GLOBALS
class BgpGlobalsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[
        Union[Annotated[str, StringConstraints(pattern="default")], str]
    ] = None
    router_id: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    local_asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    always_compare_med: Optional[bool] = None
    load_balance_mp_relax: Optional[bool] = None
    graceful_restart_enable: Optional[bool] = None
    gr_preserve_fw_state: Optional[bool] = None
    gr_restart_time: Optional[Annotated[int, Field(ge=1, le=3600)]] = None
    gr_stale_routes_time: Optional[Annotated[int, Field(ge=1, le=3600)]] = None
    external_compare_router_id: Optional[bool] = None
    ignore_as_path_length: Optional[bool] = None
    log_nbr_state_changes: Optional[bool] = None
    rr_cluster_id: Optional[str] = None
    rr_allow_out_policy: Optional[bool] = None
    disable_ebgp_connected_rt_check: Optional[bool] = None
    fast_external_failover: Optional[bool] = None
    network_import_check: Optional[bool] = None
    graceful_shutdown: Optional[bool] = None
    rr_clnt_to_clnt_reflection: Optional[bool] = None
    max_dynamic_neighbors: Optional[Annotated[int, Field(ge=1, le=5000)]] = None
    read_quanta: Optional[Annotated[int, Field(ge=1, le=10)]] = None
    write_quanta: Optional[Annotated[int, Field(ge=1, le=10)]] = None
    coalesce_time: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    route_map_process_delay: Optional[Annotated[int, Field(ge=0, le=600)]] = None
    deterministic_med: Optional[bool] = None
    med_confed: Optional[bool] = None
    med_missing_as_worst: Optional[bool] = None
    compare_confed_as_path: Optional[bool] = None
    as_path_mp_as_set: Optional[bool] = None
    default_ipv4_unicast: Optional[bool] = None
    default_local_preference: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = (
        None
    )
    default_show_hostname: Optional[bool] = None
    default_shutdown: Optional[bool] = None
    default_subgroup_pkt_queue_max: Optional[Annotated[int, Field(ge=20, le=100)]] = (
        None
    )
    max_med_time: Optional[Annotated[int, Field(ge=5, le=86400)]] = None
    max_med_val: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    max_med_admin: Optional[bool] = None
    max_med_admin_val: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    max_delay: Optional[Annotated[int, Field(ge=0, le=3600)]] = None
    establish_wait: Optional[Annotated[int, Field(ge=0, le=3600)]] = None
    confed_id: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    confed_peers: Optional[List[Annotated[int, Field(ge=1, le=4294967295)]]] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None


class BgpGlobalsTable(RootModel[Dict[str, BgpGlobalsListRow]]):
    pass


# sonic-bgp-global.yang :: sonic-bgp-global :: BGP_GLOBALS_AF
class BgpGlobalsAfListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    afi_safi: Optional[str] = None
    max_ebgp_paths: Optional[Annotated[int, Field(ge=1, le=256)]] = 1
    max_ibgp_paths: Optional[Annotated[int, Field(ge=1, le=256)]] = 1
    import_vrf: Optional[
        Union[Annotated[str, StringConstraints(pattern="default")], str]
    ] = None
    import_vrf_route_map: Optional[str] = None
    route_download_filter: Optional[str] = None
    ebgp_route_distance: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    ibgp_route_distance: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    local_route_distance: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    ibgp_equal_cluster_length: Optional[bool] = None
    route_flap_dampen: Optional[bool] = None
    route_flap_dampen_half_life: Optional[Annotated[int, Field(ge=1, le=45)]] = None
    route_flap_dampen_reuse_threshold: Optional[
        Annotated[int, Field(ge=1, le=20000)]
    ] = None
    route_flap_dampen_suppress_threshold: Optional[
        Annotated[int, Field(ge=1, le=20000)]
    ] = None
    route_flap_dampen_max_suppress: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    autort: Optional[Literal["rfc8365-compatible"]] = None
    advertise_all_vni: Optional[bool] = Field(default=None, alias="advertise-all-vni")
    advertise_svi_ip: Optional[bool] = Field(default=None, alias="advertise-svi-ip")


class BgpGlobalsAfTable(RootModel[Dict[str, BgpGlobalsAfListRow]]):
    pass


# sonic-bgp-global.yang :: sonic-bgp-global :: BGP_GLOBALS_AF_AGGREGATE_ADDR
class BgpGlobalsAfAggregateAddrListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    afi_safi: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    as_set: Optional[bool] = None
    summary_only: Optional[bool] = None
    policy: Optional[str] = None


class BgpGlobalsAfAggregateAddrTable(
    RootModel[Dict[str, BgpGlobalsAfAggregateAddrListRow]]
):
    pass


# sonic-bgp-global.yang :: sonic-bgp-global :: BGP_GLOBALS_AF_NETWORK
class BgpGlobalsAfNetworkListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    afi_safi: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    policy: Optional[str] = None
    backdoor: Optional[bool] = None


class BgpGlobalsAfNetworkTable(RootModel[Dict[str, BgpGlobalsAfNetworkListRow]]):
    pass


# sonic-bgp-internal-neighbor.yang :: sonic-bgp-internal-neighbor :: BGP_INTERNAL_NEIGHBOR
class BgpInternalNeighborListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    neighbor: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    local_addr: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        str,
    ]
    name: Optional[str] = None
    nhopself: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    rrclient: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    admin_status: Optional[Literal["up", "down"]] = None


class BgpInternalNeighborTable(RootModel[Dict[str, BgpInternalNeighborListRow]]):
    pass


# sonic-bgp-monitor.yang :: sonic-bgp-monitor :: BGP_MONITORS
class BgpMonitorsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    local_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    name: Optional[str] = None
    nhopself: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    rrclient: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    admin_status: Optional[Literal["up", "down"]] = None


class BgpMonitorsTable(RootModel[Dict[str, BgpMonitorsListRow]]):
    pass


# sonic-bgp-neighbor.yang :: sonic-bgp-neighbor :: BGP_NEIGHBOR
class BgpNeighborTemplateListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    neighbor: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    local_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    name: Optional[str] = None
    nhopself: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    rrclient: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    admin_status: Optional[Literal["up", "down"]] = None


class BgpNeighborListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    neighbor: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    peer_group_name: Optional[str] = None
    local_asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    name: Optional[str] = None
    asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    peer_type: Optional[Literal["internal", "external"]] = None
    ebgp_multihop: Optional[bool] = None
    ebgp_multihop_ttl: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    auth_password: Optional[str] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    conn_retry: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    min_adv_interval: Optional[Annotated[int, Field(ge=0, le=600)]] = None
    local_addr: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    passive_mode: Optional[bool] = None
    capability_ext_nexthop: Optional[bool] = None
    disable_ebgp_connected_route_check: Optional[bool] = None
    enforce_first_as: Optional[bool] = None
    solo_peer: Optional[bool] = None
    ttl_security_hops: Optional[Annotated[int, Field(ge=1, le=254)]] = None
    bfd: Optional[bool] = None
    bfd_check_ctrl_plane_failure: Optional[bool] = None
    capability_dynamic: Optional[bool] = None
    dont_negotiate_capability: Optional[bool] = None
    enforce_multihop: Optional[bool] = None
    override_capability: Optional[bool] = None
    peer_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    shutdown_message: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=127)]
    ] = None
    strict_capability_match: Optional[bool] = None
    admin_status: Optional[Literal["up", "down"]] = None
    local_as_no_prepend: Optional[bool] = None
    local_as_replace_as: Optional[bool] = None


class BgpNeighborTable(
    RootModel[Dict[str, Union[BgpNeighborTemplateListRow, BgpNeighborListRow]]]
):
    pass


# sonic-bgp-neighbor.yang :: sonic-bgp-neighbor :: BGP_NEIGHBOR_AF
class BgpNeighborAfListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    neighbor: Optional[str] = None
    afi_safi: Optional[str] = None
    admin_status: Optional[Literal["up", "down"]] = None
    send_default_route: Optional[bool] = None
    default_rmap: Optional[str] = None
    max_prefix_limit: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    max_prefix_warning_only: Optional[bool] = None
    max_prefix_warning_threshold: Optional[Annotated[int, Field(ge=1, le=100)]] = None
    max_prefix_restart_interval: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    route_map_in: Optional[List[str]] = None
    route_map_out: Optional[List[str]] = None
    soft_reconfiguration_in: Optional[bool] = None
    unsuppress_map_name: Optional[str] = None
    rrclient: Optional[bool] = None
    weight: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    as_override: Optional[bool] = None
    send_community: Optional[
        Literal["standard", "extended", "both", "large", "all", "none"]
    ] = None
    tx_add_paths: Optional[Literal["tx_all_paths", "tx_best_path_per_as"]] = None
    unchanged_as_path: Optional[bool] = None
    unchanged_med: Optional[bool] = None
    unchanged_nexthop: Optional[bool] = None
    filter_list_in: Optional[str] = None
    filter_list_out: Optional[str] = None
    nhself: Optional[bool] = None
    nexthop_self_force: Optional[bool] = None
    prefix_list_in: Optional[str] = None
    prefix_list_out: Optional[str] = None
    remove_private_as_enabled: Optional[bool] = None
    replace_private_as: Optional[bool] = None
    remove_private_as_all: Optional[bool] = None
    allow_as_in: Optional[bool] = None
    allow_as_count: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    allow_as_origin: Optional[bool] = None
    cap_orf: Optional[Literal["send", "receive", "both"]] = None
    route_server_client: Optional[bool] = None


class BgpNeighborAfTable(RootModel[Dict[str, BgpNeighborAfListRow]]):
    pass


# sonic-bgp-peergroup.yang :: sonic-bgp-peergroup :: BGP_PEER_GROUP
class BgpPeerGroupListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    peer_group_name: Optional[str] = None
    local_asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    name: Optional[str] = None
    asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    peer_type: Optional[Literal["internal", "external"]] = None
    ebgp_multihop: Optional[bool] = None
    ebgp_multihop_ttl: Optional[Annotated[int, Field(ge=1, le=255)]] = None
    auth_password: Optional[str] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    conn_retry: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    min_adv_interval: Optional[Annotated[int, Field(ge=0, le=600)]] = None
    local_addr: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    passive_mode: Optional[bool] = None
    capability_ext_nexthop: Optional[bool] = None
    disable_ebgp_connected_route_check: Optional[bool] = None
    enforce_first_as: Optional[bool] = None
    solo_peer: Optional[bool] = None
    ttl_security_hops: Optional[Annotated[int, Field(ge=1, le=254)]] = None
    bfd: Optional[bool] = None
    bfd_check_ctrl_plane_failure: Optional[bool] = None
    capability_dynamic: Optional[bool] = None
    dont_negotiate_capability: Optional[bool] = None
    enforce_multihop: Optional[bool] = None
    override_capability: Optional[bool] = None
    peer_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    shutdown_message: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=127)]
    ] = None
    strict_capability_match: Optional[bool] = None
    admin_status: Optional[Literal["up", "down"]] = None
    local_as_no_prepend: Optional[bool] = None
    local_as_replace_as: Optional[bool] = None


class BgpPeerGroupTable(RootModel[Dict[str, BgpPeerGroupListRow]]):
    pass


# sonic-bgp-peergroup.yang :: sonic-bgp-peergroup :: BGP_PEER_GROUP_AF
class BgpPeerGroupAfListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    peer_group_name: Optional[str] = None
    afi_safi: Optional[str] = None
    admin_status: Optional[Literal["up", "down"]] = None
    send_default_route: Optional[bool] = None
    default_rmap: Optional[str] = None
    max_prefix_limit: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    max_prefix_warning_only: Optional[bool] = None
    max_prefix_warning_threshold: Optional[Annotated[int, Field(ge=1, le=100)]] = None
    max_prefix_restart_interval: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    route_map_in: Optional[List[str]] = None
    route_map_out: Optional[List[str]] = None
    soft_reconfiguration_in: Optional[bool] = None
    unsuppress_map_name: Optional[str] = None
    rrclient: Optional[bool] = None
    weight: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    as_override: Optional[bool] = None
    send_community: Optional[
        Literal["standard", "extended", "both", "large", "all", "none"]
    ] = None
    tx_add_paths: Optional[Literal["tx_all_paths", "tx_best_path_per_as"]] = None
    unchanged_as_path: Optional[bool] = None
    unchanged_med: Optional[bool] = None
    unchanged_nexthop: Optional[bool] = None
    filter_list_in: Optional[str] = None
    filter_list_out: Optional[str] = None
    nhself: Optional[bool] = None
    nexthop_self_force: Optional[bool] = None
    prefix_list_in: Optional[str] = None
    prefix_list_out: Optional[str] = None
    remove_private_as_enabled: Optional[bool] = None
    replace_private_as: Optional[bool] = None
    remove_private_as_all: Optional[bool] = None
    allow_as_in: Optional[bool] = None
    allow_as_count: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    allow_as_origin: Optional[bool] = None
    cap_orf: Optional[Literal["send", "receive", "both"]] = None
    route_server_client: Optional[bool] = None


class BgpPeerGroupAfTable(RootModel[Dict[str, BgpPeerGroupAfListRow]]):
    pass


# sonic-bgp-peergroup.yang :: sonic-bgp-peergroup :: BGP_GLOBALS_LISTEN_PREFIX
class BgpGlobalsListenPrefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    peer_group: Optional[str] = None


class BgpGlobalsListenPrefixTable(RootModel[Dict[str, BgpGlobalsListenPrefixListRow]]):
    pass


# sonic-bgp-peerrange.yang :: sonic-bgp-peerrange :: BGP_PEER_RANGE
class BgpPeerRangeListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    peer_range_name: Optional[str] = None
    name: Optional[str] = None
    src_address: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    peer_asn: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    ip_range: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                    ),
                ],
                str,
            ]
        ]
    ] = None


class BgpPeerRangeTable(RootModel[Dict[str, BgpPeerRangeListRow]]):
    pass


# sonic-bgp-prefix-list.yang :: sonic-bgp-prefix-list :: PREFIX_LIST
class PrefixListListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    prefix_type: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")
    family: Optional[Literal["IPv4", "IPv6"]] = None


class PrefixListTable(RootModel[Dict[str, PrefixListListRow]]):
    pass


# sonic-bgp-sentinel.yang :: sonic-bgp-sentinel :: BGP_SENTINELS
class BgpSentinelsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    sentinel_name: Optional[str] = None
    name: Optional[str] = None
    src_address: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    ip_range: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                    ),
                ],
                str,
            ]
        ]
    ] = None


class BgpSentinelsTable(RootModel[Dict[str, BgpSentinelsListRow]]):
    pass


# sonic-bgp-voq-chassis-neighbor.yang :: sonic-bgp-voq-chassis-neighbor :: BGP_VOQ_CHASSIS_NEIGHBOR
class BgpVoqChassisNeighborListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    neighbor: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    holdtime: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    keepalive: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    local_addr: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        str,
    ]
    name: Optional[str] = None
    nhopself: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    rrclient: Optional[Annotated[int, Field(ge=0, le=1)]] = None
    admin_status: Optional[Literal["up", "down"]] = None


class BgpVoqChassisNeighborTable(RootModel[Dict[str, BgpVoqChassisNeighborListRow]]):
    pass


# sonic-bmp.yang :: sonic-bmp :: BMP
class BmpTableRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    bgp_neighbor_table: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "true"
    bgp_rib_in_table: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"
    bgp_rib_out_table: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"


class BmpTable(RootModel[Dict[str, BmpTableRow]]):
    pass


# sonic-breakout_cfg.yang :: sonic-breakout_cfg :: BREAKOUT_CFG
class BreakoutCfgListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    brkout_mode: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=64)]
    ] = None


class BreakoutCfgTable(RootModel[Dict[str, BreakoutCfgListRow]]):
    pass


# sonic-buffer-pg.yang :: sonic-buffer-pg :: BUFFER_PG
class BufferPgListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[str] = None
    pg_num: Optional[Annotated[str, StringConstraints(pattern="[0-7]((-)[0-7])?")]] = (
        None
    )
    profile: Optional[Union[str, Annotated[str, StringConstraints(pattern="NULL")]]] = (
        "0"
    )


class BufferPgTable(RootModel[Dict[str, BufferPgListRow]]):
    pass


# sonic-buffer-pool.yang :: sonic-buffer-pool :: BUFFER_POOL
class BufferPoolListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    type: Literal["ingress", "egress", "both"]
    mode: Literal["static", "dynamic"]
    size: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    xoff: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    percentage: Optional[Annotated[int, Field(ge=0, le=255)]] = None


class BufferPoolTable(RootModel[Dict[str, BufferPoolListRow]]):
    pass


# sonic-buffer-port-egress-profile-list.yang :: sonic-buffer-port-egress-profile-list :: BUFFER_PORT_EGRESS_PROFILE_LIST
class BufferPortEgressProfileListListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[str] = None
    profile_list: Optional[List[str]] = None


class BufferPortEgressProfileListTable(
    RootModel[Dict[str, BufferPortEgressProfileListListRow]]
):
    pass


# sonic-buffer-port-ingress-profile-list.yang :: sonic-buffer-port-ingress-profile-list :: BUFFER_PORT_INGRESS_PROFILE_LIST
class BufferPortIngressProfileListListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[str] = None
    profile_list: Optional[List[str]] = None


class BufferPortIngressProfileListTable(
    RootModel[Dict[str, BufferPortIngressProfileListListRow]]
):
    pass


# sonic-buffer-profile.yang :: sonic-buffer-profile :: BUFFER_PROFILE
class BufferProfileListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    static_th: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    dynamic_th: Optional[Annotated[int, Field(ge=-8, le=7)]] = None
    size: Annotated[int, Field(ge=0, le=18446744073709551615)]
    pool: str
    xon_offset: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    xon: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    xoff: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    headroom_type: Optional[Literal["static", "dynamic"]] = "static"
    packet_discard_action: Optional[Literal["drop", "trim"]] = None


class BufferProfileTable(RootModel[Dict[str, BufferProfileListRow]]):
    pass


# sonic-buffer-queue.yang :: sonic-buffer-queue :: BUFFER_QUEUE
class BufferQueueListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[str] = None
    qindex: Optional[
        Annotated[str, StringConstraints(pattern="(1[0-5]|[0-9])((-)(1[0-5]|[0-9]))?")]
    ] = None
    profile: Optional[str] = "0"


class VoqBufferQueueListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hostname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    asic_name: Optional[
        Annotated[str, StringConstraints(pattern="[Aa][Ss][Ii][Cc][0-9]{1,2}")]
    ] = None
    port: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    qindex: Optional[
        Annotated[str, StringConstraints(pattern="(1[0-5]|[0-9])((-)(1[0-5]|[0-9]))?")]
    ] = None
    profile: Optional[str] = "0"


class BufferQueueTable(
    RootModel[Dict[str, Union[BufferQueueListRow, VoqBufferQueueListRow]]]
):
    pass


# sonic-cable-length.yang :: sonic-cable-length :: CABLE_LENGTH
class CableLengthListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class CableLengthTable(RootModel[Dict[str, CableLengthListRow]]):
    pass


# sonic-chassis-module.yang :: sonic-chassis-module :: CHASSIS_MODULE
class ChassisModuleListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(pattern="LINE-CARD[0-9]+|FABRIC-CARD[0-9]+|DPU[0-9]+"),
        ]
    ] = None
    admin_status: Optional[Literal["up", "down"]] = "up"


class ChassisModuleTable(RootModel[Dict[str, ChassisModuleListRow]]):
    pass


# sonic-console.yang :: sonic-console :: CONSOLE_PORT
class ConsolePortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    baud_rate: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    flow_control: Optional[Annotated[str, StringConstraints(pattern="0|1")]] = "0"
    remote_device: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None


class ConsolePortTable(RootModel[Dict[str, ConsolePortListRow]]):
    pass


# sonic-console.yang :: sonic-console :: CONSOLE_SWITCH
class ConsoleSwitchConsoleMgmtRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    enabled: Optional[Annotated[str, StringConstraints(pattern="yes|no")]] = "no"


class ConsoleSwitchTable(RootModel[Dict[str, ConsoleSwitchConsoleMgmtRow]]):
    pass


# sonic-copp.yang :: sonic-copp :: COPP_GROUP
class CoppGroupListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    queue: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 0
    trap_priority: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 0
    trap_action: Literal[
        "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
    ]
    meter_type: Literal["packets", "bytes"]
    mode: Literal["sr_tcm", "tr_tcm", "storm"]
    color: Optional[Literal["aware", "blind"]] = None
    cir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    cbs: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 0
    pir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    pbs: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    green_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"
    yellow_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"
    red_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"


class CoppGroupTable(RootModel[Dict[str, CoppGroupListRow]]):
    pass


# sonic-copp.yang :: sonic-copp :: COPP_TRAP
class CoppTrapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    trap_ids: str
    trap_group: Optional[str] = None
    always_enabled: Optional[bool] = None


class CoppTrapTable(RootModel[Dict[str, CoppTrapListRow]]):
    pass


# sonic-crm.yang :: sonic-crm :: CRM
class CrmConfigRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    acl_counter_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    acl_counter_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_counter_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_group_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    acl_group_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_group_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    acl_entry_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_table_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    acl_table_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    acl_table_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    fdb_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    fdb_entry_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    fdb_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_neighbor_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv4_neighbor_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_neighbor_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_nexthop_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv4_nexthop_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_nexthop_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_route_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv4_route_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv4_route_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_neighbor_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv6_neighbor_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_neighbor_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_nexthop_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv6_nexthop_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_nexthop_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_route_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipv6_route_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipv6_route_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    nexthop_group_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    nexthop_group_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    nexthop_group_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    nexthop_group_member_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    nexthop_group_member_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    nexthop_group_member_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    polling_interval: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dnat_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dnat_entry_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dnat_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    snat_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    snat_entry_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    snat_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipmc_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    ipmc_entry_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    ipmc_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    mpls_inseg_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    mpls_inseg_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    mpls_inseg_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    mpls_nexthop_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    mpls_nexthop_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    mpls_nexthop_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    srv6_my_sid_entry_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    srv6_my_sid_entry_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    srv6_my_sid_entry_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = (
        None
    )
    srv6_nexthop_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    srv6_nexthop_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    srv6_nexthop_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dash_vnet_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_vnet_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dash_vnet_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dash_eni_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_eni_high_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dash_eni_low_threshold: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dash_eni_ether_address_map_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_eni_ether_address_map_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_eni_ether_address_map_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_inbound_routing_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_inbound_routing_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_inbound_routing_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_inbound_routing_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_inbound_routing_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_inbound_routing_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_outbound_routing_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_outbound_routing_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_outbound_routing_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_outbound_routing_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_outbound_routing_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_outbound_routing_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_pa_validation_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_pa_validation_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_pa_validation_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_pa_validation_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_pa_validation_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_pa_validation_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_outbound_ca_to_pa_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_outbound_ca_to_pa_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_outbound_ca_to_pa_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_outbound_ca_to_pa_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_outbound_ca_to_pa_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_outbound_ca_to_pa_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_acl_group_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_acl_group_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_acl_group_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_acl_group_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_acl_group_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_acl_group_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_acl_rule_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv4_acl_rule_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv4_acl_rule_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_acl_rule_threshold_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=64,
                pattern="percentage|used|free|PERCENTAGE|USED|FREE",
            ),
        ]
    ] = None
    dash_ipv6_acl_rule_high_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None
    dash_ipv6_acl_rule_low_threshold: Optional[
        Annotated[int, Field(ge=0, le=65535)]
    ] = None


class CrmTable(RootModel[Dict[str, CrmConfigRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_VNET
class DashVnetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(pattern="Vnet[a-zA-Z0-9_-]+")]] = (
        None
    )
    vni: Optional[Annotated[int, Field(ge=1, le=16777215)]] = None
    guid: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    address_spaces: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                    ),
                ],
                str,
            ]
        ]
    ] = None


class DashVnetTable(RootModel[Dict[str, DashVnetListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_QOS
class DashQosListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    bw: Optional[Annotated[int, Field(ge=0, le=100000000)]] = None
    cps: Optional[Annotated[int, Field(ge=0, le=100000000)]] = None
    flows: Optional[Annotated[int, Field(ge=0, le=100000000)]] = None


class DashQosTable(RootModel[Dict[str, DashQosListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ENI
class DashEniListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    eni_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    mac_address: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    qos: Optional[str] = None
    vnet: Optional[str] = None


class DashEniTable(RootModel[Dict[str, DashEniListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ACL_IN
class DashAclInListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    eni: Optional[str] = None
    stage: Optional[Annotated[int, Field(ge=1, le=5)]] = None
    acl_group_id: Optional[str] = None


class DashAclInTable(RootModel[Dict[str, DashAclInListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ACL_OUT
class DashAclOutListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    eni: Optional[str] = None
    stage: Optional[Annotated[int, Field(ge=1, le=5)]] = None
    acl_group_id: Optional[str] = None


class DashAclOutTable(RootModel[Dict[str, DashAclOutListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ACL_GROUP
class DashAclGroupListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    ip_version: Optional[Annotated[str, StringConstraints(pattern="ipv4|ipv6")]] = None
    guid: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )


class DashAclGroupTable(RootModel[Dict[str, DashAclGroupListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ACL_RULE
class DashAclRuleListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    acl_group_id: Optional[str] = None
    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    priority: Optional[Annotated[int, Field(ge=0, le=16777215)]] = None
    action: Optional[Annotated[str, StringConstraints(pattern="allow|deny")]] = None
    terminating: Optional[bool] = False
    ip_protocol: Optional[List[Literal["TCP", "UDP"]]] = None
    src_addr: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                    ),
                ],
                str,
            ]
        ]
    ] = None
    dst_addr: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                    ),
                ],
                str,
            ]
        ]
    ] = None
    src_port: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="([0-9]{1,4}|[0-5][0-9]{4}|[6][0-4][0-9]{3}|[6][5][0-2][0-9]{2}|[6][5][3][0-5]{2}|[6][5][3][6][0-5])-([0-9]{1,4}|[0-5][0-9]{4}|[6][0-4][0-9]{3}|[6][5][0-2][0-9]{2}|[6][5][3][0-5]{2}|[6][5][3][6][0-5])"
                ),
            ]
        ]
    ] = None
    dst_port: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="([0-9]{1,4}|[0-5][0-9]{4}|[6][0-4][0-9]{3}|[6][5][0-2][0-9]{2}|[6][5][3][0-5]{2}|[6][5][3][6][0-5])-([0-9]{1,4}|[0-5][0-9]{4}|[6][0-4][0-9]{3}|[6][5][0-2][0-9]{2}|[6][5][3][0-5]{2}|[6][5][3][6][0-5])"
                ),
            ]
        ]
    ] = None


class DashAclRuleTable(RootModel[Dict[str, DashAclRuleListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_APPLIANCE
class DashApplianceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    sip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    vni: Optional[Annotated[int, Field(ge=1, le=16777215)]] = None


class DashApplianceTable(RootModel[Dict[str, DashApplianceListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ROUTING_TYPE
class DashRoutingTypeListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="direct|vnet|vnet_direct|vnet_encap|drop|appliance|privatelink|privatelinknsg|servicetunnel"
            ),
        ]
    ] = None
    action_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    action_type: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="none|maprouting|direct|staticencap|appliance|4to6|mapdecap|decap|drop"
            ),
        ]
    ] = None
    encap_type: Optional[Annotated[str, StringConstraints(pattern="vxlan|nvgre")]] = (
        None
    )
    vni: Optional[Annotated[int, Field(ge=1, le=16777215)]] = None


class DashRoutingTypeTable(RootModel[Dict[str, DashRoutingTypeListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_ROUTE_TABLE
class DashRouteTableListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    eni: Optional[str] = None
    prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    action_type: Optional[str] = None
    vnet: Optional[str] = None
    appliance: Optional[str] = None
    overlay_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    overlay_sip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    overlay_dip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    underlay_sip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    underlay_dip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None


class DashRouteTableTable(RootModel[Dict[str, DashRouteTableListRow]]):
    pass


# sonic-dash.yang :: sonic-dash :: DASH_VNET_MAPPING_TABLE
class DashVnetMappingTableListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vnet: Optional[str] = None
    ip_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    routing_type: Optional[str] = None
    underlay_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    mac_address: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    use_dst_vni: Optional[bool] = False


class DashVnetMappingTableTable(RootModel[Dict[str, DashVnetMappingTableListRow]]):
    pass


# sonic-debug-counter.yang :: sonic-debug-counter :: DEBUG_COUNTER
class DebugCounterListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    alias: Optional[str] = None
    desc: Optional[str] = None
    group: Optional[str] = None
    drop_monitor_status: Optional[Literal["enabled", "disabled"]] = "disabled"
    window: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = 900
    incident_count_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = 3
    drop_count_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = 100
    type: Literal[
        "PORT_INGRESS_DROPS",
        "PORT_EGRESS_DROPS",
        "SWITCH_INGRESS_DROPS",
        "SWITCH_EGRESS_DROPS",
    ]


class DebugCounterTable(RootModel[Dict[str, DebugCounterListRow]]):
    pass


# sonic-debug-counter.yang :: sonic-debug-counter :: DEBUG_COUNTER_DROP_REASON
class DebugCounterDropReasonListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    reason: Optional[
        Literal[
            "L2_ANY",
            "SMAC_MULTICAST",
            "SMAC_EQUALS_DMAC",
            "DMAC_RESERVED",
            "VLAN_TAG_NOT_ALLOWED",
            "INGRESS_VLAN_FILTER",
            "INGRESS_STP_FILTER",
            "FDB_UC_DISCARD",
            "FDB_MC_DISCARD",
            "L2_LOOPBACK_FILTER",
            "EXCEEDS_L2_MTU",
            "L3_ANY",
            "EXCEEDS_L3_MTU",
            "TTL",
            "L3_LOOPBACK_FILTER",
            "NON_ROUTABLE",
            "NO_L3_HEADER",
            "IP_HEADER_ERROR",
            "UC_DIP_MC_DMAC",
            "DIP_LOOPBACK",
            "SIP_LOOPBACK",
            "SIP_MC",
            "SIP_CLASS_E",
            "SIP_UNSPECIFIED",
            "MC_DMAC_MISMATCH",
            "SIP_EQUALS_DIP",
            "SIP_BC",
            "DIP_LOCAL",
            "DIP_LINK_LOCAL",
            "SIP_LINK_LOCAL",
            "IPV6_MC_SCOPE0",
            "IPV6_MC_SCOPE1",
            "IRIF_DISABLED",
            "ERIF_DISABLED",
            "LPM4_MISS",
            "LPM6_MISS",
            "BLACKHOLE_ROUTE",
            "BLACKHOLE_ARP",
            "UNRESOLVED_NEXT_HOP",
            "L3_EGRESS_LINK_DOWN",
            "DECAP_ERROR",
            "ACL_ANY",
            "ACL_INGRESS_PORT",
            "ACL_INGRESS_LAG",
            "ACL_INGRESS_VLAN",
            "ACL_INGRESS_RIF",
            "ACL_INGRESS_SWITCH",
            "ACL_EGRESS_PORT",
            "ACL_EGRESS_LAG",
            "ACL_EGRESS_VLAN",
            "ACL_EGRESS_RIF",
            "ACL_EGRESS_SWITCH",
            "EGRESS_VLAN_FILTER",
        ]
    ] = None


class DebugCounterDropReasonTable(RootModel[Dict[str, DebugCounterDropReasonListRow]]):
    pass


# sonic-debug-counter.yang :: sonic-debug-counter :: DEBUG_DROP_MONITOR
class DebugDropMonitorConfigRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: Optional[Literal["enabled", "disabled"]] = "disabled"


class DebugDropMonitorTable(RootModel[Dict[str, DebugDropMonitorConfigRow]]):
    pass


# sonic-default-lossless-buffer-parameter.yang :: sonic-default-lossless-buffer-parameter :: DEFAULT_LOSSLESS_BUFFER_PARAMETER
class DefaultLosslessBufferParameterListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    default_dynamic_th: Annotated[int, Field(ge=-8, le=7)]
    over_subscribe_ratio: Optional[Annotated[int, Field(ge=0, le=65535)]] = None


class DefaultLosslessBufferParameterTable(
    RootModel[Dict[str, DefaultLosslessBufferParameterListRow]]
):
    pass


# sonic-device_metadata.yang :: sonic-device_metadata :: DEVICE_METADATA
class DeviceMetadataLocalhostRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hwsku: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    asic_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=16)]
    ] = None
    default_bgp_status: Optional[Literal["up", "down"]] = "up"
    docker_routing_config_mode: Optional[
        Annotated[
            str, StringConstraints(pattern="separated|unified|split|split-unified")
        ]
    ] = "unified"
    hostname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    platform: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    mac: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    default_pfcwd_status: Optional[Literal["disable", "enable"]] = "disable"
    bgp_asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    deployment_id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=255,
                pattern="ToRRouter|LeafRouter|SpineChassisFrontendRouter|ChassisBackendRouter|ASIC|MgmtToRRouter|MgmtLeafRouter|MgmtSpineRouter|MgmtAccessRouter|LowerMgmtAggregator|UpperMgmtAggregator|SpineRouter|UpperSpineRouter|FabricSpineRouter|LowerSpineRouter|BackEndToRRouter|BackEndLeafRouter|EPMS|MgmtTsToR|BmcMgmtToRRouter|SonicHost|SmartSwitchDPU|not-provisioned",
            ),
        ]
    ] = None
    buffer_model: Optional[
        Annotated[str, StringConstraints(pattern="dynamic|traditional")]
    ] = None
    frr_mgmt_framework_config: Optional[bool] = False
    synchronous_mode: Optional[Literal["enable", "disable"]] = "enable"
    yang_config_validation: Optional[Literal["enable", "disable"]] = "disable"
    cloudtype: Optional[str] = None
    region: Optional[str] = None
    sub_role: Optional[str] = None
    downstream_subrole: Optional[str] = None
    resource_type: Optional[str] = None
    mgmt_type: Optional[str] = None
    cluster: Optional[str] = None
    subtype: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="DualToR|SmartSwitch|Supervisor|UpstreamLC|DownstreamLC|LowerSpineRouter"
            ),
        ]
    ] = None
    peer_switch: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    storage_device: Optional[bool] = None
    asic_name: Optional[str] = None
    switch_id: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    switch_type: Optional[
        Annotated[
            str,
            StringConstraints(pattern="chassis-packet|fabric|npu|voq|dpu|dummy-sup"),
        ]
    ] = None
    max_cores: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    dhcp_server: Optional[Literal["enabled", "disabled"]] = None
    bgp_adv_lo_prefix_as_128: Optional[bool] = None
    suppress_fib_pending: Optional[Literal["enabled", "disabled"]] = Field(
        default="disabled", alias="suppress-fib-pending"
    )
    rack_mgmt_map: Optional[
        Annotated[str, StringConstraints(min_length=0, max_length=128)]
    ] = None
    timezone: Optional[str] = "UTC"
    create_only_config_db_buffers: Optional[bool] = None
    supporting_bulk_counter_groups: Optional[List[str]] = None
    bgp_router_id: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    chassis_hostname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    slice_type: Optional[str] = None
    location_type: Optional[str] = None
    nexthop_group: Optional[Literal["enabled", "disabled"]] = "disabled"
    ring_thread_enabled: Optional[bool] = False
    t2_group_asns: Optional[List[Annotated[int, Field(ge=0, le=4294967295)]]] = None
    anchor_route_source: Optional[List[str]] = None
    orch_northbond_dash_zmq_enabled: Optional[bool] = True
    orch_northbond_route_zmq_enabled: Optional[bool] = False
    syslog_with_osversion: Optional[bool] = False
    syslog_counter: Optional[bool] = False


class DeviceMetadataTable(RootModel[Dict[str, DeviceMetadataLocalhostRow]]):
    pass


# sonic-device_neighbor.yang :: sonic-device_neighbor :: DEVICE_NEIGHBOR
class DeviceNeighborListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    peer_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    mgmt_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    local_port: Optional[str] = None
    port: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    type: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )


class DeviceNeighborTable(RootModel[Dict[str, DeviceNeighborListRow]]):
    pass


# sonic-device_neighbor_metadata.yang :: sonic-device_neighbor_metadata :: DEVICE_NEIGHBOR_METADATA
class DeviceNeighborMetadataListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    cluster: Optional[str] = None
    hwsku: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    lo_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
        ]
    ] = None
    lo_addr_v6: Optional[str] = None
    mgmt_addr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
        ]
    ] = None
    mgmt_addr_v6: Optional[str] = None
    type: Optional[str] = None
    deployment_id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    slice_type: Optional[str] = None


class DeviceNeighborMetadataTable(RootModel[Dict[str, DeviceNeighborMetadataListRow]]):
    pass


# sonic-dhcp-server-ipv4.yang :: sonic-dhcp-server-ipv4 :: DHCP_SERVER_IPV4
class DhcpServerIpv4ListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
            str,
        ]
    ] = None
    gateway: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    lease_time: Annotated[int, Field(ge=1, le=4294967295)]
    mode: Literal["PORT"]
    netmask: Annotated[
        str,
        StringConstraints(
            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
        ),
    ]
    customized_options: Optional[List[str]] = None
    state: Literal["enabled", "disabled"]


class DhcpServerIpv4Table(RootModel[Dict[str, DhcpServerIpv4ListRow]]):
    pass


# sonic-dhcp-server-ipv4.yang :: sonic-dhcp-server-ipv4 :: DHCP_SERVER_IPV4_CUSTOMIZED_OPTIONS
class DhcpServerIpv4CustomizedOptionsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    id: Annotated[int, Field(ge=1, le=254)]
    type: Optional[Literal["string", "ipv4-address", "uint8", "uint16", "uint32"]] = (
        None
    )
    value: Union[
        Annotated[str, StringConstraints(min_length=0, max_length=255)],
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        Annotated[int, Field(ge=0, le=255)],
        Annotated[int, Field(ge=0, le=65535)],
        Annotated[int, Field(ge=0, le=4294967295)],
    ]
    always_send: Optional[bool] = True


class DhcpServerIpv4CustomizedOptionsTable(
    RootModel[Dict[str, DhcpServerIpv4CustomizedOptionsListRow]]
):
    pass


# sonic-dhcp-server-ipv4.yang :: sonic-dhcp-server-ipv4 :: DHCP_SERVER_IPV4_RANGE
class DhcpServerIpv4RangeListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    range: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ]
        ]
    ] = None


class DhcpServerIpv4RangeTable(RootModel[Dict[str, DhcpServerIpv4RangeListRow]]):
    pass


# sonic-dhcp-server-ipv4.yang :: sonic-dhcp-server-ipv4 :: DHCP_SERVER_IPV4_PORT
class DhcpServerIpv4PortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    port: Optional[str] = None
    ips: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ]
        ]
    ] = None
    ranges: Optional[List[str]] = None


class DhcpServerIpv4PortTable(RootModel[Dict[str, DhcpServerIpv4PortListRow]]):
    pass


# sonic-dhcp-server.yang :: sonic-dhcp-server :: DHCP_SERVER
class DhcpServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None


class DhcpServerTable(RootModel[Dict[str, DhcpServerListRow]]):
    pass


# sonic-dhcpv4-relay.yang :: sonic-dhcpv4-relay :: DHCPV4_RELAY
class Dhcpv4RelayListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
            ),
        ]
    ] = None
    dhcpv4_servers: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ]
        ]
    ] = None
    server_vrf: Optional[str] = None
    source_interface: Optional[
        Union[
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    link_selection: Optional[Literal["enable", "disable"]] = "disable"
    vrf_selection: Optional[Literal["enable", "disable"]] = "disable"
    server_id_override: Optional[Literal["enable", "disable"]] = "disable"
    agent_relay_mode: Optional[
        Literal[
            "forward_and_append", "forward_and_replace", "forward_untouched", "discard"
        ]
    ] = "forward_untouched"
    max_hop_count: Optional[Annotated[int, Field(ge=1, le=16)]] = 4


class Dhcpv4RelayTable(RootModel[Dict[str, Dhcpv4RelayListRow]]):
    pass


# sonic-dhcpv6-relay.yang :: sonic-dhcpv6-relay :: DHCP_RELAY
class DhcpRelayListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    dhcpv6_servers: Optional[List[str]] = None
    rfc6939_support: Optional[
        Annotated[str, StringConstraints(pattern="false|true")]
    ] = None
    interface_id: Optional[Annotated[str, StringConstraints(pattern="false|true")]] = (
        None
    )


class DhcpRelayTable(RootModel[Dict[str, DhcpRelayListRow]]):
    pass


# sonic-dns.yang :: sonic-dns :: DNS_NAMESERVER
class DnsNameserverListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None


class DnsNameserverTable(RootModel[Dict[str, DnsNameserverListRow]]):
    pass


# sonic-dot1p-tc-map.yang :: sonic-dot1p-tc-map :: DOT1P_TO_TC_MAP
class Dot1pToTcMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class Dot1pToTcMapTable(RootModel[Dict[str, Dot1pToTcMapListRow]]):
    pass


# sonic-dscp-fc-map.yang :: sonic-dscp-fc-map :: DSCP_TO_FC_MAP
class DscpToFcMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class DscpToFcMapTable(RootModel[Dict[str, DscpToFcMapListRow]]):
    pass


# sonic-dscp-tc-map.yang :: sonic-dscp-tc-map :: DSCP_TO_TC_MAP
class DscpToTcMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class DscpToTcMapTable(RootModel[Dict[str, DscpToTcMapListRow]]):
    pass


# sonic-exp-fc-map.yang :: sonic-exp-fc-map :: EXP_TO_FC_MAP
class ExpToFcMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class ExpToFcMapTable(RootModel[Dict[str, ExpToFcMapListRow]]):
    pass


# sonic-fabric-monitor.yang :: sonic-fabric-monitor :: FABRIC_MONITOR
class FabricMonitorFabricMonitorDataRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    monErrThreshCrcCells: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 1
    monErrThreshRxCells: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 61035156
    monPollThreshIsolation: Optional[Annotated[int, Field(ge=1, le=10)]] = 1
    monPollThreshRecovery: Optional[Annotated[int, Field(ge=1, le=10)]] = 8
    monCapacityThreshWarn: Optional[Annotated[int, Field(ge=5, le=100)]] = 10
    monState: Optional[Literal["enable", "disable"]] = "disable"


class FabricMonitorTable(RootModel[Dict[str, FabricMonitorFabricMonitorDataRow]]):
    pass


# sonic-fabric-port.yang :: sonic-fabric-port :: FABRIC_PORT
class FabricPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    isolateStatus: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "False"
    alias: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    lanes: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    forceUnisolateStatus: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 0


class FabricPortTable(RootModel[Dict[str, FabricPortListRow]]):
    pass


# sonic-feature.yang :: sonic-feature :: FEATURE
class FeatureListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=32)]] = (
        None
    )
    state: Optional[str] = "enabled"
    auto_restart: Optional[str] = "enabled"
    delayed: Optional[str] = "false"
    has_global_scope: Optional[str] = "false"
    has_per_asic_scope: Optional[str] = "false"
    has_per_dpu_scope: Optional[str] = "false"
    high_mem_alert: Optional[str] = "disabled"
    set_owner: Optional[Annotated[str, StringConstraints(pattern="kube|local")]] = (
        "local"
    )
    check_up_status: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"
    support_syslog_rate_limit: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"


class FeatureTable(RootModel[Dict[str, FeatureListRow]]):
    pass


# sonic-fine-grained-ecmp.yang :: sonic-fine-grained-ecmp :: FG_NHG
class FgNhgListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    bucket_size: Annotated[int, Field(ge=0, le=65535)]
    match_mode: Literal["route-based", "nexthop-based", "prefix-based"]
    max_next_hops: Annotated[int, Field(ge=1, le=128)]


class FgNhgTable(RootModel[Dict[str, FgNhgListRow]]):
    pass


# sonic-fine-grained-ecmp.yang :: sonic-fine-grained-ecmp :: FG_NHG_PREFIX
class FgNhgPrefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    FG_NHG: str


class FgNhgPrefixTable(RootModel[Dict[str, FgNhgPrefixListRow]]):
    pass


# sonic-fine-grained-ecmp.yang :: sonic-fine-grained-ecmp :: FG_NHG_MEMBER
class FgNhgMemberListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    next_hop_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    FG_NHG: str
    bank: Annotated[int, Field(ge=0, le=65535)]
    link: Optional[str] = None


class FgNhgMemberTable(RootModel[Dict[str, FgNhgMemberListRow]]):
    pass


# sonic-fips.yang :: sonic-fips :: FIPS
class FipsGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    enable: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"
    enforce: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"


class FipsTable(RootModel[Dict[str, FipsGlobalRow]]):
    pass


# sonic-flex_counter.yang :: sonic-flex_counter :: FLEX_COUNTER_TABLE
class FlexCounterTableBufferPoolWatermarkRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableDebugCounterRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class FlexCounterTableEniRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableDashMeterRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTablePfcwdRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class FlexCounterTablePgDropRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTablePgWatermarkRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTablePortRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTablePortRatesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class FlexCounterTablePortBufferDropRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTableQueueRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTableQueueWatermarkRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None
    BULK_CHUNK_SIZE: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None
    BULK_CHUNK_SIZE_PER_PREFIX: Optional[str] = None


class FlexCounterTableRifRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableRifRatesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class FlexCounterTableAclRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableFlowCntTrapRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableFlowCntRouteRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableTunnelRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableWredEcnQueueRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableWredEcnPortRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableSrv6Row(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableSwitchRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    FLEX_COUNTER_STATUS: Optional[Literal["enable", "disable"]] = None
    FLEX_COUNTER_DELAY_STATUS: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=4294967295)]] = None


class FlexCounterTableTable(
    RootModel[
        Dict[
            str,
            Union[
                FlexCounterTableBufferPoolWatermarkRow,
                FlexCounterTableDebugCounterRow,
                FlexCounterTableEniRow,
                FlexCounterTableDashMeterRow,
                FlexCounterTablePfcwdRow,
                FlexCounterTablePgDropRow,
                FlexCounterTablePgWatermarkRow,
                FlexCounterTablePortRow,
                FlexCounterTablePortRatesRow,
                FlexCounterTablePortBufferDropRow,
                FlexCounterTableQueueRow,
                FlexCounterTableQueueWatermarkRow,
                FlexCounterTableRifRow,
                FlexCounterTableRifRatesRow,
                FlexCounterTableAclRow,
                FlexCounterTableFlowCntTrapRow,
                FlexCounterTableFlowCntRouteRow,
                FlexCounterTableTunnelRow,
                FlexCounterTableWredEcnQueueRow,
                FlexCounterTableWredEcnPortRow,
                FlexCounterTableSrv6Row,
                FlexCounterTableSwitchRow,
            ],
        ]
    ]
):
    pass


# sonic-flex_counter.yang :: sonic-flex_counter :: FLOW_COUNTER_ROUTE_PATTERN
class FlowCounterRoutePatternListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    max_match_count: Optional[Annotated[int, Field(ge=1, le=50)]] = None


class FlowCounterRoutePatternVrfListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[
        Annotated[str, StringConstraints(min_length=0, max_length=16)]
    ] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    max_match_count: Optional[Annotated[int, Field(ge=1, le=50)]] = None


class FlowCounterRoutePatternTable(
    RootModel[
        Dict[
            str,
            Union[FlowCounterRoutePatternListRow, FlowCounterRoutePatternVrfListRow],
        ]
    ]
):
    pass


# sonic-gnmi.yang :: sonic-gnmi :: GNMI
class GnmiCertsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ca_crt: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).cer")
        ]
    ] = None
    server_crt: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).cer")
        ]
    ] = None
    server_key: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).key")
        ]
    ] = None


class GnmiGnmiRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    client_auth: Optional[bool] = None
    log_level: Optional[Annotated[int, Field(ge=0, le=100)]] = None
    port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    save_on_set: Optional[bool] = None
    enable_crl: Optional[bool] = None
    crl_expire_duration: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    user_auth: Optional[
        Annotated[str, StringConstraints(pattern="password|jwt|cert|none")]
    ] = None


class GnmiTable(RootModel[Dict[str, Union[GnmiCertsRow, GnmiGnmiRow]]]):
    pass


# sonic-gnmi.yang :: sonic-gnmi :: GNMI_CLIENT_CERT
class GnmiClientCertListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cert_cname: Optional[str] = None
    role: Optional[List[str]] = None


class GnmiClientCertTable(RootModel[Dict[str, GnmiClientCertListRow]]):
    pass


# sonic-grpcclient.yang :: sonic-grpcclient :: GRPCCLIENT
class GrpcclientConfigRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: Optional[Literal["secure", "insecure"]] = None
    auth_level: Optional[Literal["server", "client"]] = None
    log_level: Optional[Literal["info", "notice", "debug", "warning", "critical"]] = (
        None
    )


class GrpcclientCertsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    client_crt: Optional[str] = None
    client_key: Optional[str] = None
    ca_crt: Optional[str] = None
    grpc_ssl_credential: Optional[str] = None


class GrpcclientTable(
    RootModel[Dict[str, Union[GrpcclientConfigRow, GrpcclientCertsRow]]]
):
    pass


# sonic-hash.yang :: sonic-hash :: SWITCH_HASH
class SwitchHashGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ecmp_hash: Optional[
        List[
            Literal[
                "IN_PORT",
                "DST_MAC",
                "SRC_MAC",
                "ETHERTYPE",
                "VLAN_ID",
                "IP_PROTOCOL",
                "DST_IP",
                "SRC_IP",
                "L4_DST_PORT",
                "L4_SRC_PORT",
                "INNER_DST_MAC",
                "INNER_SRC_MAC",
                "INNER_ETHERTYPE",
                "INNER_IP_PROTOCOL",
                "INNER_DST_IP",
                "INNER_DST_IPV4",
                "INNER_DST_IPV6",
                "INNER_SRC_IP",
                "INNER_SRC_IPV4",
                "INNER_SRC_IPV6",
                "INNER_L4_DST_PORT",
                "INNER_L4_SRC_PORT",
                "IPV6_FLOW_LABEL",
            ]
        ]
    ] = None
    lag_hash: Optional[
        List[
            Literal[
                "IN_PORT",
                "DST_MAC",
                "SRC_MAC",
                "ETHERTYPE",
                "VLAN_ID",
                "IP_PROTOCOL",
                "DST_IP",
                "SRC_IP",
                "L4_DST_PORT",
                "L4_SRC_PORT",
                "INNER_DST_MAC",
                "INNER_SRC_MAC",
                "INNER_ETHERTYPE",
                "INNER_IP_PROTOCOL",
                "INNER_DST_IP",
                "INNER_DST_IPV4",
                "INNER_DST_IPV6",
                "INNER_SRC_IP",
                "INNER_SRC_IPV4",
                "INNER_SRC_IPV6",
                "INNER_L4_DST_PORT",
                "INNER_L4_SRC_PORT",
                "IPV6_FLOW_LABEL",
            ]
        ]
    ] = None
    ecmp_hash_algorithm: Optional[
        Literal["CRC", "XOR", "RANDOM", "CRC_32LO", "CRC_32HI", "CRC_CCITT", "CRC_XOR"]
    ] = None
    lag_hash_algorithm: Optional[
        Literal["CRC", "XOR", "RANDOM", "CRC_32LO", "CRC_32HI", "CRC_CCITT", "CRC_XOR"]
    ] = None


class SwitchHashTable(RootModel[Dict[str, SwitchHashGlobalRow]]):
    pass


# sonic-heartbeat.yang :: sonic-heartbeat :: HEARTBEAT
class HeartbeatListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=32)]] = (
        None
    )
    heartbeat_interval: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 10000
    alert_interval: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 60000


class HeartbeatTable(RootModel[Dict[str, HeartbeatListRow]]):
    pass


# sonic-high-frequency-telemetry.yang :: sonic-high-frequency-telemetry :: HIGH_FREQUENCY_TELEMETRY_PROFILE
class HighFrequencyTelemetryProfileListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    stream_state: Annotated[str, StringConstraints(pattern="enabled|disabled")]
    poll_interval: Annotated[int, Field(ge=0, le=4294967295)]
    otel_endpoint: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    ] = None
    otel_certs: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    ] = None


class HighFrequencyTelemetryProfileTable(
    RootModel[Dict[str, HighFrequencyTelemetryProfileListRow]]
):
    pass


# sonic-high-frequency-telemetry.yang :: sonic-high-frequency-telemetry :: HIGH_FREQUENCY_TELEMETRY_GROUP
class HighFrequencyTelemetryGroupListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    profile_name: Optional[str] = None
    group_name: Optional[
        Literal["PORT", "BUFFER_POOL", "QUEUE", "INGRESS_PRIORITY_GROUP"]
    ] = None
    object_names: Optional[List[str]] = None
    object_counters: Optional[List[str]] = None


class HighFrequencyTelemetryGroupTable(
    RootModel[Dict[str, HighFrequencyTelemetryGroupListRow]]
):
    pass


# sonic-interface.yang :: sonic-interface :: INTERFACE
class InterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    vrf_name: Optional[str] = None
    vnet_name: Optional[str] = None
    nat_zone: Optional[Annotated[int, Field(ge=0, le=3)]] = 0
    mpls: Optional[Literal["enable", "disable"]] = None
    ipv6_use_link_local_only: Optional[Literal["enable", "disable"]] = "disable"
    mac_addr: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    loopback_action: Optional[
        Annotated[str, StringConstraints(pattern="drop|forward")]
    ] = None


class InterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")
    scope: Optional[Literal["global", "local"]] = None
    family: Optional[Literal["IPv4", "IPv6"]] = None


class InterfaceTable(
    RootModel[Dict[str, Union[InterfaceListRow, InterfaceIpprefixListRow]]]
):
    pass


# sonic-kdump.yang :: sonic-kdump :: KDUMP
class KdumpConfigRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    enabled: Optional[bool] = None
    memory: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(((([0-9]+[MG]?)?(-([0-9]+[MG])?):)?[0-9]+[MG],?)+)"
            ),
        ]
    ] = None
    num_dumps: Optional[Annotated[int, Field(ge=1, le=9)]] = None
    remote: Optional[bool] = None
    ssh_string: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="([a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+|[0-9]{1,3}(\\.[0-9]{1,3}){3}))"
            ),
        ]
    ] = None
    ssh_path: Optional[
        Annotated[str, StringConstraints(pattern="(/([a-zA-Z0-9._-]+|\\.)+)+")]
    ] = None


class KdumpTable(RootModel[Dict[str, KdumpConfigRow]]):
    pass


# sonic-kubernetes_master.yang :: sonic-kubernetes_master :: KUBERNETES_MASTER
class KubernetesMasterServerRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    port: Optional[Annotated[int, Field(ge=0, le=65535)]] = 6443
    disable: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"
    insecure: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "true"


class KubernetesMasterTable(RootModel[Dict[str, KubernetesMasterServerRow]]):
    pass


# sonic-lldp.yang :: sonic-lldp :: LLDP
class LldpGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hello_time: Optional[Annotated[int, Field(ge=5, le=254)]] = 30
    multiplier: Optional[Annotated[int, Field(ge=1, le=10)]] = 4
    system_name: Optional[str] = None
    system_description: Optional[str] = None
    supp_mgmt_address_tlv: Optional[bool] = False
    supp_system_capabilities_tlv: Optional[bool] = False
    enabled: Optional[bool] = True
    mode: Optional[Literal["RECEIVE", "TRANSMIT"]] = None


class LldpTable(RootModel[Dict[str, LldpGlobalRow]]):
    pass


# sonic-lldp.yang :: sonic-lldp :: LLDP_PORT
class LldpPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[str] = None
    enabled: Optional[bool] = True
    mode: Optional[Literal["RECEIVE", "TRANSMIT"]] = None


class LldpPortTable(RootModel[Dict[str, LldpPortListRow]]):
    pass


# sonic-logger.yang :: sonic-logger :: LOGGER
class LoggerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    LOGLEVEL: Union[
        Literal["EMERG", "ALERT", "CRIT", "ERROR", "WARN", "NOTICE", "INFO", "DEBUG"],
        Literal[
            "SAI_LOG_LEVEL_CRITICAL",
            "SAI_LOG_LEVEL_ERROR",
            "SAI_LOG_LEVEL_WARN",
            "SAI_LOG_LEVEL_NOTICE",
            "SAI_LOG_LEVEL_INFO",
            "SAI_LOG_LEVEL_DEBUG",
        ],
    ]
    LOGOUTPUT: Optional[Literal["SYSLOG", "STDOUT", "STDERR"]] = "SYSLOG"
    require_manual_refresh: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class LoggerTable(RootModel[Dict[str, LoggerListRow]]):
    pass


# sonic-loopback-interface.yang :: sonic-loopback-interface :: LOOPBACK_INTERFACE
class LoopbackInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=15)]] = (
        None
    )
    vrf_name: Optional[str] = None
    nat_zone: Optional[Annotated[int, Field(ge=0, le=3)]] = 0
    admin_status: Optional[Literal["up", "down"]] = "up"


class LoopbackInterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")
    scope: Optional[Literal["global", "local"]] = None
    family: Optional[Literal["IPv4", "IPv6"]] = None


class LoopbackInterfaceTable(
    RootModel[
        Dict[str, Union[LoopbackInterfaceListRow, LoopbackInterfaceIpprefixListRow]]
    ]
):
    pass


# sonic-lossless-traffic-pattern.yang :: sonic-lossless-traffic-pattern :: LOSSLESS_TRAFFIC_PATTERN
class LosslessTrafficPatternListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    mtu: Annotated[int, Field(ge=1, le=9216)]
    small_packet_percentage: Annotated[int, Field(ge=0, le=100)]


class LosslessTrafficPatternTable(RootModel[Dict[str, LosslessTrafficPatternListRow]]):
    pass


# sonic-macsec.yang :: sonic-macsec :: MACSEC_PROFILE
class MacsecProfileListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    priority: Optional[Annotated[int, Field(ge=0, le=255)]] = 255
    cipher_suite: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="GCM-AES-128|GCM-AES-256|GCM-AES-XPN-128|GCM-AES-XPN-256"
            ),
        ]
    ] = "GCM-AES-128"
    primary_cak: Annotated[
        str, StringConstraints(pattern="[0-9a-fA-F]{66}|[0-9a-fA-F]{130}")
    ]
    primary_ckn: Annotated[
        str, StringConstraints(pattern="[0-9a-fA-F]{32}|[0-9a-fA-F]{64}")
    ]
    fallback_cak: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{66}|[0-9a-fA-F]{130}")]
    ] = None
    fallback_ckn: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{32}|[0-9a-fA-F]{64}")]
    ] = None
    policy: Optional[
        Annotated[str, StringConstraints(pattern="integrity_only|security")]
    ] = "security"
    enable_replay_protect: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "false"
    replay_window: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    send_sci: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "true"
    rekey_period: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 0


class MacsecProfileTable(RootModel[Dict[str, MacsecProfileListRow]]):
    pass


# sonic-mclag.yang :: sonic-mclag :: MCLAG_DOMAIN
class MclagDomainListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    domain_id: Optional[Annotated[int, Field(ge=1, le=4095)]] = None
    source_ip: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    peer_ip: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    peer_link: Optional[str] = None
    keepalive_interval: Optional[Annotated[int, Field(ge=1, le=60)]] = 1
    session_timeout: Optional[Annotated[int, Field(ge=1, le=3600)]] = 30


class MclagDomainTable(RootModel[Dict[str, MclagDomainListRow]]):
    pass


# sonic-mclag.yang :: sonic-mclag :: MCLAG_INTERFACE
class MclagInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    domain_id: Optional[str] = None
    if_name: Optional[str] = None
    if_type: Optional[str] = None


class MclagInterfaceTable(RootModel[Dict[str, MclagInterfaceListRow]]):
    pass


# sonic-mclag.yang :: sonic-mclag :: MCLAG_UNIQUE_IP
class MclagUniqueIpListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    if_name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
            ),
        ]
    ] = None
    unique_ip: Optional[Literal["enable"]] = None


class MclagUniqueIpTable(RootModel[Dict[str, MclagUniqueIpListRow]]):
    pass


# sonic-memory-statistics.yang :: sonic-memory-statistics :: MEMORY_STATISTICS
class MemoryStatisticsMemoryStatisticsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    enabled: Optional[bool] = False
    sampling_interval: Optional[Annotated[int, Field(ge=3, le=15)]] = 5
    retention_period: Optional[Annotated[int, Field(ge=1, le=30)]] = 15


class MemoryStatisticsTable(RootModel[Dict[str, MemoryStatisticsMemoryStatisticsRow]]):
    pass


# sonic-mgmt_interface.yang :: sonic-mgmt_interface :: MGMT_INTERFACE
class MgmtInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    gwaddr: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    forced_mgmt_routes: Optional[
        List[
            Union[
                Union[
                    Annotated[
                        str,
                        StringConstraints(
                            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                        ),
                    ],
                    str,
                ],
                Union[
                    Annotated[
                        str,
                        StringConstraints(
                            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                        ),
                    ],
                    str,
                ],
            ]
        ]
    ] = None


class MgmtInterfaceTable(RootModel[Dict[str, MgmtInterfaceListRow]]):
    pass


# sonic-mgmt_port.yang :: sonic-mgmt_port :: MGMT_PORT
class MgmtPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="eth([1-3][0-9]{3}|[1-9][0-9]{2}|[1-9][0-9]|[0-9])"
            ),
        ]
    ] = None
    speed: Optional[Annotated[int, Field(ge=10, le=1000)]] = None
    autoneg: Optional[Annotated[str, StringConstraints(pattern="on|off")]] = None
    alias: Optional[str] = None
    description: Optional[str] = None
    mtu: Optional[Annotated[int, Field(ge=1500, le=9216)]] = 1500
    admin_status: Optional[Literal["up", "down"]] = "up"


class MgmtPortTable(RootModel[Dict[str, MgmtPortListRow]]):
    pass


# sonic-mgmt_vrf.yang :: sonic-mgmt_vrf :: MGMT_VRF_CONFIG
class MgmtVrfConfigVrfGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    mgmtVrfEnabled: Optional[bool] = False


class MgmtVrfConfigTable(RootModel[Dict[str, MgmtVrfConfigVrfGlobalRow]]):
    pass


# sonic-mirror-session.yang :: sonic-mirror-session :: MIRROR_SESSION
class MirrorSessionListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    type: Optional[Literal["ERSPAN", "SPAN"]] = "ERSPAN"
    src_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    dst_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    gre_type: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=6,
                pattern="0[xX][0-9a-fA-F]*|([0-9]|[1-5]?[0-9]{2,4}|6[1-4][0-9]{3}|65[1-4][0-9]{2}|655[1-2][0-9]|6553[0-5])",
            ),
        ]
    ] = "0x88be"
    dscp: Optional[Annotated[int, Field(ge=0, le=63)]] = None
    ttl: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    queue: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    dst_port: Optional[Union[str, Annotated[str, StringConstraints(pattern="CPU")]]] = (
        None
    )
    src_port: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    ] = None
    direction: Optional[Literal["RX", "TX", "BOTH"]] = "BOTH"
    policer: Optional[str] = None


class MirrorSessionTable(RootModel[Dict[str, MirrorSessionListRow]]):
    pass


# sonic-mpls-tc-map.yang :: sonic-mpls-tc-map :: MPLS_TC_TO_TC_MAP
class MplsTcToTcMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class MplsTcToTcMapTable(RootModel[Dict[str, MplsTcToTcMapListRow]]):
    pass


# sonic-mux-cable.yang :: sonic-mux-cable :: MUX_CABLE
class MuxCableListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[str] = None
    cable_type: Optional[Literal["active-active", "active-standby"]] = "active-standby"
    prober_type: Optional[Literal["hardware", "software"]] = "software"
    server_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
            ),
        ]
    ] = None
    server_ipv6: Optional[str] = None
    soc_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
            ),
        ]
    ] = None
    soc_ipv6: Optional[str] = None
    state: Optional[Literal["auto", "manual", "detach", "active", "standby"]] = "auto"


class MuxCableTable(RootModel[Dict[str, MuxCableListRow]]):
    pass


# sonic-mux-linkmgr.yang :: sonic-mux-linkmgr :: MUX_LINKMGR
class MuxLinkmgrLinkProberRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    interval_v4: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 100
    interval_v6: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 1000
    positive_signal_count: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 1
    negative_signal_count: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 3
    suspend_timer: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    use_well_known_mac: Optional[Literal["enabled", "disabled"]] = None
    src_mac: Optional[Literal["ToRMac", "VlanMac"]] = None
    interval_pck_loss_count_update: Optional[
        Annotated[int, Field(ge=0, le=4294967295)]
    ] = None


class MuxLinkmgrTimedOscillationRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    oscillation_enabled: Optional[bool] = True
    interval_sec: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 300


class MuxLinkmgrMuxloggerRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    log_verbosity: Optional[Literal["trace", "debug", "info", "error", "fatal"]] = None


class MuxLinkmgrServiceMgmtRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kill_radv: Optional[Literal["True", "False"]] = "True"


class MuxLinkmgrTable(
    RootModel[
        Dict[
            str,
            Union[
                MuxLinkmgrLinkProberRow,
                MuxLinkmgrTimedOscillationRow,
                MuxLinkmgrMuxloggerRow,
                MuxLinkmgrServiceMgmtRow,
            ],
        ]
    ]
):
    pass


# sonic-nat.yang :: sonic-nat :: STATIC_NAPT
class StaticNaptListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    global_ip: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    ip_protocol: Optional[Literal["TCP", "UDP"]] = None
    global_l4_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    local_ip: Annotated[
        str,
        StringConstraints(
            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
        ),
    ]
    local_port: Annotated[int, Field(ge=0, le=65535)]
    nat_type: Optional[Literal["snat", "dnat"]] = "dnat"
    twice_nat_id: Optional[Annotated[int, Field(ge=1, le=9999)]] = None


class StaticNaptTable(RootModel[Dict[str, StaticNaptListRow]]):
    pass


# sonic-nat.yang :: sonic-nat :: STATIC_NAT
class StaticNatListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    global_ip: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    local_ip: Annotated[
        str,
        StringConstraints(
            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
        ),
    ]
    nat_type: Optional[Literal["snat", "dnat"]] = "dnat"
    twice_nat_id: Optional[Annotated[int, Field(ge=1, le=9999)]] = None


class StaticNatTable(RootModel[Dict[str, StaticNatListRow]]):
    pass


# sonic-nat.yang :: sonic-nat :: NAT_GLOBAL
class NatGlobalValuesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    admin_mode: Optional[Literal["enabled", "disabled"]] = "disabled"
    nat_timeout: Optional[Annotated[int, Field(ge=300, le=432000)]] = 600
    nat_tcp_timeout: Optional[Annotated[int, Field(ge=300, le=432000)]] = 86400
    nat_udp_timeout: Optional[Annotated[int, Field(ge=120, le=600)]] = 300


class NatGlobalTable(RootModel[Dict[str, NatGlobalValuesRow]]):
    pass


# sonic-nat.yang :: sonic-nat :: NAT_POOL
class NatPoolListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    nat_ip: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        Annotated[
            str,
            StringConstraints(
                pattern="(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(-(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]))?"
            ),
        ],
    ]
    nat_port: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]{1,4}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-4])(-)([0-9]{1,4}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))"
            ),
        ]
    ] = None


class NatPoolTable(RootModel[Dict[str, NatPoolListRow]]):
    pass


# sonic-nat.yang :: sonic-nat :: NAT_BINDINGS
class NatBindingsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    nat_pool: str
    nat_type: Optional[Literal["snat", "dnat"]] = "snat"
    twice_nat_id: Optional[Annotated[int, Field(ge=1, le=9999)]] = None


class NatBindingsTable(RootModel[Dict[str, NatBindingsListRow]]):
    pass


# sonic-neigh.yang :: sonic-neigh :: NEIGH
class NeighListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[
        Union[str, Annotated[str, StringConstraints(pattern="Vlan[0-9]+")]]
    ] = None
    neighbor: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    neigh: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    family: Optional[
        Annotated[str, StringConstraints(pattern="IPv4|IPV4|IPv6|IPV6")]
    ] = None


class NeighTable(RootModel[Dict[str, NeighListRow]]):
    pass


# sonic-ntp.yang :: sonic-ntp :: NTP
class NtpGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    src_intf: Optional[
        List[Union[str, Annotated[str, StringConstraints(pattern="eth0")]]]
    ] = None
    vrf: Optional[Annotated[str, StringConstraints(pattern="mgmt|default")]] = None
    authentication: Optional[Literal["enabled", "disabled"]] = "disabled"
    dhcp: Optional[Literal["enabled", "disabled"]] = "enabled"
    server_role: Optional[Literal["enabled", "disabled"]] = "enabled"
    admin_state: Optional[Literal["enabled", "disabled"]] = "enabled"


class NtpTable(RootModel[Dict[str, NtpGlobalRow]]):
    pass


# sonic-ntp.yang :: sonic-ntp :: NTP_SERVER
class NtpServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    server_address: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    association_type: Optional[Literal["server", "pool"]] = "server"
    iburst: Optional[Literal["on", "off"]] = "on"
    key: Optional[str] = None
    resolve_as: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    admin_state: Optional[Literal["enabled", "disabled"]] = "enabled"
    trusted: Optional[Literal["yes", "no"]] = "no"
    version: Optional[Annotated[int, Field(ge=3, le=4)]] = 4


class NtpServerTable(RootModel[Dict[str, NtpServerListRow]]):
    pass


# sonic-ntp.yang :: sonic-ntp :: NTP_KEY
class NtpKeyListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    trusted: Optional[Literal["yes", "no"]] = "no"
    value: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = (
        None
    )
    type: Optional[Literal["md5", "sha1", "sha256", "sha384", "sha512"]] = "md5"


class NtpKeyTable(RootModel[Dict[str, NtpKeyListRow]]):
    pass


# sonic-nvgre-tunnel.yang :: sonic-nvgre-tunnel :: NVGRE_TUNNEL
class NvgreTunnelListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tunnel_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    src_ip: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        str,
    ]


class NvgreTunnelTable(RootModel[Dict[str, NvgreTunnelListRow]]):
    pass


# sonic-nvgre-tunnel.yang :: sonic-nvgre-tunnel :: NVGRE_TUNNEL_MAP
class NvgreTunnelMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    tunnel_name: Optional[str] = None
    tunnel_map_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    vlan_id: Annotated[int, Field(ge=1, le=4094)]
    vsid: Annotated[int, Field(ge=0, le=16777214)]


class NvgreTunnelMapTable(RootModel[Dict[str, NvgreTunnelMapListRow]]):
    pass


# sonic-passwh.yang :: sonic-passwh :: PASSW_HARDENING
class PasswHardeningPoliciesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    state: Optional[Literal["enabled", "disabled"]] = "disabled"
    expiration: Optional[Annotated[int, Field(ge=-1, le=365)]] = None
    expiration_warning: Optional[Annotated[int, Field(ge=-1, le=30)]] = None
    history_cnt: Optional[Annotated[int, Field(ge=1, le=100)]] = None
    len_min: Optional[Annotated[int, Field(ge=1, le=32)]] = None
    reject_user_passw_match: Optional[bool] = None
    lower_class: Optional[bool] = None
    upper_class: Optional[bool] = None
    digits_class: Optional[bool] = None
    special_class: Optional[bool] = None


class PasswHardeningTable(RootModel[Dict[str, PasswHardeningPoliciesRow]]):
    pass


# sonic-pbh.yang :: sonic-pbh :: PBH_HASH_FIELD
class PbhHashFieldListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hash_field_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    hash_field: Literal[
        "IN_PORT",
        "DST_MAC",
        "SRC_MAC",
        "ETHERTYPE",
        "VLAN_ID",
        "IP_PROTOCOL",
        "DST_IP",
        "SRC_IP",
        "L4_DST_PORT",
        "L4_SRC_PORT",
        "INNER_DST_MAC",
        "INNER_SRC_MAC",
        "INNER_ETHERTYPE",
        "INNER_IP_PROTOCOL",
        "INNER_DST_IP",
        "INNER_DST_IPV4",
        "INNER_DST_IPV6",
        "INNER_SRC_IP",
        "INNER_SRC_IPV4",
        "INNER_SRC_IPV6",
        "INNER_L4_DST_PORT",
        "INNER_L4_SRC_PORT",
        "IPV6_FLOW_LABEL",
    ]
    ip_mask: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        str,
    ]
    sequence_id: Annotated[int, Field(ge=0, le=4294967295)]


class PbhHashFieldTable(RootModel[Dict[str, PbhHashFieldListRow]]):
    pass


# sonic-pbh.yang :: sonic-pbh :: PBH_HASH
class PbhHashListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hash_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    hash_field_list: Optional[List[str]] = None


class PbhHashTable(RootModel[Dict[str, PbhHashListRow]]):
    pass


# sonic-pbh.yang :: sonic-pbh :: PBH_RULE
class PbhRuleListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    table_name: Optional[str] = None
    rule_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    priority: Annotated[int, Field(ge=0, le=4294967295)]
    gre_key: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(0x){1}[a-fA-F0-9]{1,8}/(0x){1}[a-fA-F0-9]{1,8}"
            ),
        ]
    ] = None
    ether_type: Optional[
        Annotated[str, StringConstraints(pattern="(0x){1}[a-fA-F0-9]{1,4}")]
    ] = None
    ip_protocol: Optional[
        Annotated[str, StringConstraints(pattern="(0x){1}[a-fA-F0-9]{1,2}")]
    ] = None
    ipv6_next_header: Optional[
        Annotated[str, StringConstraints(pattern="(0x){1}[a-fA-F0-9]{1,2}")]
    ] = None
    l4_dst_port: Optional[
        Annotated[str, StringConstraints(pattern="(0x){1}[a-fA-F0-9]{1,4}")]
    ] = None
    inner_ether_type: Optional[
        Annotated[str, StringConstraints(pattern="(0x){1}[a-fA-F0-9]{1,4}")]
    ] = None
    hash: str
    packet_action: Optional[Literal["SET_ECMP_HASH", "SET_LAG_HASH"]] = "SET_ECMP_HASH"
    flow_counter: Optional[Literal["DISABLED", "ENABLED"]] = "DISABLED"


class PbhRuleTable(RootModel[Dict[str, PbhRuleListRow]]):
    pass


# sonic-pbh.yang :: sonic-pbh :: PBH_TABLE
class PbhTableListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    table_name: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    interface_list: Optional[List[str]] = None
    description: Annotated[str, StringConstraints(min_length=1, max_length=255)]


class PbhTableTable(RootModel[Dict[str, PbhTableListRow]]):
    pass


# sonic-peer-switch.yang :: sonic-peer-switch :: PEER_SWITCH
class PeerSwitchListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    peer_switch: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    address_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None


class PeerSwitchTable(RootModel[Dict[str, PeerSwitchListRow]]):
    pass


# sonic-pfc-priority-priority-group-map.yang :: sonic-pfc-priority-priority-group-map :: PFC_PRIORITY_TO_PRIORITY_GROUP_MAP
class PfcPriorityToPriorityGroupMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class PfcPriorityToPriorityGroupMapTable(
    RootModel[Dict[str, PfcPriorityToPriorityGroupMapListRow]]
):
    pass


# sonic-pfc-priority-queue-map.yang :: sonic-pfc-priority-queue-map :: MAP_PFC_PRIORITY_TO_QUEUE
class MapPfcPriorityToQueueListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class MapPfcPriorityToQueueTable(RootModel[Dict[str, MapPfcPriorityToQueueListRow]]):
    pass


# sonic-pfcwd.yang :: sonic-pfcwd :: PFC_WD
class PfcWdListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[
        Union[str, Annotated[str, StringConstraints(pattern="GLOBAL")]]
    ] = None
    action: Optional[Literal["drop", "forward", "alert"]] = None
    detection_time: Optional[Annotated[int, Field(ge=100, le=5000)]] = None
    restoration_time: Optional[Annotated[int, Field(ge=100, le=60000)]] = None
    pfc_stat_history: Optional[
        Annotated[str, StringConstraints(pattern="enable|disable")]
    ] = None
    POLL_INTERVAL: Optional[Annotated[int, Field(ge=100, le=3000)]] = None


class PfcWdTable(RootModel[Dict[str, PfcWdListRow]]):
    pass


# sonic-policer.yang :: sonic-policer :: POLICER
class PolicerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    meter_type: Literal["packets", "bytes"]
    mode: Literal["sr_tcm", "tr_tcm", "storm"]
    color: Optional[Literal["aware", "blind"]] = None
    cir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    cbs: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    pir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    pbs: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    green_packet_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"
    yellow_packet_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"
    red_packet_action: Optional[
        Literal[
            "drop", "forward", "copy", "copy_cancel", "trap", "log", "deny", "transit"
        ]
    ] = "forward"


class PolicerTable(RootModel[Dict[str, PolicerListRow]]):
    pass


# sonic-port-qos-map.yang :: sonic-port-qos-map :: PORT_QOS_MAP
class PortQosMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[
        Union[Annotated[str, StringConstraints(pattern="global")], str]
    ] = None
    tc_to_pg_map: Optional[str] = None
    tc_to_queue_map: Optional[str] = None
    pfc_enable: Optional[
        Annotated[str, StringConstraints(pattern="([0-7](,[0-7])*)?")]
    ] = None
    pfcwd_sw_enable: Optional[
        Annotated[str, StringConstraints(pattern="([0-7](,[0-7])*)?")]
    ] = None
    pfc_to_queue_map: Optional[str] = None
    pfc_to_pg_map: Optional[str] = None
    dscp_to_tc_map: Optional[str] = None
    tc_to_dscp_map: Optional[str] = None
    dot1p_to_tc_map: Optional[str] = None
    scheduler: Optional[str] = None


class PortQosMapTable(RootModel[Dict[str, PortQosMapListRow]]):
    pass


# sonic-port.yang :: sonic-port :: PORT
class PortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    core_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=16)]
    ] = None
    core_port_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=16)]
    ] = None
    num_voq: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=16)]
    ] = None
    alias: Optional[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = (
        None
    )
    lanes: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    mode: Optional[Annotated[str, StringConstraints(pattern="routed|access|trunk")]] = (
        None
    )
    description: Optional[
        Annotated[str, StringConstraints(min_length=0, max_length=255)]
    ] = None
    speed: Annotated[int, Field(ge=1, le=1600000)]
    dhcp_rate_limit: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = 300
    link_training: Optional[Annotated[str, StringConstraints(pattern="on|off")]] = None
    autoneg: Optional[Annotated[str, StringConstraints(pattern="on|off")]] = None
    adv_speeds: Optional[
        List[
            Union[
                Annotated[int, Field(ge=1, le=1600000)],
                Annotated[str, StringConstraints(pattern="all")],
            ]
        ]
    ] = None
    interface_type: Optional[
        Literal[
            "CR",
            "CR2",
            "CR4",
            "CR8",
            "SR",
            "SR2",
            "SR4",
            "SR8",
            "LR",
            "LR4",
            "LR8",
            "KR",
            "KR4",
            "KR8",
            "CAUI",
            "GMII",
            "SFI",
            "XLAUI",
            "KR2",
            "CAUI4",
            "XAUI",
            "XFI",
            "XGMII",
            "none",
        ]
    ] = None
    adv_interface_types: Optional[
        List[
            Union[
                Literal[
                    "CR",
                    "CR2",
                    "CR4",
                    "CR8",
                    "SR",
                    "SR2",
                    "SR4",
                    "SR8",
                    "LR",
                    "LR4",
                    "LR8",
                    "KR",
                    "KR4",
                    "KR8",
                    "CAUI",
                    "GMII",
                    "SFI",
                    "XLAUI",
                    "KR2",
                    "CAUI4",
                    "XAUI",
                    "XFI",
                    "XGMII",
                    "none",
                ],
                Annotated[str, StringConstraints(pattern="all")],
            ]
        ]
    ] = None
    mtu: Optional[Annotated[int, Field(ge=68, le=9216)]] = None
    subport: Optional[Annotated[int, Field(ge=0, le=12)]] = None
    index: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    asic_port_name: Optional[str] = None
    role: Optional[Annotated[str, StringConstraints(pattern="Ext|Int|Inb|Rec|Dpc")]] = (
        "Ext"
    )
    admin_status: Optional[Literal["up", "down"]] = "down"
    fec: Optional[Annotated[str, StringConstraints(pattern="rs|fc|none|auto")]] = None
    dom_polling: Optional[Literal["enabled", "disabled"]] = None
    pfc_asym: Optional[Annotated[str, StringConstraints(pattern="on|off")]] = None
    tpid: Optional[
        Annotated[str, StringConstraints(pattern="0x8100|0x9100|0x9200|0x88a8|0x88A8")]
    ] = None
    mux_cable: Optional[bool] = None
    macsec: Optional[str] = None
    tx_power: Optional[float] = None
    laser_freq: Optional[Annotated[int, Field(ge=-2147483648, le=2147483647)]] = None


class PortTable(RootModel[Dict[str, PortListRow]]):
    pass


# sonic-portchannel.yang :: sonic-portchannel :: PORTCHANNEL
class PortchannelListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[str, StringConstraints(pattern="PortChannel[0-9]{1,4}")]
    ] = None
    min_links: Optional[Annotated[int, Field(ge=1, le=1024)]] = None
    mode: Optional[Annotated[str, StringConstraints(pattern="routed|access|trunk")]] = (
        None
    )
    description: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    mtu: Optional[Annotated[int, Field(ge=1, le=9216)]] = None
    admin_status: Literal["up", "down"]
    lacp_key: Optional[
        Union[
            Annotated[str, StringConstraints(pattern="auto")],
            Annotated[int, Field(ge=1, le=65535)],
        ]
    ] = None
    tpid: Optional[
        Annotated[str, StringConstraints(pattern="0x8100|0x9100|0x9200|0x88a8|0x88A8")]
    ] = None
    fallback: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None
    fast_rate: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = None


class PortchannelTable(RootModel[Dict[str, PortchannelListRow]]):
    pass


# sonic-portchannel.yang :: sonic-portchannel :: PORTCHANNEL_MEMBER
class PortchannelMemberListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    port: Optional[str] = None


class PortchannelMemberTable(RootModel[Dict[str, PortchannelMemberListRow]]):
    pass


# sonic-portchannel.yang :: sonic-portchannel :: PORTCHANNEL_INTERFACE
class PortchannelInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    vrf_name: Optional[str] = None
    loopback_action: Optional[
        Annotated[str, StringConstraints(pattern="drop|forward")]
    ] = None
    nat_zone: Optional[Annotated[int, Field(ge=0, le=3)]] = 0
    mpls: Optional[Literal["enable", "disable"]] = None
    ipv6_use_link_local_only: Optional[Literal["enable", "disable"]] = "disable"
    mac_addr: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None


class PortchannelInterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None


class PortchannelInterfaceTable(
    RootModel[
        Dict[
            str, Union[PortchannelInterfaceListRow, PortchannelInterfaceIpprefixListRow]
        ]
    ]
):
    pass


# sonic-queue.yang :: sonic-queue :: QUEUE
class QueueListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[Union[str, Annotated[str, StringConstraints(pattern="CPU")]]] = (
        None
    )
    qindex: Optional[str] = None
    scheduler: Optional[str] = None
    wred_profile: Optional[str] = None


class VoqQueueListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hostname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    asic_name: Optional[
        Annotated[str, StringConstraints(pattern="[Aa][Ss][Ii][Cc][0-9]{1,2}")]
    ] = None
    ifname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=128)]
    ] = None
    qindex: Optional[str] = None
    scheduler: Optional[str] = None
    wred_profile: Optional[str] = None


class QueueTable(RootModel[Dict[str, Union[QueueListRow, VoqQueueListRow]]]):
    pass


# sonic-restapi.yang :: sonic-restapi :: RESTAPI
class RestapiCertsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ca_crt: Optional[
        Annotated[
            str,
            StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).([a-z]+)"),
        ]
    ] = None
    server_crt: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).crt")
        ]
    ] = None
    client_crt_cname: Optional[
        Annotated[
            str,
            StringConstraints(pattern="([a-zA-Z0-9_\\-\\.]+,)*([a-zA-Z0-9_\\-\\.]+)"),
        ]
    ] = None
    server_key: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).key")
        ]
    ] = None


class RestapiConfigRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    client_auth: Optional[bool] = True
    log_level: Optional[Annotated[str, StringConstraints(pattern="trace|info")]] = None
    allow_insecure: Optional[bool] = False


class RestapiTable(RootModel[Dict[str, Union[RestapiCertsRow, RestapiConfigRow]]]):
    pass


# sonic-route-common.yang :: sonic-route-common :: ROUTE_REDISTRIBUTE
class RouteRedistributeListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[
        Union[Annotated[str, StringConstraints(pattern="default")], str]
    ] = None
    src_protocol: Optional[str] = None
    dst_protocol: Optional[str] = None
    addr_family: Optional[str] = None
    route_map: Optional[List[str]] = None
    metric: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None


class RouteRedistributeTable(RootModel[Dict[str, RouteRedistributeListRow]]):
    pass


# sonic-route-map.yang :: sonic-route-map :: ROUTE_MAP_SET
class RouteMapSetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None


class RouteMapSetTable(RootModel[Dict[str, RouteMapSetListRow]]):
    pass


# sonic-route-map.yang :: sonic-route-map :: ROUTE_MAP
class RouteMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    stmt_name: Optional[Annotated[int, Field(ge=1, le=65535)]] = None
    route_operation: Optional[Literal["permit", "deny"]] = None
    match_interface: Optional[
        Union[
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    match_prefix_set: Optional[str] = None
    match_ipv6_prefix_set: Optional[str] = None
    match_protocol: Optional[str] = None
    match_next_hop_set: Optional[str] = None
    match_src_vrf: Optional[
        Union[Annotated[str, StringConstraints(pattern="default")], str]
    ] = None
    match_neighbor: Optional[
        List[
            Union[
                Union[
                    Annotated[
                        str,
                        StringConstraints(
                            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                        ),
                    ],
                    str,
                ],
                str,
                Annotated[
                    str,
                    StringConstraints(
                        pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                    ),
                ],
            ]
        ]
    ] = None
    match_tag: Optional[List[Annotated[int, Field(ge=0, le=4294967295)]]] = None
    match_med: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    match_origin: Optional[str] = None
    match_local_pref: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    match_community: Optional[str] = None
    match_ext_community: Optional[str] = None
    match_as_path: Optional[str] = None
    call_route_map: Optional[str] = None
    set_origin: Optional[str] = None
    set_local_pref: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    set_med: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    set_metric_action: Optional[
        Literal[
            "METRIC_SET_VALUE",
            "METRIC_ADD_VALUE",
            "METRIC_SUBTRACT_VALUE",
            "METRIC_SET_RTT",
            "METRIC_ADD_RTT",
            "METRIC_SUBTRACT_RTT",
        ]
    ] = None
    set_metric: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    set_next_hop: Optional[str] = None
    set_ipv6_next_hop_global: Optional[str] = None
    set_ipv6_next_hop_prefer_global: Optional[bool] = None
    set_repeat_asn: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    set_asn: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    set_asn_list: Optional[str] = None
    set_community_inline: Optional[List[str]] = None
    set_community_ref: Optional[str] = None
    set_ext_community_inline: Optional[List[str]] = None
    set_ext_community_ref: Optional[str] = None
    set_tag: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None


class RouteMapTable(RootModel[Dict[str, RouteMapListRow]]):
    pass


# sonic-routing-policy-sets.yang :: sonic-routing-policy-sets :: PREFIX_SET
class PrefixSetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    mode: Optional[Literal["IPv4", "IPv6"]] = "IPv4"


class PrefixSetTable(RootModel[Dict[str, PrefixSetListRow]]):
    pass


# sonic-routing-policy-sets.yang :: sonic-routing-policy-sets :: PREFIX
class PrefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    masklength_range: Optional[str] = None
    action: Optional[Literal["permit", "deny"]] = None
    sequence_number: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = None


class PrefixNoseqListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    masklength_range: Optional[str] = None
    action: Optional[Literal["permit", "deny"]] = None


class PrefixTable(RootModel[Dict[str, Union[PrefixListRow, PrefixNoseqListRow]]]):
    pass


# sonic-routing-policy-sets.yang :: sonic-routing-policy-sets :: COMMUNITY_SET
class CommunitySetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    set_type: Optional[Literal["STANDARD", "EXPANDED"]] = None
    match_action: Optional[Literal["ANY", "ALL"]] = None
    action: Optional[Literal["permit", "deny"]] = None
    community_member: Optional[List[str]] = None


class CommunitySetTable(RootModel[Dict[str, CommunitySetListRow]]):
    pass


# sonic-routing-policy-sets.yang :: sonic-routing-policy-sets :: EXTENDED_COMMUNITY_SET
class ExtendedCommunitySetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    set_type: Optional[Literal["STANDARD", "EXPANDED"]] = None
    match_action: Optional[Literal["ANY", "ALL"]] = None
    action: Optional[Literal["permit", "deny"]] = None
    community_member: Optional[List[str]] = None


class ExtendedCommunitySetTable(RootModel[Dict[str, ExtendedCommunitySetListRow]]):
    pass


# sonic-routing-policy-sets.yang :: sonic-routing-policy-sets :: AS_PATH_SET
class AsPathSetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    action: Optional[Literal["permit", "deny"]] = None
    as_path_set_member: Optional[List[str]] = None


class AsPathSetTable(RootModel[Dict[str, AsPathSetListRow]]):
    pass


# sonic-scheduler.yang :: sonic-scheduler :: SCHEDULER
class SchedulerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    type: Optional[Literal["DWRR", "WRR", "STRICT"]] = "WRR"
    weight: Optional[Annotated[int, Field(ge=1, le=100)]] = 1
    priority: Optional[Annotated[int, Field(ge=0, le=9)]] = None
    meter_type: Optional[Literal["packets", "bytes"]] = "bytes"
    cir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    pir: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = None
    cbs: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    pbs: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None


class SchedulerTable(RootModel[Dict[str, SchedulerListRow]]):
    pass


# sonic-serial-console.yang :: sonic-serial-console :: SERIAL_CONSOLE
class SerialConsolePoliciesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    inactivity_timeout: Optional[Annotated[int, Field(ge=0, le=35000)]] = 15
    sysrq_capabilities: Optional[Literal["enabled", "disabled"]] = "disabled"


class SerialConsoleTable(RootModel[Dict[str, SerialConsolePoliciesRow]]):
    pass


# sonic-sflow.yang :: sonic-sflow :: SFLOW_COLLECTOR
class SflowCollectorListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = (
        None
    )
    collector_ip: Union[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ],
        str,
    ]
    collector_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = 6343
    collector_vrf: Optional[
        Annotated[str, StringConstraints(pattern="mgmt|default")]
    ] = None


class SflowCollectorTable(RootModel[Dict[str, SflowCollectorListRow]]):
    pass


# sonic-sflow.yang :: sonic-sflow :: SFLOW_SESSION
class SflowSessionListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    port: Optional[Union[str, Annotated[str, StringConstraints(pattern="all")]]] = None
    admin_state: Optional[Literal["up", "down"]] = "up"
    sample_rate: Optional[Annotated[int, Field(ge=256, le=8388608)]] = None
    sample_direction: Optional[Literal["rx", "tx", "both"]] = "rx"


class SflowSessionTable(RootModel[Dict[str, SflowSessionListRow]]):
    pass


# sonic-sflow.yang :: sonic-sflow :: SFLOW
class SflowGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    admin_state: Optional[Literal["up", "down"]] = "down"
    polling_interval: Optional[Annotated[int, Field(ge=0, le=300)]] = 20
    agent_id: Optional[
        Union[
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None
    sample_direction: Optional[Literal["rx", "tx", "both"]] = "rx"


class SflowTable(RootModel[Dict[str, SflowGlobalRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: MID_PLANE_BRIDGE
class MidPlaneBridgeGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    bridge: Optional[Annotated[str, StringConstraints(pattern="bridge-midplane")]] = (
        None
    )
    ip_prefix: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
            ),
        ]
    ] = None


class MidPlaneBridgeTable(RootModel[Dict[str, MidPlaneBridgeGlobalRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: DPUS
class DpusListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    dpu_name: Optional[Annotated[str, StringConstraints(pattern="dpu[0-9]+")]] = None
    midplane_interface: Optional[
        Annotated[str, StringConstraints(pattern="dpu[0-9]+")]
    ] = None


class DpusTable(RootModel[Dict[str, DpusListRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: DPU
class DpuListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    dpu_name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=255, pattern="[a-zA-Z0-9-]+[0-9]"
            ),
        ]
    ] = None
    state: Optional[Literal["up", "down"]] = None
    local_port: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=15)]
    ] = None
    vip_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    vip_ipv6: Optional[str] = None
    pa_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    pa_ipv6: Optional[str] = None
    midplane_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    dpu_id: Optional[Annotated[str, StringConstraints(pattern="[0-7]")]] = None
    vdpu_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    gnmi_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    orchagent_zmq_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    swbus_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None


class DpuTable(RootModel[Dict[str, DpuListRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: REMOTE_DPU
class RemoteDpuListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    dpu_name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=255, pattern="[a-zA-Z0-9-]+[0-9]+"
            ),
        ]
    ] = None
    type: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    pa_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    pa_ipv6: Optional[str] = None
    npu_ipv4: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    npu_ipv6: Optional[str] = None
    dpu_id: Optional[Annotated[str, StringConstraints(pattern="[0-7]")]] = None
    swbus_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None


class RemoteDpuTable(RootModel[Dict[str, RemoteDpuListRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: VDPU
class VdpuListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vdpu_id: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    profile: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    tier: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    main_dpu_ids: Optional[
        List[
            Annotated[
                str,
                StringConstraints(
                    min_length=1, max_length=255, pattern="[a-zA-Z0-9-]+[0-9]+"
                ),
            ]
        ]
    ] = None


class VdpuTable(RootModel[Dict[str, VdpuListRow]]):
    pass


# sonic-smart-switch.yang :: sonic-smart-switch :: DASH_HA_GLOBAL_CONFIG
class DashHaGlobalConfigGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vnet_name: Optional[str] = None
    cp_data_channel_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dp_channel_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dp_channel_src_port_min: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dp_channel_src_port_max: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    dp_channel_probe_interval_ms: Optional[
        Annotated[int, Field(ge=0, le=4294967295)]
    ] = None
    dp_channel_probe_fail_threshold: Optional[
        Annotated[int, Field(ge=0, le=4294967295)]
    ] = None
    dpu_bfd_probe_interval_in_ms: Optional[
        Annotated[int, Field(ge=0, le=4294967295)]
    ] = None
    dpu_bfd_probe_multiplier: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = (
        None
    )


class DashHaGlobalConfigTable(RootModel[Dict[str, DashHaGlobalConfigGlobalRow]]):
    pass


# sonic-snmp.yang :: sonic-snmp :: SNMP
class SnmpContactRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    Contact: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None


class SnmpLocationRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    Location: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None


class SnmpTable(RootModel[Dict[str, Union[SnmpContactRow, SnmpLocationRow]]]):
    pass


# sonic-snmp.yang :: sonic-snmp :: SNMP_COMMUNITY
class SnmpCommunityListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str, StringConstraints(min_length=4, max_length=32, pattern="[^ @,\\\\']*")
        ]
    ] = None
    TYPE: Optional[Literal["RO", "RW"]] = None


class SnmpCommunityTable(RootModel[Dict[str, SnmpCommunityListRow]]):
    pass


# sonic-snmp.yang :: sonic-snmp :: SNMP_USER
class SnmpUserListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str, StringConstraints(min_length=4, max_length=32, pattern="[^ :@,\\\\']*")
        ]
    ] = None
    SNMP_USER_TYPE: Literal["noAuthNoPriv", "AuthNoPriv", "Priv"]
    SNMP_USER_PERMISSION: Literal["RO", "RW"]
    SNMP_USER_AUTH_TYPE: Optional[str] = ""
    SNMP_USER_AUTH_PASSWORD: Optional[
        Annotated[
            str, StringConstraints(min_length=0, max_length=64, pattern="[^ @:]*")
        ]
    ] = None
    SNMP_USER_ENCRYPTION_TYPE: Optional[str] = ""
    SNMP_USER_ENCRYPTION_PASSWORD: Annotated[
        str, StringConstraints(min_length=0, max_length=64, pattern="[^ @:]*")
    ]


class SnmpUserTable(RootModel[Dict[str, SnmpUserListRow]]):
    pass


# sonic-snmp.yang :: sonic-snmp :: SNMP_AGENT_ADDRESS_CONFIG
class SnmpAgentAddressConfigListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    agent_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    port: Optional[
        Union[
            Annotated[str, StringConstraints(pattern="")],
            Annotated[int, Field(ge=0, le=65535)],
        ]
    ] = None
    vrf_name: Optional[
        Union[
            Annotated[str, StringConstraints(pattern="")],
            Annotated[str, StringConstraints(pattern="mgmt")],
            Annotated[str, StringConstraints(pattern="Vrf[a-zA-Z0-9_-]+")],
        ]
    ] = None


class SnmpAgentAddressConfigTable(RootModel[Dict[str, SnmpAgentAddressConfigListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP
class StpListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    keyleaf: Optional[Literal["GLOBAL"]] = None
    mode: Literal["pvst", "mst"]
    rootguard_timeout: Optional[Annotated[int, Field(ge=5, le=600)]] = 30
    forward_delay: Optional[Annotated[int, Field(ge=4, le=30)]] = 15
    hello_time: Optional[Annotated[int, Field(ge=1, le=10)]] = 2
    max_age: Optional[Annotated[int, Field(ge=6, le=40)]] = 20
    priority: Optional[Annotated[int, Field(ge=0, le=61440)]] = 32768


class StpTable(RootModel[Dict[str, StpListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_VLAN
class StpVlanListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    vlanid: Optional[Annotated[int, Field(ge=1, le=4095)]] = None
    enabled: bool
    forward_delay: Optional[Annotated[int, Field(ge=4, le=30)]] = 15
    hello_time: Optional[Annotated[int, Field(ge=1, le=10)]] = 2
    max_age: Optional[Annotated[int, Field(ge=6, le=40)]] = 20
    priority: Optional[Annotated[int, Field(ge=0, le=61440)]] = 32768


class StpVlanTable(RootModel[Dict[str, StpVlanListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_VLAN_PORT
class StpVlanPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vlan_name: Optional[str] = Field(default=None, alias="vlan-name")
    ifname: Optional[str] = None
    path_cost: Optional[Annotated[int, Field(ge=1, le=200000000)]] = 200
    priority: Optional[Annotated[int, Field(ge=0, le=240)]] = 128


class StpVlanPortTable(RootModel[Dict[str, StpVlanPortListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_PORT
class StpPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[str] = None
    enabled: bool
    root_guard: Optional[bool] = False
    bpdu_guard: Optional[bool] = False
    bpdu_guard_do_disable: Optional[bool] = False
    uplink_fast: Optional[bool] = False
    portfast: Optional[bool] = False
    path_cost: Optional[Annotated[int, Field(ge=1, le=200000000)]] = 200
    priority: Optional[Annotated[int, Field(ge=0, le=240)]] = 128
    edge_port: Optional[bool] = False
    link_type: Optional[Literal["auto", "shared", "point-to-point"]] = None


class StpPortTable(RootModel[Dict[str, StpPortListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_MST
class StpMstListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    keyleaf: Optional[Literal["GLOBAL"]] = None
    name: Optional[str] = None
    revision: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    max_hops: Optional[Annotated[int, Field(ge=0, le=255)]] = 20
    max_age: Optional[Annotated[int, Field(ge=0, le=255)]] = 20
    hello_time: Optional[Annotated[int, Field(ge=0, le=255)]] = 2
    forward_delay: Optional[Annotated[int, Field(ge=0, le=255)]] = 15
    hold_count: Optional[Annotated[int, Field(ge=0, le=255)]] = None


class StpMstTable(RootModel[Dict[str, StpMstListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_MST_INST
class StpMstInstListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    instance: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    vlan: Optional[List[str]] = None
    bridge_priority: Optional[Annotated[int, Field(ge=0, le=61440)]] = 32768


class StpMstInstTable(RootModel[Dict[str, StpMstInstListRow]]):
    pass


# sonic-spanning-tree.yang :: sonic-spanning-tree :: STP_MST_PORT
class StpMstPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    inst_id: Optional[str] = None
    ifname: Optional[str] = None
    path_cost: Optional[Annotated[int, Field(ge=1, le=200000000)]] = 200
    priority: Optional[Annotated[int, Field(ge=0, le=240)]] = 128


class StpMstPortTable(RootModel[Dict[str, StpMstPortListRow]]):
    pass


# sonic-srv6.yang :: sonic-srv6 :: SRV6_MY_LOCATORS
class Srv6MyLocatorsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    locator_name: Optional[str] = None
    prefix: str
    block_len: Optional[Annotated[int, Field(ge=1, le=128)]] = 32
    node_len: Optional[Annotated[int, Field(ge=1, le=128)]] = 16
    func_len: Optional[Annotated[int, Field(ge=0, le=128)]] = 16
    arg_len: Optional[Annotated[int, Field(ge=0, le=128)]] = 0
    vrf: Optional[Union[str, Annotated[str, StringConstraints(pattern="default")]]] = (
        "default"
    )


class Srv6MyLocatorsTable(RootModel[Dict[str, Srv6MyLocatorsListRow]]):
    pass


# sonic-srv6.yang :: sonic-srv6 :: SRV6_MY_SIDS
class Srv6MySidsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ip_prefix: Optional[str] = None
    locator: Optional[str] = None
    action: Optional[Literal["uN", "uDT46"]] = None
    decap_vrf: Optional[
        Union[str, Annotated[str, StringConstraints(pattern="default")]]
    ] = "default"
    decap_dscp_mode: Optional[Literal["uniform", "pipe"]] = None


class Srv6MySidsTable(RootModel[Dict[str, Srv6MySidsListRow]]):
    pass


# sonic-ssh-server.yang :: sonic-ssh-server :: SSH_SERVER
class SshServerPoliciesRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    authentication_retries: Optional[Annotated[int, Field(ge=1, le=100)]] = 6
    login_timeout: Optional[Annotated[int, Field(ge=1, le=600)]] = 120
    ports: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="([1-9]|[1-9]\\d{1,3}|[1-5]\\d{4}|6[0-4]\\d{3}|65[0-4]\\d{2}|655[0-2]\\d|6553[0-6])(,([1-9]|[1-9]\\d{1,3}|[1-5]\\d{4}|6[0-4]\\d{3}|65[0-4]\\d{2}|655[0-2]\\d|6553[0-6]))*"
            ),
        ]
    ] = "22"
    inactivity_timeout: Optional[Annotated[int, Field(ge=0, le=35000)]] = 15
    max_sessions: Optional[Annotated[int, Field(ge=0, le=100)]] = 0
    permit_root_login: Optional[
        Literal["yes", "prohibit-password", "forced-commands-only", "no"]
    ] = None
    password_authentication: Optional[bool] = True
    ciphers: Optional[
        List[
            Literal[
                "3des-cbc",
                "aes128-cbc",
                "aes192-cbc",
                "aes256-cbc",
                "aes128-ctr",
                "aes192-ctr",
                "aes256-ctr",
                "aes128-gcm@openssh.com",
                "aes256-gcm@openssh.com",
                "chacha20-poly1305@openssh.com",
            ]
        ]
    ] = None
    kex_algorithms: Optional[
        List[
            Literal[
                "diffie-hellman-group1-sha1",
                "diffie-hellman-group14-sha1",
                "diffie-hellman-group14-sha256",
                "diffie-hellman-group16-sha512",
                "diffie-hellman-group18-sha512",
                "diffie-hellman-group-exchange-sha1",
                "diffie-hellman-group-exchange-sha256",
                "ecdh-sha2-nistp256",
                "ecdh-sha2-nistp384",
                "ecdh-sha2-nistp521",
                "curve25519-sha256",
                "curve25519-sha256@libssh.org",
                "sntrup761x25519-sha512",
                "sntrup761x25519-sha512@openssh.com",
            ]
        ]
    ] = None
    macs: Optional[
        List[
            Literal[
                "hmac-sha1",
                "hmac-sha1-96",
                "hmac-sha2-256",
                "hmac-sha2-512",
                "hmac-md5",
                "hmac-md5-96",
                "umac-64@openssh.com",
                "umac-128@openssh.com",
                "hmac-sha1-etm@openssh.com",
                "hmac-sha1-96-etm@openssh.com",
                "hmac-sha2-256-etm@openssh.com",
                "hmac-sha2-512-etm@openssh.com",
                "hmac-md5-etm@openssh.com",
                "hmac-md5-96-etm@openssh.com",
                "umac-64-etm@openssh.com",
                "umac-128-etm@openssh.com",
            ]
        ]
    ] = None


class SshServerTable(RootModel[Dict[str, SshServerPoliciesRow]]):
    pass


# sonic-static-route.yang :: sonic-static-route :: STATIC_ROUTE
class StaticRouteTemplateListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    nexthop: Optional[str] = None
    ifname: Optional[str] = None
    advertise: Optional[
        Annotated[str, StringConstraints(pattern="((true|false),)*(true|false)")]
    ] = "false"
    bfd: Optional[
        Annotated[str, StringConstraints(pattern="((true|false),)*(true|false)")]
    ] = "false"


class StaticRouteListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vrf_name: Optional[
        Union[
            Annotated[str, StringConstraints(pattern="default")],
            Annotated[str, StringConstraints(pattern="mgmt")],
            Annotated[str, StringConstraints(pattern="Vrf[a-zA-Z0-9_-]+")],
        ]
    ] = None
    prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = None
    nexthop: Optional[str] = None
    ifname: Optional[str] = None
    advertise: Optional[
        Annotated[str, StringConstraints(pattern="((true|false),)*(true|false)")]
    ] = "false"
    distance: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="((25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?),)*(25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?)"
            ),
        ]
    ] = "0"
    nexthop_vrf: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="((((Vrf[a-zA-Z0-9_-]+)|(default)|(mgmt)),)*((Vrf[a-zA-Z0-9_-]+)|(default)|(mgmt)))?"
            ),
        ]
    ] = Field(default=None, alias="nexthop-vrf")
    blackhole: Optional[
        Annotated[str, StringConstraints(pattern="((true|false),)*(true|false)")]
    ] = "false"


class StaticRouteTable(
    RootModel[Dict[str, Union[StaticRouteTemplateListRow, StaticRouteListRow]]]
):
    pass


# sonic-storm-control.yang :: sonic-storm-control :: PORT_STORM_CONTROL
class PortStormControlListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ifname: Optional[str] = None
    storm_type: Optional[
        Literal["broadcast", "unknown-unicast", "unknown-multicast"]
    ] = None
    kbps: Optional[Annotated[int, Field(ge=0, le=100000000)]] = None


class PortStormControlTable(RootModel[Dict[str, PortStormControlListRow]]):
    pass


# sonic-stormond-config.yang :: sonic-stormond-config :: STORMOND_CONFIG
class StormondConfigIntervalsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    daemon_polling_interval: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = 3600
    fsstats_sync_interval: Optional[Annotated[int, Field(ge=1, le=4294967295)]] = 86400


class StormondConfigTable(RootModel[Dict[str, StormondConfigIntervalsRow]]):
    pass


# sonic-subnet-decap.yang :: sonic-subnet-decap :: SUBNET_DECAP
class SubnetDecapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    status: Optional[Literal["enable", "disable"]] = "disable"
    src_ip: Annotated[
        str,
        StringConstraints(
            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
        ),
    ]
    src_ip_v6: str


class SubnetDecapTable(RootModel[Dict[str, SubnetDecapListRow]]):
    pass


# sonic-suppress-asic-sdk-health-event.yang :: sonic-suppress-asic-sdk-health-event :: SUPPRESS_ASIC_SDK_HEALTH_EVENT
class SuppressAsicSdkHealthEventListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    severity: Optional[Literal["fatal", "warning", "notice"]] = None
    max_events: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    categories: Optional[List[Literal["software", "firmware", "cpu_hw", "asic_hw"]]] = (
        None
    )


class SuppressAsicSdkHealthEventTable(
    RootModel[Dict[str, SuppressAsicSdkHealthEventListRow]]
):
    pass


# sonic-syslog.yang :: sonic-syslog :: SYSLOG_SERVER
class SyslogServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    server_address: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    source: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    vrf: Optional[Union[str, Literal["default", "mgmt"]]] = None
    filter: Optional[Literal["include", "exclude"]] = None
    filter_regex: Optional[str] = None
    protocol: Optional[Literal["tcp", "udp"]] = None
    severity: Optional[
        Literal["none", "debug", "info", "notice", "warn", "error", "crit"]
    ] = None


class SyslogServerTable(RootModel[Dict[str, SyslogServerListRow]]):
    pass


# sonic-syslog.yang :: sonic-syslog :: SYSLOG_CONFIG
class SyslogConfigGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    rate_limit_interval: Optional[Annotated[int, Field(ge=0, le=2147483647)]] = None
    rate_limit_burst: Optional[Annotated[int, Field(ge=0, le=2147483647)]] = None
    format: Optional[Literal["welf", "standard"]] = "standard"
    welf_firewall_name: Optional[str] = None
    severity: Optional[
        Literal["none", "debug", "info", "notice", "warn", "error", "crit"]
    ] = "notice"


class SyslogConfigTable(RootModel[Dict[str, SyslogConfigGlobalRow]]):
    pass


# sonic-syslog.yang :: sonic-syslog :: SYSLOG_CONFIG_FEATURE
class SyslogConfigFeatureListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    service: Optional[str] = None
    rate_limit_interval: Optional[Annotated[int, Field(ge=0, le=2147483647)]] = None
    rate_limit_burst: Optional[Annotated[int, Field(ge=0, le=2147483647)]] = None


class SyslogConfigFeatureTable(RootModel[Dict[str, SyslogConfigFeatureListRow]]):
    pass


# sonic-system-aaa.yang :: sonic-system-aaa :: AAA
class AaaListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: Optional[Literal["authentication", "authorization", "accounting"]] = None
    login: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="((ldap|tacacs\\+|local|radius|default),)*(ldap|tacacs\\+|local|radius|default)"
            ),
        ]
    ] = "local"
    failthrough: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "False"
    fallback: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "False"
    debug: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "False"
    trace: Optional[
        Annotated[str, StringConstraints(pattern="false|true|False|True")]
    ] = "False"


class AaaTable(RootModel[Dict[str, AaaListRow]]):
    pass


# sonic-system-defaults.yang :: sonic-system-defaults :: SYSTEM_DEFAULTS
class SystemDefaultsListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=32)]] = (
        None
    )
    status: Optional[Literal["enabled", "disabled"]] = None


class SystemDefaultsTable(RootModel[Dict[str, SystemDefaultsListRow]]):
    pass


# sonic-system-ldap.yang :: sonic-system-ldap :: LDAP_SERVER
class LdapServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hostname: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    priority: Optional[Annotated[int, Field(ge=1, le=8)]] = 1


class LdapServerTable(RootModel[Dict[str, LdapServerListRow]]):
    pass


# sonic-system-ldap.yang :: sonic-system-ldap :: LDAP
class LdapGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    bind_dn: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=65)]
    ] = None
    bind_password: Optional[
        Annotated[
            str, StringConstraints(min_length=1, max_length=65, pattern="[^ #,]*")
        ]
    ] = None
    bind_timeout: Optional[Annotated[int, Field(ge=1, le=120)]] = 5
    version: Optional[Annotated[int, Field(ge=1, le=3)]] = 3
    base_dn: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=65)]
    ] = None
    port: Optional[Annotated[int, Field(ge=0, le=65535)]] = 389
    timeout: Optional[Annotated[int, Field(ge=1, le=60)]] = None


class LdapTable(RootModel[Dict[str, LdapGlobalRow]]):
    pass


# sonic-system-port.yang :: sonic-system-port :: SYSTEM_PORT
class SystemPortListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    hostname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=63)]
    ] = None
    asic_name: Optional[
        Annotated[str, StringConstraints(pattern="[Aa][Ss][Ii][Cc][0-9]{1,2}")]
    ] = None
    ifname: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=128)]
    ] = None
    core_index: Optional[Annotated[int, Field(ge=0, le=7)]] = None
    core_port_index: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    num_voq: Optional[Annotated[int, Field(ge=1, le=8)]] = None
    speed: Optional[Annotated[int, Field(ge=1, le=800000)]] = None
    switch_id: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    system_port_id: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None


class SystemPortTable(RootModel[Dict[str, SystemPortListRow]]):
    pass


# sonic-system-radius.yang :: sonic-system-radius :: RADIUS
class RadiusGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    passkey: Optional[
        Annotated[
            str, StringConstraints(min_length=1, max_length=65, pattern="[^ #,]*")
        ]
    ] = None
    auth_type: Optional[Literal["pap", "chap", "mschapv2"]] = "pap"
    src_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    nas_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    statistics: Optional[bool] = None
    timeout: Optional[Annotated[int, Field(ge=1, le=60)]] = 5
    retransmit: Optional[Annotated[int, Field(ge=0, le=10)]] = 3


class RadiusTable(RootModel[Dict[str, RadiusGlobalRow]]):
    pass


# sonic-system-radius.yang :: sonic-system-radius :: RADIUS_SERVER
class RadiusServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ipaddress: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    auth_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = 1812
    passkey: Optional[
        Annotated[
            str, StringConstraints(min_length=1, max_length=65, pattern="[^ #,]*")
        ]
    ] = None
    auth_type: Optional[Literal["pap", "chap", "mschapv2"]] = "pap"
    priority: Optional[Annotated[int, Field(ge=1, le=64)]] = None
    timeout: Optional[Annotated[int, Field(ge=1, le=60)]] = 5
    retransmit: Optional[Annotated[int, Field(ge=0, le=10)]] = 3
    vrf: Optional[Annotated[str, StringConstraints(pattern="mgmt|default")]] = None
    src_intf: Optional[
        Union[
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None


class RadiusServerTable(RootModel[Dict[str, RadiusServerListRow]]):
    pass


# sonic-system-tacacs.yang :: sonic-system-tacacs :: TACPLUS_SERVER
class TacplusServerListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ipaddress: Optional[
        Union[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ],
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=253,
                    pattern="((([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.)*([a-zA-Z0-9_]([a-zA-Z0-9\\-_]){0,61})?[a-zA-Z0-9]\\.?)|\\.",
                ),
            ],
        ]
    ] = None
    priority: Optional[Annotated[int, Field(ge=1, le=64)]] = 1
    tcp_port: Optional[Annotated[int, Field(ge=0, le=65535)]] = 49
    timeout: Optional[Annotated[int, Field(ge=1, le=60)]] = 5
    auth_type: Optional[Literal["pap", "chap", "mschap", "login"]] = "pap"
    passkey: Optional[
        Annotated[
            str, StringConstraints(min_length=1, max_length=256, pattern="[^ #,]*")
        ]
    ] = None
    vrf: Optional[Annotated[str, StringConstraints(pattern="mgmt|default")]] = None


class TacplusServerTable(RootModel[Dict[str, TacplusServerListRow]]):
    pass


# sonic-system-tacacs.yang :: sonic-system-tacacs :: TACPLUS
class TacplusGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    auth_type: Optional[Literal["pap", "chap", "mschap", "login"]] = "pap"
    timeout: Optional[Annotated[int, Field(ge=1, le=60)]] = 5
    key_encrypt: Optional[bool] = None
    passkey: Optional[
        Annotated[
            str, StringConstraints(min_length=1, max_length=256, pattern="[^ #,]*")
        ]
    ] = None
    src_intf: Optional[
        Union[
            str,
            Annotated[
                str,
                StringConstraints(
                    pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
                ),
            ],
        ]
    ] = None


class TacplusTable(RootModel[Dict[str, TacplusGlobalRow]]):
    pass


# sonic-tc-dscp-map.yang :: sonic-tc-dscp-map :: TC_TO_DSCP_MAP
class TcToDscpMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class TcToDscpMapTable(RootModel[Dict[str, TcToDscpMapListRow]]):
    pass


# sonic-tc-priority-group-map.yang :: sonic-tc-priority-group-map :: TC_TO_PRIORITY_GROUP_MAP
class TcToPriorityGroupMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class TcToPriorityGroupMapTable(RootModel[Dict[str, TcToPriorityGroupMapListRow]]):
    pass


# sonic-tc-queue-map.yang :: sonic-tc-queue-map :: TC_TO_QUEUE_MAP
class TcToQueueMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None


class TcToQueueMapTable(RootModel[Dict[str, TcToQueueMapListRow]]):
    pass


# sonic-telemetry.yang :: sonic-telemetry :: TELEMETRY
class TelemetryCertsRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ca_crt: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).cer")
        ]
    ] = None
    server_crt: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).cer")
        ]
    ] = None
    server_key: Optional[
        Annotated[
            str, StringConstraints(pattern="(/[a-zA-Z0-9_-]+)*/([a-zA-Z0-9_-]+).key")
        ]
    ] = None


class TelemetryGnmiRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    client_auth: Optional[bool] = None
    log_level: Optional[Annotated[int, Field(ge=0, le=100)]] = None
    port: Optional[Annotated[int, Field(ge=0, le=65535)]] = None
    save_on_set: Optional[bool] = None
    enable_crl: Optional[bool] = None
    crl_expire_duration: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    user_auth: Optional[
        Annotated[str, StringConstraints(pattern="password|jwt|cert|none")]
    ] = None


class TelemetryTable(RootModel[Dict[str, Union[TelemetryCertsRow, TelemetryGnmiRow]]]):
    pass


# sonic-telemetry_client.yang :: sonic-telemetry_client :: TELEMETRY_CLIENT
class TelemetryClientListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    prefix: Optional[
        Annotated[str, StringConstraints(pattern="Subscription|DestinationGroup")]
    ] = None
    name: Optional[str] = None
    dst_addr: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="((([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]):([0-9]|[1-9]\\d{1,3}|[1-5]\\d{1,4}|6[0-4]\\d{1,3}|65[0-4]\\d{1,2}|655[0-2][0-9]|6553[0-5]),?)+"
            ),
        ]
    ] = None
    dst_group: Optional[str] = None
    path_target: Optional[
        Literal["APPL_DB", "CONFIG_DB", "COUNTERS_DB", "STATE_DB", "OTHERS"]
    ] = None
    paths: Optional[str] = None
    report_interval: Optional[Annotated[int, Field(ge=0, le=18446744073709551615)]] = (
        5000
    )
    report_type: Optional[Literal["periodic", "stream", "once"]] = None


class TelemetryClientTable(RootModel[Dict[str, TelemetryClientListRow]]):
    pass


# sonic-trimming.yang :: sonic-trimming :: SWITCH_TRIMMING
class SwitchTrimmingGlobalRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    size: Optional[Annotated[int, Field(ge=0, le=4294967295)]] = None
    dscp_value: Optional[
        Union[
            Annotated[int, Field(ge=0, le=63)],
            Annotated[str, StringConstraints(pattern="from-tc")],
        ]
    ] = None
    tc_value: Optional[Annotated[int, Field(ge=0, le=255)]] = None
    queue_index: Optional[
        Union[
            Annotated[int, Field(ge=0, le=255)],
            Annotated[str, StringConstraints(pattern="dynamic")],
        ]
    ] = None


class SwitchTrimmingTable(RootModel[Dict[str, SwitchTrimmingGlobalRow]]):
    pass


# sonic-tunnel.yang :: sonic-tunnel :: TUNNEL
class TunnelListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    mux_tunnel: Optional[
        Annotated[str, StringConstraints(pattern="MuxTunnel[0-9]+")]
    ] = None
    dscp_mode: Optional[Annotated[str, StringConstraints(pattern="uniform|pipe")]] = (
        None
    )
    src_ip: Optional[str] = None
    dst_ip: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
            ),
        ]
    ] = None
    ecn_mode: Optional[
        Annotated[str, StringConstraints(pattern="copy_from_outer|standard")]
    ] = None
    encap_ecn_mode: Optional[Annotated[str, StringConstraints(pattern="standard")]] = (
        None
    )
    ttl_mode: Optional[Annotated[str, StringConstraints(pattern="uniform|pipe")]] = None
    tunnel_type: Optional[Annotated[str, StringConstraints(pattern="IPINIP")]] = None
    decap_dscp_to_tc_map: Optional[str] = None
    decap_tc_to_pg_map: Optional[str] = None
    encap_tc_to_dscp_map: Optional[str] = None
    encap_tc_to_queue_map: Optional[str] = None


class TunnelTable(RootModel[Dict[str, TunnelListRow]]):
    pass


# sonic-versions.yang :: sonic-versions :: VERSIONS
class VersionsDatabaseRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    VERSION: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=255,
                pattern="version_(([1-9]|[1-9]{1}[0-9]{1})_([0-9]{1,2})_([0-9]{1,2})|([1-9]{1}[0-9]{5})_([0-9]{2}))",
            ),
        ]
    ] = None


class VersionsTable(RootModel[Dict[str, VersionsDatabaseRow]]):
    pass


# sonic-vlan-sub-interface.yang :: sonic-vlan-sub-interface :: VLAN_SUB_INTERFACE
class VlanSubInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(\\w+)\\.([1-9][0-9]{0,2}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
            ),
        ]
    ] = None
    admin_status: Optional[Literal["up", "down"]] = None
    vrf_name: Optional[str] = None
    vnet_name: Optional[str] = None
    loopback_action: Optional[
        Annotated[str, StringConstraints(pattern="drop|forward")]
    ] = None
    vlan: Optional[Annotated[int, Field(ge=1, le=4094)]] = None


class VlanSubInterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")


class VlanSubInterfaceTable(
    RootModel[
        Dict[str, Union[VlanSubInterfaceListRow, VlanSubInterfaceIpprefixListRow]]
    ]
):
    pass


# sonic-vlan.yang :: sonic-vlan :: VLAN_INTERFACE
class VlanInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    vrf_name: Optional[str] = None
    vnet_name: Optional[str] = None
    nat_zone: Optional[Annotated[int, Field(ge=0, le=3)]] = 0
    mpls: Optional[Literal["enable", "disable"]] = None
    grat_arp: Optional[
        Annotated[str, StringConstraints(pattern="enabled|disabled")]
    ] = None
    proxy_arp: Optional[
        Annotated[str, StringConstraints(pattern="enabled|disabled")]
    ] = None
    ipv6_use_link_local_only: Optional[Literal["enable", "disable"]] = "disable"
    mac_addr: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    loopback_action: Optional[
        Annotated[str, StringConstraints(pattern="drop|forward")]
    ] = None


class VlanInterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")
    scope: Optional[Literal["global", "local"]] = None
    family: Optional[Literal["IPv4", "IPv6"]] = None
    secondary: Optional[bool] = None


class VlanInterfaceTable(
    RootModel[Dict[str, Union[VlanInterfaceListRow, VlanInterfaceIpprefixListRow]]]
):
    pass


# sonic-vlan.yang :: sonic-vlan :: VLAN
class VlanListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="Vlan(409[0-5]|40[0-8][0-9]|[1-3][0-9]{3}|[1-9][0-9]{2}|[1-9][0-9]|[2-9])"
            ),
        ]
    ] = None
    vlanid: Optional[Annotated[int, Field(ge=2, le=4094)]] = None
    alias: Optional[str] = None
    description: Optional[
        Annotated[str, StringConstraints(min_length=1, max_length=255)]
    ] = None
    dhcp_servers: Optional[
        List[
            Union[
                Annotated[
                    str,
                    StringConstraints(
                        pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                    ),
                ],
                str,
            ]
        ]
    ] = None
    dhcpv6_servers: Optional[List[str]] = None
    mtu: Optional[Annotated[int, Field(ge=1, le=9216)]] = None
    admin_status: Optional[Literal["up", "down"]] = None
    mac: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None


class VlanTable(RootModel[Dict[str, VlanListRow]]):
    pass


# sonic-vlan.yang :: sonic-vlan :: VLAN_MEMBER
class VlanMemberListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    port: Optional[str] = None
    tagging_mode: Literal["tagged", "untagged", "priority_tagged"]


class VlanMemberTable(RootModel[Dict[str, VlanMemberListRow]]):
    pass


# sonic-vnet.yang :: sonic-vnet :: VNET
class VnetListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    vxlan_tunnel: str
    vni: Annotated[int, Field(ge=1, le=16777215)]
    peer_list: Optional[str] = None
    guid: Optional[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = (
        None
    )
    scope: Optional[Annotated[str, StringConstraints(pattern="default")]] = None
    advertise_prefix: Optional[bool] = None
    overlay_dmac: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    src_mac: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None


class VnetTable(RootModel[Dict[str, VnetListRow]]):
    pass


# sonic-vnet.yang :: sonic-vnet :: VNET_ROUTE_TUNNEL
class VnetRouteTunnelListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    vnet_name: Optional[str] = None
    prefix: Optional[
        Annotated[
            str,
            StringConstraints(
                pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
            ),
        ]
    ] = None
    endpoint: Annotated[
        str,
        StringConstraints(
            pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
        ),
    ]
    mac_address: Optional[
        Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")]
    ] = None
    vni: Optional[Annotated[int, Field(ge=1, le=16777215)]] = None


class VnetRouteTunnelTable(RootModel[Dict[str, VnetRouteTunnelListRow]]):
    pass


# sonic-voq-inband-interface.yang :: sonic-voq-inband-interface :: VOQ_INBAND_INTERFACE
class VoqInbandInterfaceListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(pattern="Ethernet-IB[0-9]+")]] = (
        None
    )
    inband_type: Optional[Annotated[str, StringConstraints(pattern="port|Port")]] = (
        "port"
    )


class VoqInbandInterfaceIpprefixListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    ip_prefix: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])/(([0-9])|([1-2][0-9])|(3[0-2]))"
                ),
            ],
            str,
        ]
    ] = Field(default=None, alias="ip-prefix")


class VoqInbandInterfaceTable(
    RootModel[
        Dict[str, Union[VoqInbandInterfaceListRow, VoqInbandInterfaceIpprefixListRow]]
    ]
):
    pass


# sonic-vrf.yang :: sonic-vrf :: VRF
class VrfListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=15)]] = (
        None
    )
    fallback: Optional[bool] = False
    vni: Optional[Annotated[int, Field(ge=0, le=16777215)]] = 0


class VrfTable(RootModel[Dict[str, VrfListRow]]):
    pass


# sonic-vxlan.yang :: sonic-vxlan :: VXLAN_TUNNEL
class VxlanTunnelListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    src_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None
    dst_ip: Optional[
        Union[
            Annotated[
                str,
                StringConstraints(
                    pattern="(([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\\.){3}([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(%[\\p{N}\\p{L}]+)?"
                ),
            ],
            str,
        ]
    ] = None


class VxlanTunnelTable(RootModel[Dict[str, VxlanTunnelListRow]]):
    pass


# sonic-vxlan.yang :: sonic-vxlan :: VXLAN_TUNNEL_MAP
class VxlanTunnelMapListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    mapname: Optional[str] = None
    vlan: Annotated[
        str,
        StringConstraints(
            pattern="Vlan([0-9]{1,3}|[1-3][0-9]{3}|[4][0][0-8][0-9]|[4][0][9][0-4])"
        ),
    ]
    vni: Annotated[int, Field(ge=1, le=16777215)]


class VxlanTunnelMapTable(RootModel[Dict[str, VxlanTunnelMapListRow]]):
    pass


# sonic-vxlan.yang :: sonic-vxlan :: VXLAN_EVPN_NVO
class VxlanEvpnNvoListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[str] = None
    source_vtep: str


class VxlanEvpnNvoTable(RootModel[Dict[str, VxlanEvpnNvoListRow]]):
    pass


# sonic-warm-restart.yang :: sonic-warm-restart :: WARM_RESTART
class WarmRestartListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    module: Optional[Literal["bgp", "teamd", "swss", "system"]] = None
    bgp_eoiu: Optional[bool] = None
    bgp_timer: Optional[Annotated[int, Field(ge=1, le=3600)]] = None
    teamsyncd_timer: Optional[Annotated[int, Field(ge=1, le=3600)]] = None
    neighsyncd_timer: Optional[Annotated[int, Field(ge=1, le=9999)]] = None


class WarmRestartTable(RootModel[Dict[str, WarmRestartListRow]]):
    pass


# sonic-wred-profile.yang :: sonic-wred-profile :: WRED_PROFILE
class WredProfileListRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=32,
                pattern="[a-zA-Z0-9]{1}([-a-zA-Z0-9_]{0,31})",
            ),
        ]
    ] = None
    yellow_min_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    green_min_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    red_min_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    yellow_max_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    green_max_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    red_max_threshold: Optional[
        Annotated[int, Field(ge=0, le=18446744073709551615)]
    ] = None
    ecn: Optional[
        Literal[
            "ecn_none",
            "ecn_green",
            "ecn_yellow",
            "ecn_red",
            "ecn_green_yellow",
            "ecn_green_red",
            "ecn_yellow_red",
            "ecn_all",
        ]
    ] = "ecn_none"
    wred_green_enable: Optional[bool] = False
    wred_yellow_enable: Optional[bool] = False
    wred_red_enable: Optional[bool] = False
    yellow_drop_probability: Optional[Annotated[int, Field(ge=0, le=100)]] = 100
    green_drop_probability: Optional[Annotated[int, Field(ge=0, le=100)]] = 100
    red_drop_probability: Optional[Annotated[int, Field(ge=0, le=100)]] = 100


class WredProfileTable(RootModel[Dict[str, WredProfileListRow]]):
    pass


# sonic-xcvrd-log.yang :: sonic-xcvrd-log :: XCVRD_LOG
class XcvrdLogYCableRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    log_verbosity: Optional[
        Literal["info", "notice", "debug", "warning", "critical"]
    ] = None


class XcvrdLogTable(RootModel[Dict[str, XcvrdLogYCableRow]]):
    pass


# sonic-ztp.yang :: sonic-ztp :: ZTP
class ZtpModeRow(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    profile: Optional[Literal["active"]] = None
    inband: Optional[bool] = True
    out_of_band: Optional[bool] = Field(default=True, alias="out-of-band")
    ipv4: Optional[bool] = True
    ipv6: Optional[bool] = True
    product_name: Optional[str] = Field(default=None, alias="product-name")
    serial_no: Optional[str] = Field(default=None, alias="serial-no")


class ZtpTable(RootModel[Dict[str, ZtpModeRow]]):
    pass


TABLE_MODELS: Dict[str, type[BaseModel]] = {
    "AAA": AaaTable,
    "ASIC_SENSORS": AsicSensorsTable,
    "AS_PATH_SET": AsPathSetTable,
    "AUTO_TECHSUPPORT": AutoTechsupportTable,
    "AUTO_TECHSUPPORT_FEATURE": AutoTechsupportFeatureTable,
    "BANNER_MESSAGE": BannerMessageTable,
    "BGP_AGGREGATE_ADDRESS": BgpAggregateAddressTable,
    "BGP_ALLOWED_PREFIXES": BgpAllowedPrefixesTable,
    "BGP_BBR": BgpBbrTable,
    "BGP_DEVICE_GLOBAL": BgpDeviceGlobalTable,
    "BGP_GLOBALS": BgpGlobalsTable,
    "BGP_GLOBALS_AF": BgpGlobalsAfTable,
    "BGP_GLOBALS_AF_AGGREGATE_ADDR": BgpGlobalsAfAggregateAddrTable,
    "BGP_GLOBALS_AF_NETWORK": BgpGlobalsAfNetworkTable,
    "BGP_GLOBALS_LISTEN_PREFIX": BgpGlobalsListenPrefixTable,
    "BGP_INTERNAL_NEIGHBOR": BgpInternalNeighborTable,
    "BGP_MONITORS": BgpMonitorsTable,
    "BGP_NEIGHBOR": BgpNeighborTable,
    "BGP_NEIGHBOR_AF": BgpNeighborAfTable,
    "BGP_PEER_GROUP": BgpPeerGroupTable,
    "BGP_PEER_GROUP_AF": BgpPeerGroupAfTable,
    "BGP_PEER_RANGE": BgpPeerRangeTable,
    "BGP_SENTINELS": BgpSentinelsTable,
    "BGP_VOQ_CHASSIS_NEIGHBOR": BgpVoqChassisNeighborTable,
    "BMP": BmpTable,
    "BREAKOUT_CFG": BreakoutCfgTable,
    "BUFFER_PG": BufferPgTable,
    "BUFFER_POOL": BufferPoolTable,
    "BUFFER_PORT_EGRESS_PROFILE_LIST": BufferPortEgressProfileListTable,
    "BUFFER_PORT_INGRESS_PROFILE_LIST": BufferPortIngressProfileListTable,
    "BUFFER_PROFILE": BufferProfileTable,
    "BUFFER_QUEUE": BufferQueueTable,
    "CABLE_LENGTH": CableLengthTable,
    "CHASSIS_MODULE": ChassisModuleTable,
    "COMMUNITY_SET": CommunitySetTable,
    "CONSOLE_PORT": ConsolePortTable,
    "CONSOLE_SWITCH": ConsoleSwitchTable,
    "COPP_GROUP": CoppGroupTable,
    "COPP_TRAP": CoppTrapTable,
    "CRM": CrmTable,
    "DASH_ACL_GROUP": DashAclGroupTable,
    "DASH_ACL_IN": DashAclInTable,
    "DASH_ACL_OUT": DashAclOutTable,
    "DASH_ACL_RULE": DashAclRuleTable,
    "DASH_APPLIANCE": DashApplianceTable,
    "DASH_ENI": DashEniTable,
    "DASH_HA_GLOBAL_CONFIG": DashHaGlobalConfigTable,
    "DASH_QOS": DashQosTable,
    "DASH_ROUTE_TABLE": DashRouteTableTable,
    "DASH_ROUTING_TYPE": DashRoutingTypeTable,
    "DASH_VNET": DashVnetTable,
    "DASH_VNET_MAPPING_TABLE": DashVnetMappingTableTable,
    "DEBUG_COUNTER": DebugCounterTable,
    "DEBUG_COUNTER_DROP_REASON": DebugCounterDropReasonTable,
    "DEBUG_DROP_MONITOR": DebugDropMonitorTable,
    "DEFAULT_LOSSLESS_BUFFER_PARAMETER": DefaultLosslessBufferParameterTable,
    "DEVICE_METADATA": DeviceMetadataTable,
    "DEVICE_NEIGHBOR": DeviceNeighborTable,
    "DEVICE_NEIGHBOR_METADATA": DeviceNeighborMetadataTable,
    "DHCPV4_RELAY": Dhcpv4RelayTable,
    "DHCP_RELAY": DhcpRelayTable,
    "DHCP_SERVER": DhcpServerTable,
    "DHCP_SERVER_IPV4": DhcpServerIpv4Table,
    "DHCP_SERVER_IPV4_CUSTOMIZED_OPTIONS": DhcpServerIpv4CustomizedOptionsTable,
    "DHCP_SERVER_IPV4_PORT": DhcpServerIpv4PortTable,
    "DHCP_SERVER_IPV4_RANGE": DhcpServerIpv4RangeTable,
    "DNS_NAMESERVER": DnsNameserverTable,
    "DOT1P_TO_TC_MAP": Dot1pToTcMapTable,
    "DPU": DpuTable,
    "DPUS": DpusTable,
    "DSCP_TO_FC_MAP": DscpToFcMapTable,
    "DSCP_TO_TC_MAP": DscpToTcMapTable,
    "EXP_TO_FC_MAP": ExpToFcMapTable,
    "EXTENDED_COMMUNITY_SET": ExtendedCommunitySetTable,
    "FABRIC_MONITOR": FabricMonitorTable,
    "FABRIC_PORT": FabricPortTable,
    "FEATURE": FeatureTable,
    "FG_NHG": FgNhgTable,
    "FG_NHG_MEMBER": FgNhgMemberTable,
    "FG_NHG_PREFIX": FgNhgPrefixTable,
    "FIPS": FipsTable,
    "FLEX_COUNTER_TABLE": FlexCounterTableTable,
    "FLOW_COUNTER_ROUTE_PATTERN": FlowCounterRoutePatternTable,
    "GNMI": GnmiTable,
    "GNMI_CLIENT_CERT": GnmiClientCertTable,
    "GRPCCLIENT": GrpcclientTable,
    "HEARTBEAT": HeartbeatTable,
    "HIGH_FREQUENCY_TELEMETRY_GROUP": HighFrequencyTelemetryGroupTable,
    "HIGH_FREQUENCY_TELEMETRY_PROFILE": HighFrequencyTelemetryProfileTable,
    "INTERFACE": InterfaceTable,
    "KDUMP": KdumpTable,
    "KUBERNETES_MASTER": KubernetesMasterTable,
    "LDAP": LdapTable,
    "LDAP_SERVER": LdapServerTable,
    "LLDP": LldpTable,
    "LLDP_PORT": LldpPortTable,
    "LOGGER": LoggerTable,
    "LOOPBACK_INTERFACE": LoopbackInterfaceTable,
    "LOSSLESS_TRAFFIC_PATTERN": LosslessTrafficPatternTable,
    "MACSEC_PROFILE": MacsecProfileTable,
    "MAP_PFC_PRIORITY_TO_QUEUE": MapPfcPriorityToQueueTable,
    "MCLAG_DOMAIN": MclagDomainTable,
    "MCLAG_INTERFACE": MclagInterfaceTable,
    "MCLAG_UNIQUE_IP": MclagUniqueIpTable,
    "MEMORY_STATISTICS": MemoryStatisticsTable,
    "MGMT_INTERFACE": MgmtInterfaceTable,
    "MGMT_PORT": MgmtPortTable,
    "MGMT_VRF_CONFIG": MgmtVrfConfigTable,
    "MID_PLANE_BRIDGE": MidPlaneBridgeTable,
    "MIRROR_SESSION": MirrorSessionTable,
    "MPLS_TC_TO_TC_MAP": MplsTcToTcMapTable,
    "MUX_CABLE": MuxCableTable,
    "MUX_LINKMGR": MuxLinkmgrTable,
    "NAT_BINDINGS": NatBindingsTable,
    "NAT_GLOBAL": NatGlobalTable,
    "NAT_POOL": NatPoolTable,
    "NEIGH": NeighTable,
    "NTP": NtpTable,
    "NTP_KEY": NtpKeyTable,
    "NTP_SERVER": NtpServerTable,
    "NVGRE_TUNNEL": NvgreTunnelTable,
    "NVGRE_TUNNEL_MAP": NvgreTunnelMapTable,
    "PASSW_HARDENING": PasswHardeningTable,
    "PBH_HASH": PbhHashTable,
    "PBH_HASH_FIELD": PbhHashFieldTable,
    "PBH_RULE": PbhRuleTable,
    "PBH_TABLE": PbhTableTable,
    "PEER_SWITCH": PeerSwitchTable,
    "PFC_PRIORITY_TO_PRIORITY_GROUP_MAP": PfcPriorityToPriorityGroupMapTable,
    "PFC_WD": PfcWdTable,
    "POLICER": PolicerTable,
    "PORT": PortTable,
    "PORTCHANNEL": PortchannelTable,
    "PORTCHANNEL_INTERFACE": PortchannelInterfaceTable,
    "PORTCHANNEL_MEMBER": PortchannelMemberTable,
    "PORT_QOS_MAP": PortQosMapTable,
    "PORT_STORM_CONTROL": PortStormControlTable,
    "PREFIX": PrefixTable,
    "PREFIX_LIST": PrefixListTable,
    "PREFIX_SET": PrefixSetTable,
    "QUEUE": QueueTable,
    "RADIUS": RadiusTable,
    "RADIUS_SERVER": RadiusServerTable,
    "REMOTE_DPU": RemoteDpuTable,
    "RESTAPI": RestapiTable,
    "ROUTE_MAP": RouteMapTable,
    "ROUTE_MAP_SET": RouteMapSetTable,
    "ROUTE_REDISTRIBUTE": RouteRedistributeTable,
    "SCHEDULER": SchedulerTable,
    "SERIAL_CONSOLE": SerialConsoleTable,
    "SFLOW": SflowTable,
    "SFLOW_COLLECTOR": SflowCollectorTable,
    "SFLOW_SESSION": SflowSessionTable,
    "SNMP": SnmpTable,
    "SNMP_AGENT_ADDRESS_CONFIG": SnmpAgentAddressConfigTable,
    "SNMP_COMMUNITY": SnmpCommunityTable,
    "SNMP_USER": SnmpUserTable,
    "SRV6_MY_LOCATORS": Srv6MyLocatorsTable,
    "SRV6_MY_SIDS": Srv6MySidsTable,
    "SSH_SERVER": SshServerTable,
    "STATIC_NAPT": StaticNaptTable,
    "STATIC_NAT": StaticNatTable,
    "STATIC_ROUTE": StaticRouteTable,
    "STORMOND_CONFIG": StormondConfigTable,
    "STP": StpTable,
    "STP_MST": StpMstTable,
    "STP_MST_INST": StpMstInstTable,
    "STP_MST_PORT": StpMstPortTable,
    "STP_PORT": StpPortTable,
    "STP_VLAN": StpVlanTable,
    "STP_VLAN_PORT": StpVlanPortTable,
    "SUBNET_DECAP": SubnetDecapTable,
    "SUPPRESS_ASIC_SDK_HEALTH_EVENT": SuppressAsicSdkHealthEventTable,
    "SWITCH_HASH": SwitchHashTable,
    "SWITCH_TRIMMING": SwitchTrimmingTable,
    "SYSLOG_CONFIG": SyslogConfigTable,
    "SYSLOG_CONFIG_FEATURE": SyslogConfigFeatureTable,
    "SYSLOG_SERVER": SyslogServerTable,
    "SYSTEM_DEFAULTS": SystemDefaultsTable,
    "SYSTEM_PORT": SystemPortTable,
    "TACPLUS": TacplusTable,
    "TACPLUS_SERVER": TacplusServerTable,
    "TC_TO_DSCP_MAP": TcToDscpMapTable,
    "TC_TO_PRIORITY_GROUP_MAP": TcToPriorityGroupMapTable,
    "TC_TO_QUEUE_MAP": TcToQueueMapTable,
    "TELEMETRY": TelemetryTable,
    "TELEMETRY_CLIENT": TelemetryClientTable,
    "TUNNEL": TunnelTable,
    "VDPU": VdpuTable,
    "VERSIONS": VersionsTable,
    "VLAN": VlanTable,
    "VLAN_INTERFACE": VlanInterfaceTable,
    "VLAN_MEMBER": VlanMemberTable,
    "VLAN_SUB_INTERFACE": VlanSubInterfaceTable,
    "VNET": VnetTable,
    "VNET_ROUTE_TUNNEL": VnetRouteTunnelTable,
    "VOQ_INBAND_INTERFACE": VoqInbandInterfaceTable,
    "VRF": VrfTable,
    "VXLAN_EVPN_NVO": VxlanEvpnNvoTable,
    "VXLAN_TUNNEL": VxlanTunnelTable,
    "VXLAN_TUNNEL_MAP": VxlanTunnelMapTable,
    "WARM_RESTART": WarmRestartTable,
    "WRED_PROFILE": WredProfileTable,
    "XCVRD_LOG": XcvrdLogTable,
    "ZTP": ZtpTable,
}
