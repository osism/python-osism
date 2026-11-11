# SPDX-License-Identifier: Apache-2.0

"""Collector for Linux nodes, executed on the node itself.

This file is piped to ``python3 -`` over SSH. It must stay self-contained:
standard library only, no imports from ``osism``, and no syntax newer than
Python 3.6, because it runs with whatever interpreter the node has.

It only gathers raw command output and sysfs values and prints them as one
JSON document. All parsing happens on the manager (``parse_linux``,
``parse_lldp``), where it can be tested against captured documents.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys

VERSION = 1
SYS_NET = "/sys/class/net"

ARPHRD_ETHER = "1"
ARPHRD_INFINIBAND = "32"

SYSFS_ATTRIBUTES = [
    "address",
    "carrier",
    "dev_port",
    "duplex",
    "mtu",
    "operstate",
    "phys_port_name",
    "speed",
    "type",
]

# phys_port_name of a switchdev representor, e.g. pf0vf3 or c1pf0sf2
REPRESENTOR = re.compile(r"pf\d+(vf|sf)\d+$")


def run(argv, timeout=20):
    """Run a command and return its exit code and output as a dict."""
    try:
        process = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
    except OSError as exc:
        return {"rc": 127, "out": "", "err": str(exc)}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "out": "", "err": "timeout"}
    return {
        "rc": process.returncode,
        "out": process.stdout,
        "err": process.stderr.strip(),
    }


def read(path):
    """Return the stripped content of a file, or None when it is unreadable."""
    try:
        with open(path) as handle:
            return handle.read().strip()
    except (IOError, OSError):
        return None


def port_kind(name, sys_net=SYS_NET):
    """Classify a network device.

    Returns ``physical``, ``vf`` or ``infiniband`` for a port backed by
    hardware, and None for everything else: bonds, bridges, VLANs and other
    virtual devices have no ``device`` link, and switchdev representors stand
    for a function of the NIC, not for a port.
    """
    base = os.path.join(sys_net, name)
    if not os.path.exists(os.path.join(base, "device")):
        return None

    link_type = read(os.path.join(base, "type"))
    if link_type == ARPHRD_INFINIBAND:
        return "infiniband"
    if link_type != ARPHRD_ETHER:
        return None

    if os.path.exists(os.path.join(base, "device", "physfn")):
        return "vf"
    if REPRESENTOR.search(read(os.path.join(base, "phys_port_name")) or ""):
        return None
    return "physical"


def list_ports(kinds, sys_net=SYS_NET):
    """Return ``{name: kind}`` for the ports of the requested kinds."""
    try:
        names = sorted(os.listdir(sys_net))
    except OSError:
        return {}
    ports = {}
    for name in names:
        kind = port_kind(name, sys_net)
        if kind in kinds:
            ports[name] = kind
    return ports


def collect_port(name, kind, sys_net=SYS_NET, runner=run):
    """Collect identity and link state of one port."""
    base = os.path.join(sys_net, name)
    port = {
        "kind": kind,
        "sysfs": dict(
            (attribute, read(os.path.join(base, attribute)))
            for attribute in SYSFS_ATTRIBUTES
        ),
        "pci": os.path.basename(os.path.realpath(os.path.join(base, "device"))),
        "ethtool_P": runner(["ethtool", "-P", name]),
    }
    if kind == "vf":
        try:
            port["physfn"] = sorted(
                os.listdir(os.path.join(base, "device", "physfn", "net"))
            )
        except OSError:
            port["physfn"] = []
    return port


def section_ports(document, ports, sys_net, runner):
    document["ip_link"] = runner(["ip", "-j", "-d", "link", "show"])
    for name, kind in ports.items():
        document["ports"][name].update(collect_port(name, kind, sys_net, runner))


def section_lldp(document, ports, sys_net, runner):
    document["lldpctl"] = runner(["lldpctl", "-f", "json"])


SECTIONS = {
    "ports": section_ports,
    "lldp": section_lldp,
}


def collect(sections, kinds, sys_net=SYS_NET, runner=run):
    """Run the requested sections and return the document."""
    ports = list_ports(kinds, sys_net)
    document = {
        "collector": "linux",
        "version": VERSION,
        "hostname": socket.gethostname(),
        "sections": sections,
        "ports": dict((name, {}) for name in ports),
    }
    for section in sections:
        SECTIONS[section](document, ports, sys_net, runner)
    return document


def main(argv=None, sys_net=SYS_NET, runner=run, stream=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", default="ports")
    parser.add_argument("--include-vf", action="store_true")
    parser.add_argument("--include-infiniband", action="store_true")
    arguments = parser.parse_args(argv)

    sections = [name for name in arguments.sections.split(",") if name]
    unknown = [name for name in sections if name not in SECTIONS]
    if unknown:
        sys.stderr.write("unknown section(s): %s\n" % ", ".join(unknown))
        return 2

    kinds = ["physical"]
    if arguments.include_vf:
        kinds.append("vf")
    if arguments.include_infiniband:
        kinds.append("infiniband")

    json.dump(collect(sections, kinds, sys_net, runner), stream or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
