# SPDX-License-Identifier: Apache-2.0

"""Device selection for the live hardware reports.

The reports log in to Linux nodes and SONiC switches. Which devices they
log in to is decided here: NetBox is queried with the filters given on the
command line, every device found is classified as node or switch, and name
patterns narrow the result. Without NetBox the nodes of the Ansible
inventory are the only possible targets.

The result is a list of ``Target`` objects holding plain data, so that the
collection can run in worker threads without touching the NetBox session.
"""

from dataclasses import dataclass, field
import fnmatch
import json
import subprocess
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from loguru import logger

from osism import settings
from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path

KIND_NODE = "node"
KIND_SWITCH = "switch"

INVENTORY_PATH = "/ansible/inventory/hosts.yml"
DEFAULT_SWITCH_USER = "admin"
DEFAULT_STATUS = "active"

# Options that take slugs and map 1:1 to a NetBox device filter.
SLUG_FILTERS = [
    ("--site", "site", "site"),
    ("--role", "role", "device role"),
    ("--region", "region", "region"),
    ("--site-group", "site_group", "site group"),
    ("--tenant", "tenant", "tenant"),
    ("--tag", "tag", "tag"),
    ("--manufacturer", "manufacturer", "manufacturer"),
    ("--device-type", "device_type", "device type"),
    ("--platform", "platform", "platform"),
]

# Options that take names. NetBox only filters devices by rack_id and
# location_id, so the names are resolved to IDs first.
NAME_FILTERS = [
    ("--rack", "rack", "racks"),
    ("--location", "location", "locations"),
]


class SelectionError(Exception):
    """The selection could not be evaluated or matched no device."""


@dataclass
class Target:
    """One device a report logs in to.

    Attributes:
        name: NetBox device name, or the inventory hostname without NetBox
        hostname: Inventory hostname (custom field ``inventory_hostname``,
            else the device name)
        kind: ``node`` or ``switch``
        address: Address used for SSH, set by ``resolve_addresses``
        user: SSH user, set by ``resolve_addresses``
        device_id: NetBox device ID, ``None`` without NetBox
        device: NetBox device as plain data, empty without NetBox
    """

    name: str
    hostname: str
    kind: str
    address: str = ""
    user: str = ""
    device_id: Optional[int] = None
    device: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def hwsku(self) -> Optional[str]:
        custom_fields = self.device.get("custom_fields") or {}
        return (custom_fields.get("sonic_parameters") or {}).get("hwsku")

    def describe(self) -> Dict[str, Any]:
        """Return the device attributes shown in a report."""
        device = self.device
        device_type = device.get("device_type") or {}
        return {
            "name": self.name,
            "inventory_hostname": self.hostname,
            "kind": self.kind,
            "address": self.address,
            "site": _nested(device, "site", "slug"),
            "rack": _nested(device, "rack", "name"),
            "role": _role_slug(device),
            "device_type": device_type.get("model"),
            "manufacturer": _nested(device_type, "manufacturer", "name"),
            "serial": device.get("serial") or None,
        }


def add_selection_arguments(parser) -> None:
    """Add the device selection options shared by the hardware reports."""
    parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help="Shell-style pattern matched against the device name and the inventory hostname",
    )
    parser.add_argument(
        "--type",
        choices=["all", KIND_NODE, KIND_SWITCH],
        default="all",
        help="Restrict the selection to nodes or switches (default: all)",
    )
    parser.add_argument(
        "--include-unmanaged",
        action="store_true",
        help="Also query SONiC switches that do not match NETBOX_FILTER_CONDUCTOR_SONIC",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=str,
        help="Limit selected hosts to an additional pattern (Ansible pattern, selects nodes only)",
    )
    for flag, dest, label in SLUG_FILTERS:
        parser.add_argument(
            flag,
            dest=dest,
            action="append",
            metavar="SLUG",
            help=f"Select devices by {label} slug (can be used multiple times)",
        )
    for flag, dest, _ in NAME_FILTERS:
        parser.add_argument(
            flag,
            dest=dest,
            action="append",
            metavar="NAME",
            help=f"Select devices by {dest} name (can be used multiple times)",
        )
    parser.add_argument(
        "--status",
        action="append",
        metavar="STATUS",
        help=f"Select devices by status (default: {DEFAULT_STATUS}, can be used multiple times)",
    )
    parser.add_argument(
        "--filter",
        dest="netbox_filter",
        action="append",
        metavar="KEY=VALUE",
        help="Pass any other NetBox device filter through unchanged (can be used multiple times)",
    )


def uses_netbox_filters(parsed_args) -> bool:
    """Return True when an option was given that only NetBox can evaluate."""
    dests = [dest for _, dest, _ in SLUG_FILTERS + NAME_FILTERS]
    dests.extend(["status", "netbox_filter"])
    return any(getattr(parsed_args, dest, None) for dest in dests)


