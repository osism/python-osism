# SPDX-License-Identifier: Apache-2.0

"""Tests that document and verify the SONiC config generator's ownership model.

generate_sonic_config() starts from a deep copy of /etc/sonic/config_db.json.
The section helpers use unconditional assignment for the entries they own, so
pre-existing values in those entries are not preserved on regen.

The tests in this file directly invoke the private helpers to show what the
ownership rule means in practice.  See the generate_sonic_config() docstring
for the full ownership statement.

The orchestrator follows the same rule for the entries it writes directly; see
test_generate_sonic_config_bgp_globals_default_extra_fields_dropped_on_regen in
test_config_generator_orchestrator.py for BGP_GLOBALS['default'].
"""

from types import SimpleNamespace

from osism.tasks.conductor.sonic.config_generator import (
    INHERITED_TABLE_KEYS,
    ON_DEMAND_OWNED_TABLE_KEYS,
    OWNED_TABLE_KEYS,
    SCAFFOLDED_OWNED_TABLE_KEYS,
    TOP_LEVEL_SCAFFOLD_KEYS,
    _add_vlan_configuration,
    _add_vrf_configuration,
)


def _empty_config():
    """Minimal config dict covering the sections these helpers can write."""
    return {
        "VRF": {},
        "VLAN": {},
        "VLAN_INTERFACE": {},
        "VLAN_MEMBER": {},
        "BGP_GLOBALS": {},
        "BGP_GLOBALS_AF": {},
        "BGP_GLOBALS_ROUTE_ADVERTISE": {},
        "ROUTE_REDISTRIBUTE": {},
        "VXLAN_TUNNEL": {},
        "VXLAN_EVPN_NVO": {},
        "VXLAN_TUNNEL_MAP": {},
        "MGMT_INTERFACE": {"eth0|10.0.0.1/24": {"gwaddr": "10.0.0.254"}},
    }


def _device(name="leaf-1"):
    return SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# _add_vrf_configuration
# ---------------------------------------------------------------------------


class TestVrfConfigurationOwnership:
    """_add_vrf_configuration owns VRF-derived config entries outright."""

    def test_bgp_globals_for_vrf_replaces_preexisting_entry(self):
        """Pre-existing BGP_GLOBALS[vrf_name] is replaced wholesale on regen.

        Any operator-added fields not produced by the generator (e.g. custom
        timer overrides) are silently dropped.
        """
        config = _empty_config()
        config["BGP_GLOBALS"]["default"] = {
            "router_id": "10.0.0.1",
            "local_asn": "4200000001",
        }
        config["BGP_GLOBALS"]["tenant-vrf"] = {
            "router_id": "10.0.0.1",
            "local_asn": "4200000001",
            "custom_timer": "operator-value",
        }
        vrf_info = {
            "vrfs": {"tenant-vrf": {"table_id": 100}},
            "interface_vrf_mapping": {},
        }

        _add_vrf_configuration(config, vrf_info, {})

        # Entry must exactly match the deepcopy of BGP_GLOBALS["default"].
        # custom_timer must be absent — it is not derived from NetBox or policy.
        assert config["BGP_GLOBALS"]["tenant-vrf"] == {
            "router_id": "10.0.0.1",
            "local_asn": "4200000001",
        }
        assert "custom_timer" not in config["BGP_GLOBALS"]["tenant-vrf"]

    def test_vlan_for_vni_vrf_replaces_preexisting_entry(self):
        """Pre-existing VLAN[Vlan{vni}] is replaced wholesale on regen.

        Operator-added fields (e.g. a description) are silently dropped.
        """
        config = _empty_config()
        config["BGP_GLOBALS"]["default"] = {}
        vni = 2001
        vlan_name = f"Vlan{vni}"
        config["VLAN"][vlan_name] = {
            "admin_status": "up",
            "autostate": "enable",
            "vlanid": str(vni),
            "description": "do-not-modify",
        }
        vrf_info = {
            "vrfs": {"tenant-vrf": {"vni": vni}},
            "interface_vrf_mapping": {},
        }

        _add_vrf_configuration(config, vrf_info, {})

        assert config["VLAN"][vlan_name] == {
            "admin_status": "up",
            "autostate": "enable",
            "vlanid": str(vni),
        }
        assert "description" not in config["VLAN"][vlan_name]

    def test_route_redistribute_key_is_reset_to_empty_dict(self):
        """The generated ROUTE_REDISTRIBUTE key is always reset to {} on regen.

        Any operator-configured route policy under the generated key is
        silently dropped.
        """
        config = _empty_config()
        config["BGP_GLOBALS"]["default"] = {}
        key = "tenant-vrf|connected|bgp|ipv4"
        config["ROUTE_REDISTRIBUTE"][key] = {"route_map": "RM-CUSTOM"}
        vrf_info = {
            "vrfs": {"tenant-vrf": {"vni": 3001}},
            "interface_vrf_mapping": {},
        }

        _add_vrf_configuration(config, vrf_info, {})

        assert config["ROUTE_REDISTRIBUTE"][key] == {}

    def test_sections_not_owned_by_vrf_helper_pass_through_unchanged(self):
        """Sections not written by _add_vrf_configuration are not disturbed."""
        config = _empty_config()
        config["BGP_GLOBALS"]["default"] = {}
        vrf_info = {
            "vrfs": {"tenant-vrf": {}},
            "interface_vrf_mapping": {},
        }

        _add_vrf_configuration(config, vrf_info, {})

        assert config["MGMT_INTERFACE"] == {
            "eth0|10.0.0.1/24": {"gwaddr": "10.0.0.254"}
        }


