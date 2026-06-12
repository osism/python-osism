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

import ast
from pathlib import Path
from types import SimpleNamespace

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import (
    IMAGE_CONSUMED_TABLE_KEYS,
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
        assert set(SCAFFOLDED_OWNED_TABLE_KEYS).isdisjoint(ON_DEMAND_OWNED_TABLE_KEYS)

    def test_image_consumed_and_owned_are_disjoint(self):
        """No table is both image-consumed and owned.

        Image-consumed tables are read defensively from the image base config
        (via config.get) and never dropped. Owned tables are dropped up front
        and rebuilt. A table in both would be dropped before it is read, so the
        consuming helper would always see an empty table -- the dependency the
        image-consumed category exists to document would silently break.
        """
        assert set(IMAGE_CONSUMED_TABLE_KEYS).isdisjoint(OWNED_TABLE_KEYS)

    def test_image_consumed_and_inherited_are_disjoint(self):
        """No table is both image-consumed and inherited.

        Image-consumed tables are read but never modified; inherited tables
        are read and have selected fields updated in place. The two are
        mutually exclusive by definition (modified vs. not), so a table in
        both is a contradictory classification. With the owned/inherited and
        owned/image-consumed invariants above, this completes pairwise
        disjointness across all three classified categories.
        """
        assert set(IMAGE_CONSUMED_TABLE_KEYS).isdisjoint(INHERITED_TABLE_KEYS)


# ---------------------------------------------------------------------------
# Static guard: every referenced table is classified
# ---------------------------------------------------------------------------


_CONFIG_METHODS = ("get", "setdefault", "pop", "update")

# Calls allowed on the RHS of `config = ...` as a whole-config base load: they
# take the prior config or a file as input and introduce no literal table keys
# of their own. Any other call (merge(config, {...}), dict(config, X={})) could
# carry a literal key the collector never reads, so the backstop rejects it.
_BASE_LOAD_CALLS = frozenset({"copy.deepcopy", "copy.copy", "json.load", "json.loads"})


def _is_config(node):
    return isinstance(node, ast.Name) and node.id == "config"


def _literal_dict_keys(node):
    """String-literal keys of a dict-display node ({...}); [] for anything else.

    A ``**spread`` entry has a None key and is skipped, so {**config, "X": ...}
    yields just ["X"].
    """
    if not isinstance(node, ast.Dict):
        return []
    return [
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    ]


def _config_table_keys_referenced_in_source():
    """Collect every top-level config_db table the generator references.

    Parses config_generator.py and records the string-literal table name of
    every reference made through a local variable named ``config``:
      - subscripts (``config["X"]``),
      - the defensive accessors (``config.get/setdefault/pop("X", ...)``) -- a
        read is a real dependency on a table, so reads are collected the same
        as writes; that is how an image-consumed table such as TELEMETRY is
        caught,
      - update() in every literal form: ``config.update({"X": ...})``,
        ``config.update(X=...)`` (keyword), ``config.update(**{"X": ...})``,
      - dict-merge assignments with a literal operand: ``config |= {"X": ...}``,
        ``config = config | {"X": ...}``, ``config = {**config, "X": ...}``.

    Keys that are not string literals are skipped, because the table name is
    not knowable statically: dynamic subscripts (``config[some_var]``) and
    merges from a non-literal mapping (``config.update(some_dict)``). Any other
    way of mutating config would also hide keys, so it does not slip past
    silently -- test_config_mutations_are_statically_analyzable rejects it.
    Returns a set of table names.
    """
    tree = ast.parse(Path(config_generator.__file__).read_text())
    referenced = set()

    for node in ast.walk(tree):
        # config["X"]
        if isinstance(node, ast.Subscript):
            key = node.slice
            if (
                _is_config(node.value)
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            ):
                referenced.add(key.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and _is_config(func.value):
                # config.get/setdefault/pop("X", ...)
                if (
                    func.attr in ("get", "setdefault", "pop")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    referenced.add(node.args[0].value)
                # config.update({"X": ...}) / .update(X=...) / .update(**{"X": ...})
                elif func.attr == "update":
                    if node.args:
                        referenced.update(_literal_dict_keys(node.args[0]))
                    for keyword in node.keywords:
                        if keyword.arg is not None:
                            referenced.add(keyword.arg)
                        else:
                            referenced.update(_literal_dict_keys(keyword.value))
        # config |= {"X": ...}
        elif isinstance(node, ast.AugAssign):
            if _is_config(node.target) and isinstance(node.op, ast.BitOr):
                referenced.update(_literal_dict_keys(node.value))
        # config = {**config, "X": ...}  /  config = config | {"X": ...}
        elif isinstance(node, ast.Assign):
            if any(_is_config(target) for target in node.targets):
                value = node.value
                if isinstance(value, ast.Dict):
                    referenced.update(_literal_dict_keys(value))
                elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
                    referenced.update(_literal_dict_keys(value.left))
                    referenced.update(_literal_dict_keys(value.right))

    return referenced


def _unanalyzable_config_mutations():
    """Find config mutations whose literal keys the collector cannot read.

    The collector above understands a fixed set of mutation forms. Any other
    way of writing to the top-level ``config`` dict could introduce a table the
    guard never sees, so this backstop locates them and the guard rejects them.
    Returns a list of (lineno, source) pairs.

    Flagged: a method call ``config.<m>(...)`` whose method is outside the
    recognized set, and a reassignment ``config = <expr>`` whose right-hand
    side is not a dict display, a dict-merge (``a | b``), or one of the
    whitelisted base-load calls (copy.deepcopy / copy.copy / json.load /
    json.loads). A merge via an arbitrary call -- ``config = merge(config,
    {...})``, ``config = dict(config, X={})`` -- is therefore flagged, not
    silently allowed.

    Not flagged -- the one accepted blind spot, a dynamic key in an otherwise
    recognized form (``config[var]``, ``config.setdefault(var, {})``,
    ``config.pop(var, None)``, ``config.update(name)``). The table name is not
    a literal at the call site; the generator relies on this legitimately for
    the up-front scaffold and drop loops, and resolving it would need data-flow
    analysis.
    """
    tree = ast.parse(Path(config_generator.__file__).read_text())
    offenders = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_config(node.func.value)
            and node.func.attr not in _CONFIG_METHODS
        ):
            offenders.append((node.lineno, ast.unparse(node)))
        elif isinstance(node, ast.Assign) and any(
            _is_config(target) for target in node.targets
        ):
            value = node.value
            allowed = (
                isinstance(value, ast.Dict)
                or (isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr))
                or (
                    isinstance(value, ast.Call)
                    and ast.unparse(value.func) in _BASE_LOAD_CALLS
                )
            )
            if not allowed:
                offenders.append((node.lineno, ast.unparse(node)))

    return offenders


class TestStaticTableReferenceGuard:
    """Every config_db table the generator touches must be classified.

    The taxonomy constants above are a hand-maintained allowlist; nothing
    forces a newly handled table into one of them. This guard parses the
    generator source and fails when it references a table that is neither
    owned, inherited, nor image-consumed -- the omission that lets a new table
    fall into the unpoliced pass-through tier and accumulate stale config. It
    is static rather than runtime so it catches tables that emit only when
    NetBox carries their data (a generate-and-inspect test would miss them
    unless the fixture happened to trigger every table).
    """

    def test_every_referenced_table_is_classified(self):
        classified = (
            set(OWNED_TABLE_KEYS)
            | set(INHERITED_TABLE_KEYS)
            | set(IMAGE_CONSUMED_TABLE_KEYS)
        )
        referenced = _config_table_keys_referenced_in_source()
        unclassified = referenced - classified

        assert not unclassified, (
            "config_generator.py references these config_db tables, but the "
            "ownership model does not classify them: "
            + ", ".join(sorted(unclassified))
            + ".\n\n"
            "Every table the generator touches must be placed in exactly one "
            "category (see the generate_sonic_config docstring):\n"
            "  - owned, rebuilt from NetBox/policy every regen -> add to "
            "ON_DEMAND_OWNED_TABLE_KEYS (or TOP_LEVEL_SCAFFOLD_KEYS if it is "
            "created up front by the orchestrator)\n"
            "  - image base content preserved, with selected fields updated "
            "in place -> add to INHERITED_TABLE_KEYS\n"
            "  - read from the image but never modified -> add to "
            "IMAGE_CONSUMED_TABLE_KEYS\n"
            "Leaving a table unclassified lets pre-existing operator or image "
            "content survive a regen, the stale-config bug the ownership model "
            "exists to prevent."
        )

    def test_config_mutations_are_statically_analyzable(self):
        """No config mutation can hide a literal table from the collector.

        The classification guard only catches tables it can see. This backstop
        keeps that "every literal reference" guarantee honest: every write to
        the config dict must use a form whose keys the collector reads, so a
        new mutation idiom (e.g. config.replace(...), config = merge(...)) cannot
        smuggle an unclassified table past the guard. The fix is to use a
        supported form (subscript / get/setdefault/pop / update / |=) or to
        teach the collector the new one.
        """
        offenders = _unanalyzable_config_mutations()
        assert not offenders, (
            "config_generator.py mutates the config dict in forms the ownership "
            "guard cannot statically read for table keys:\n"
            + "\n".join(f"  line {lineno}: {source}" for lineno, source in offenders)
            + '\nUse a supported form (config["X"] = ..., config.get/setdefault/'
            "pop, config.update, config |= {...}) or extend "
            "_config_table_keys_referenced_in_source to understand the new one."
        )