def build_netbox_query(parsed_args, nb) -> Dict[str, List[Any]]:
    """Translate the filter options into a NetBox device query.

    Values of one option are passed as a list, which NetBox combines the way
    it combines a repeated query parameter. Different options are ANDed.

    Raises:
        SelectionError: A rack or location name is unknown, or a ``--filter``
            value is not of the form ``KEY=VALUE``
    """
    query: Dict[str, List[Any]] = {}

    for _, dest, _ in SLUG_FILTERS:
        values = getattr(parsed_args, dest, None)
        if values:
            query[dest] = list(values)

    for _, dest, endpoint_name in NAME_FILTERS:
        names = getattr(parsed_args, dest, None)
        if not names:
            continue
        endpoint = getattr(nb.dcim, endpoint_name)
        ids: List[Any] = []
        for name in names:
            try:
                found = [record.id for record in endpoint.filter(name=name)]
            except Exception as exc:
                raise SelectionError(f"NetBox {dest} query failed: {exc}")
            if not found:
                raise SelectionError(f"No {dest} named {name} found in NetBox")
            ids.extend(found)
        query[f"{dest}_id"] = ids

    if getattr(parsed_args, "status", None):
        query["status"] = list(parsed_args.status)

    for item in getattr(parsed_args, "netbox_filter", None) or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise SelectionError(f"Invalid filter {item!r}, expected KEY=VALUE")
        query.setdefault(key, []).append(value)

    query.setdefault("status", [DEFAULT_STATUS])
    return query


def load_inventory_hosts(limit: Optional[str] = None) -> List[str]:
    """Return the hosts of the Ansible inventory, optionally limited.

    Raises:
        SelectionError: The inventory could not be loaded
    """
    command = [
        "ansible-inventory",
        "-i",
        get_inventory_path(INVENTORY_PATH),
        "--list",
    ]
    if limit:
        command.extend(["--limit", limit])

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SelectionError("Timeout loading inventory.")

    if result.returncode != 0:
        raise SelectionError("Error loading inventory.")

    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise SelectionError("Could not parse inventory.")

    return get_hosts_from_inventory(data)


def managed_switch_ids(nb) -> Set[int]:
    """Return the IDs of the devices matching NETBOX_FILTER_CONDUCTOR_SONIC.

    Those are the switches ``sonic sync`` operates on, and therefore the ones
    the operator key is deployed to.
    """
    # Imported here: the conductor package is expensive to import and only
    # needed when switches are part of the selection.
    from osism.tasks.conductor.netbox import get_nb_device_query_list_sonic

    ids: Set[int] = set()
    for query in get_nb_device_query_list_sonic():
        for device in nb.dcim.devices.filter(**query):
            ids.add(device.id)
    return ids


def select_targets(parsed_args, nb) -> List[Target]:
    """Evaluate the selection options and return the devices to query.

    Args:
        parsed_args: Namespace holding the options of
            ``add_selection_arguments``
        nb: pynetbox API object, or ``None`` when NetBox is not configured

    Returns:
        Targets sorted by name, without addresses

    Raises:
        SelectionError: The selection could not be evaluated, or it matched
            no device
    """
    if nb is None:
        targets = _select_from_inventory(parsed_args)
    else:
        targets = _select_from_netbox(parsed_args, nb)

    if not targets:
        raise SelectionError("No devices matched the selection.")

    return sorted(targets, key=lambda target: target.name)


def resolve_addresses(
    targets: Iterable[Target], resolve_node: Callable[[str], str]
) -> None:
    """Set the SSH address and user of every target.

    Nodes are reached as the operator user at the address ``resolve_node``
    returns for the inventory hostname. Switches are reached at the
    management IP of their config context, else the OOB IP, else the primary
    IP. A switch without any of these keeps an empty address.

    This talks to NetBox for switches without an OOB IP and has to run in
    the main thread, before the collection starts.
    """
    for target in targets:
        if target.kind == KIND_SWITCH:
            target.address, target.user = _switch_access(target.device)
        else:
            target.address = resolve_node(target.hostname)
            target.user = settings.OPERATOR_USER


def _select_from_inventory(parsed_args) -> List[Target]:
    if uses_netbox_filters(parsed_args):
        raise SelectionError(
            "NetBox is not configured, NetBox filters cannot be used. "
            "Select nodes by NAME or --limit."
        )
    if parsed_args.type == KIND_SWITCH:
        raise SelectionError(
            "NetBox is not configured, SONiC switches cannot be discovered."
        )

    hosts = load_inventory_hosts(parsed_args.limit)
    return [
        Target(name=host, hostname=host, kind=KIND_NODE)
        for host in hosts
        if _matches(parsed_args.names, host)
    ]