# ---------------------------------------------------------------------------
# _add_vlan_configuration
# ---------------------------------------------------------------------------


class TestVlanConfigurationOwnership:
    """_add_vlan_configuration owns VLAN entries outright."""

    def test_vlan_entry_replaces_preexisting_entry(self):
        """Pre-existing VLAN[VlanX] is replaced wholesale on regen.

        Operator-added fields not produced by the generator are silently
        dropped.
        """
        config = _empty_config()
        vid = 100
        vlan_name = f"Vlan{vid}"
        config["VLAN"][vlan_name] = {
            "admin_status": "up",
            "autostate": "enable",
            "members": [],
            "vlanid": str(vid),
            "description": "operator-managed",
        }
        vlan_info = {
            "vlans": {vid: {}},
            "vlan_members": {},
            "vlan_interfaces": {},
        }

        _add_vlan_configuration(config, vlan_info, {}, _device())

        assert config["VLAN"][vlan_name] == {
            "admin_status": "up",
            "autostate": "enable",
            "members": [],
            "vlanid": str(vid),
        }
        assert "description" not in config["VLAN"][vlan_name]


# ---------------------------------------------------------------------------
# Ownership-taxonomy invariants
# ---------------------------------------------------------------------------


class TestOwnershipTaxonomyInvariants:
    """Guard the relationships between the table-classification constants.

    OWNED_TABLE_KEYS is derived from these sets, so most of the taxonomy is
    correct by construction. These tests pin the parts that are *not* derived
    -- the hand-written INHERITED_TABLE_KEYS and ON_DEMAND_OWNED_TABLE_KEYS
    literals -- so an accidental edit to either fails here rather than silently
    breaking the ownership model at runtime.
    """

    def test_scaffold_partitions_into_owned_and_inherited(self):
        """The scaffold set is exactly its owned and inherited tables.

        Every scaffolded table is either rebuilt (scaffolded-owned) or
        preserved (inherited), with nothing left unclassified and no inherited
        table outside the scaffold set. The latter matters at runtime: the
        orchestrator setdefault-creates only TOP_LEVEL_SCAFFOLD_KEYS and then
        indexes into the inherited tables directly (e.g.
        config["DEVICE_METADATA"]), so an inherited table missing from the
        scaffold set would KeyError on a fresh base config.
        """
        assert set(TOP_LEVEL_SCAFFOLD_KEYS) == (
            set(SCAFFOLDED_OWNED_TABLE_KEYS) | set(INHERITED_TABLE_KEYS)
        )

    def test_owned_and_inherited_are_disjoint(self):
        """No table is both owned and inherited.

        Owned tables are dropped up front and rebuilt; inherited tables keep
        their base content. A table in both sets would be dropped *and*
        expected to survive -- the drop wins, silently breaking inheritance.
        """
        assert set(OWNED_TABLE_KEYS).isdisjoint(INHERITED_TABLE_KEYS)

    def test_owned_table_keys_has_no_duplicates(self):
        """OWNED_TABLE_KEYS lists each table once.

        A duplicate means an on-demand literal shadows a scaffolded key (or
        vice versa), signalling the two classification sets have drifted into
        overlap.
        """
        assert len(OWNED_TABLE_KEYS) == len(set(OWNED_TABLE_KEYS))

    def test_scaffolded_and_on_demand_owned_are_disjoint(self):
        """The two owned sub-categories do not overlap.

        Scaffolded-owned tables are created up front; on-demand owned tables
        are created only when NetBox carries their data. A table in both would
        be miscategorised about how it comes into existence.
        """
        assert set(SCAFFOLDED_OWNED_TABLE_KEYS).isdisjoint(
            ON_DEMAND_OWNED_TABLE_KEYS
        )
