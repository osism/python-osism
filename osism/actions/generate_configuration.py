from datetime import datetime
import ipaddress
import logging
import os

import git
import jinja2
from osism.tasks import ansible
from osism.utils import first
from osism import utils
from pottery import Redlock


def vlans_as_string(untagged_vlan, tagged_vlans):
    vlans = [str(x.vid) for x in tagged_vlans]
    if untagged_vlan:
        vlans = vlans + [str(untagged_vlan.vid)]
    return ",".join(sorted(vlans))


def for_device(name, template=None):
    device = utils.nb.dcim.devices.get(name=name)

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
        mlag_address = utils.nb.ipam.ip_addresses.get(device=device, interface="Vlan4094")
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

    mlag_domain_id = device.name.split("-")[1]

    repo = git.Repo.init(path="/state")
    repo.config_writer().set_value("user", "name", "Netbox Generator").release()
    repo.config_writer().set_value("user", "email", "netbox-generator@reconciler.local").release()

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
        "device_manufacturer": device.device_type.manufacturer.name
    }

    loader = jinja2.FileSystemLoader(searchpath="/netbox/templates/")
    environment = jinja2.Environment(loader=loader)
    template = environment.get_template(template)
    result = template.render(data)

    logging.info(f"Writing generated configuration to /state/{device.name}.cfg.j2")
    with open(f"/state/{device.name}.cfg.j2", "w+") as fp:
        fp.write(os.linesep.join([s for s in result.splitlines() if s]))

    lock = Redlock(key="lock_osism_generate_configuration", masters={utils.redis}, auto_release_time=1000)

    lock.acquire()
    repo.git.add(f"/state/{device.name}.cfg.j2")
    if len(repo.index.diff("HEAD")) > 0:
        logging.info(f"Committing changes in /state/{device.name}.cfg.j2")
        repo.git.commit(message=f"Update {device.name}")

        arguments = []
        arguments.append(f"-e device={device.name}")
        arguments.append(f"-l {device.name}")
        ansible.run.delay("netbox", "deploy", arguments)

    lock.release()