def _select_from_netbox(parsed_args, nb) -> List[Target]:
    from osism.tasks.conductor.sonic.constants import DEFAULT_SONIC_ROLES

    want_nodes = parsed_args.type in ("all", KIND_NODE)
    # --limit is an Ansible pattern and can only ever select inventory hosts
    want_switches = parsed_args.type in ("all", KIND_SWITCH) and not parsed_args.limit

    inventory_hosts: Set[str] = set()
    if want_nodes:
        inventory_hosts = set(load_inventory_hosts(parsed_args.limit))

    query = build_netbox_query(parsed_args, nb)
    try:
        devices = [dict(record) for record in nb.dcim.devices.filter(**query)]
    except Exception as exc:
        raise SelectionError(f"NetBox device query failed: {exc}")

    managed: Optional[Set[int]] = None
    targets: List[Target] = []
    unmanaged: List[str] = []
    selected_hosts: Set[str] = set()

    for device in devices:
        name = device.get("name") or ""
        hostname = _hostname(device)
        if not name or not _matches(parsed_args.names, name, hostname):
            continue

        if _role_slug(device) in DEFAULT_SONIC_ROLES:
            if not want_switches:
                continue
            if not parsed_args.include_unmanaged:
                if managed is None:
                    try:
                        managed = managed_switch_ids(nb)
                    except Exception as exc:
                        raise SelectionError(
                            f"Could not evaluate NETBOX_FILTER_CONDUCTOR_SONIC: {exc}"
                        )
                if device.get("id") not in managed:
                    unmanaged.append(name)
                    continue
            targets.append(_target(device, KIND_SWITCH))
        elif want_nodes and hostname in inventory_hosts:
            targets.append(_target(device, KIND_NODE))
            selected_hosts.add(hostname)
        else:
            logger.debug(f"Skipping {name}: neither a managed node nor a SONiC switch")

    if unmanaged:
        logger.warning(
            f"Skipping {len(unmanaged)} SONiC switch(es) not matching "
            f"NETBOX_FILTER_CONDUCTOR_SONIC: {', '.join(sorted(unmanaged))}. "
            "Use --include-unmanaged to query them."
        )

    # Without any narrowing option every inventory host is expected to show
    # up. A host that does not is missing in NetBox or not active there.
    if want_nodes and not parsed_args.names and not uses_netbox_filters(parsed_args):
        unknown = sorted(inventory_hosts - selected_hosts)
        if unknown:
            logger.warning(
                f"Skipping {len(unknown)} inventory host(s) without an active "
                f"NetBox device: {', '.join(unknown)}"
            )

    return targets


def _target(device: Dict[str, Any], kind: str) -> Target:
    return Target(
        name=device["name"],
        hostname=_hostname(device),
        kind=kind,
        device_id=device.get("id"),
        device=device,
    )


def _matches(patterns: Optional[List[str]], *names: str) -> bool:
    if not patterns:
        return True
    return any(
        fnmatch.fnmatchcase(name, pattern) for pattern in patterns for name in names
    )


def _hostname(device: Dict[str, Any]) -> str:
    custom_fields = device.get("custom_fields") or {}
    return custom_fields.get("inventory_hostname") or device.get("name") or ""


def _role_slug(device: Dict[str, Any]) -> Optional[str]:
    # NetBox before 3.6 calls the field device_role
    role = device.get("role") or device.get("device_role") or {}
    return role.get("slug")


def _nested(data: Dict[str, Any], key: str, attribute: str) -> Any:
    return (data.get(key) or {}).get(attribute)


def _address(value: Any) -> str:
    """Return the bare address of a NetBox IP (``10.0.0.1/24`` -> ``10.0.0.1``)."""
    if isinstance(value, dict):
        value = value.get("address")
    return str(value).split("/")[0] if value else ""


def _switch_access(device: Dict[str, Any]) -> tuple:
    management = (device.get("local_context_data") or {}).get("management") or {}
    user = management.get("username") or DEFAULT_SWITCH_USER

    address = _address(management.get("ip")) or _address(device.get("oob_ip"))
    if not address:
        # Falls back to the IP of a management interface, which costs NetBox
        # queries and is therefore only tried when there is no OOB IP field.
        from osism.tasks.conductor.netbox import get_device_oob_ip

        oob = get_device_oob_ip(
            SimpleNamespace(id=device.get("id"), name=device.get("name"), oob_ip=None)
        )
        if oob:
            address = oob[0]
    if not address:
        address = _address(device.get("primary_ip4")) or _address(
            device.get("primary_ip6")
        )
    return address, user
