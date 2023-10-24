# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import ipaddress
import os

from loguru import logger
import git
import gitdb
import jinja2
from pottery import Redlock

from osism.utils import first
from osism import utils


def vlans_as_string(untagged_vlan, tagged_vlans):
    vlans = [str(x.vid) for x in tagged_vlans]
    if untagged_vlan:
        vlans = vlans + [str(untagged_vlan.vid)]
    return ",".join(sorted(vlans))


def for_device(name, template=None):
    device = utils.nb.dcim.devices.get(name=name)

    if (
        "device_type" not in device.custom_fields
        or device.custom_fields["device_type"] != "switch"
    ):
        return

    if "Managed by OSISM" not in [str(x) for x in device.tags]:
        return

    logger.info(f"Generate configuration for device {device.name}")

    if not template:
        template = f"{device.name}.cfg.j2"

        if not os.path.isfile(f"/netbox/templates/{template}"):
            template = f"{device.device_type.manufacturer.name}.cfg.j2"

        if not os.path.isfile(f"/netbox/templates/{template}"):
            template = "default.cfg.j2"

    vlans = utils.nb.ipam.vlans.filter(available_on_device=device.id)
    interfaces = utils.nb.dcim.interfaces.filter(device=device)

    interfaces_ethernet = []
    interfaces_port_channels = []
    interfaces_virtual = []

    for interface in interfaces:
        if str(interface.type) == "Link Aggregation Group (LAG)":
            interfaces_port_channels.append(interface)
        elif str(interface.type) == "Virtual":
            interfaces_virtual.append(interface)
        else:
            interfaces_ethernet.append(interface)

    # Port-Channel10 + Vlan4094 are always used as MLAG
    try:
        mlag = utils.nb.dcim.interfaces.get(device=device, name="Port-Channel10")
        mlag_vlan = utils.nb.dcim.interfaces.get(device=device, name="Vlan4094")
        mlag_address = utils.nb.ipam.ip_addresses.get(
            device=device, interface="Vlan4094"
        )
    except:  # noqa
        mlag = None
        mlag_vlan = None
        mlag_address = None

    # NOTE: only work with /30
    try:
        x = list(ipaddress.ip_interface(mlag_address.address).network.hosts())
        x.remove(ipaddress.ip_interface(mlag_address.address).ip)
        mlag_peer_address = x[0]
    except:  # noqa
        mlag_peer_address = None

    try:
        mlag_domain_id = device.name.split("-")[1]
    except:  # noqa
        mlag_domain_id = None

    repo = git.Repo.init(path="/state")
    repo.config_writer().set_value("user", "name", "Netbox Generator").release()
    repo.config_writer().set_value(
        "user", "email", "netbox-generator@reconciler.local"
    ).release()

    data = {
        "hostname": device.name,
        "interfaces_ethernet": interfaces_ethernet,
        "interfaces_virtual": interfaces_virtual,
        "interfaces_port_channels": interfaces_port_channels,
        "vlans": vlans,
        "device": name,
        "nb": utils.nb,
        "first": first,
        "vlans_as_string": vlans_as_string,
        "mlag": mlag,
        "mlag_vlan": mlag_vlan,
        "mlag_peer_address": mlag_peer_address,
        "mlag_domain_id": mlag_domain_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "device_type": device.device_type.model,
        "device_manufacturer": device.device_type.manufacturer.name,
    }

    loader = jinja2.FileSystemLoader(searchpath="/netbox/templates/")
    environment = jinja2.Environment(loader=loader)
    template = environment.get_template(template)
    result = template.render(data)

    logger.info(f"Writing generated configuration to /state/{device.name}.cfg.j2")
    with open(f"/state/{device.name}.cfg.j2", "w+") as fp:
        fp.write(os.linesep.join([s for s in result.splitlines() if s]))

    # Allow only one change per time
    lock = Redlock(key="lock_repository", masters={utils.redis})
    lock.acquire()

    repo.git.add(f"/state/{device.name}.cfg.j2")

    try:
        if len(repo.index.diff("HEAD")) > 0:
            logger.info(f"Committing changes in /state/{device.name}.cfg.j2")
            repo.git.commit(message=f"Update {device.name}")

    # Ref 'HEAD' did not resolve to an object
    except gitdb.exc.BadName:
        logger.info("Initial commit")
        repo.git.commit(message="Initial commit")

    lock.release()
