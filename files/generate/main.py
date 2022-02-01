from datetime import datetime
import ipaddress
import logging
import glob
import os
import sys

import git
import jinja2
from oslo_config import cfg
from osism.tasks import ansible
from osism.utils import first
import pynetbox
import yaml

from osism import settings


def vlans_as_string(untagged_vlan, tagged_vlans):
    vlans = [str(x.vid) for x in tagged_vlans]
    if untagged_vlan:
        vlans = vlans + [str(untagged_vlan.vid)]
    return ",".join(sorted(vlans))

PROJECT_NAME = 'generate'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.BoolOpt('stdout', help='Print configuration on stdout', default=False),
    cfg.StrOpt('device', help='Device', required=True),
    cfg.StrOpt('template', help='Template', required=False),
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

if CONF.debug:
    level = logging.DEBUG
else:
    level = logging.INFO
logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

nb = pynetbox.api(
    settings.NETBOX_URL,
    token=settings.NETBOX_TOKEN
)

if settings.IGNORE_SSL_ERRORS:
    import requests
    requests.packages.urllib3.disable_warnings()
    session = requests.Session()
    session.verify = False
    nb.http_session = session

device = nb.dcim.devices.get(name=CONF.device)
logging.info(f"Generating configuration for device {device.name}")

if CONF.template:
    template = CONF.template
else:
    template = f"{device.name}.cfg.j2"
    
    if not os.path.isfile(f"/netbox/templates/{template}"):
        template = f"{device.device_type.manufacturer.name}.cfg.j2"

    if not os.path.isfile(f"/netbox/templates/{template}"):
        template = "default.cfg.j2"

logging.info(f"Using template {template}")

vlans = nb.ipam.vlans.filter(available_on_device=device.id)
interfaces = nb.dcim.interfaces.filter(device=device)

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
    mlag = nb.dcim.interfaces.get(device=device, name="Port-Channel10")
    mlag_vlan = nb.dcim.interfaces.get(device=device, name="Vlan4094")
    mlag_address = nb.ipam.ip_addresses.get(device=device, interface="Vlan4094")
except:
    mlag = None
    mlag_vlan = None
    mlag_address = None

# NOTE: only work with /30
try:
    x = list(ipaddress.ip_interface(mlag_address.address).network.hosts())
    x.remove(ipaddress.ip_interface(mlag_address.address).ip)
    mlag_peer_address = x[0]
except:
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
    "device": CONF.device,
    "nb": nb,
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

repo.git.add(f"/state/{device.name}.cfg.j2")
if len(repo.index.diff("HEAD")) > 0:
    logging.info(f"Committing changes in /state/{device.name}.cfg.j2")
    repo.git.commit(message=f"Update {device.name}")

    arguments = []
    arguments.append(f"-e device={device.name}")
    arguments.append(f"-l {device.name}")
    ansible.run.delay("netbox", "deploy", arguments)

if CONF.stdout:
    print(os.linesep.join([s for s in result.splitlines() if s]))
