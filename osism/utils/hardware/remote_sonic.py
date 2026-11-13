# SPDX-License-Identifier: Apache-2.0

"""Collector for SONiC switches, executed on the switch itself.

This file is piped to ``python3 -`` over SSH. It must stay self-contained:
standard library only, no imports from ``osism``, and no syntax newer than
Python 3.6, because it runs with the interpreter of the SONiC host system.

It reads the SONiC Redis databases with ``sonic-db-dump`` instead of parsing
the human-readable ``show`` tables, and prints the raw dumps as one JSON
document. All parsing happens on the manager (``parse_sonic``,
``parse_lldp``), where it can be tested against captured documents.
"""

import argparse
import json
import os
import socket
import subprocess
import sys

VERSION = 1
SYS_NET = "/sys/class/net"
MGMT_PORT = "eth0"

# Tables dumped per section: (database, table, key pattern, mandatory)
TABLES = {
    "ports": [
        ("CONFIG_DB", "PORT", "PORT|*", True),
        ("CONFIG_DB", "DEVICE_METADATA", "DEVICE_METADATA|localhost", False),
        ("APPL_DB", "PORT_TABLE", "PORT_TABLE:*", False),
    ],
}


def run(argv, timeout=30):
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


def db_dump(database, pattern, runner=run):
    """Dump the keys of a database matching a pattern.

    The dump is tried as the login user first and with ``sudo -n`` second,
    because access to Redis is restricted on some SONiC releases.

    Returns:
        ``(dump, access, error)``: the parsed dump with the access method
        that worked, or None with the last error
    """
    error = "no output"
    for access, prefix in (("user", []), ("sudo", ["sudo", "-n"])):
        result = runner(prefix + ["sonic-db-dump", "-n", database, "-y", "-k", pattern])
        if result["rc"] != 0:
            error = result["err"] or "exit code %d" % result["rc"]
            continue
        try:
            dump = json.loads(result["out"] or "{}")
        except ValueError:
            error = "unparsable sonic-db-dump output"
            continue
        if isinstance(dump, dict):
            return dump, access, None
        error = "unparsable sonic-db-dump output"
    return None, None, error


def extra_ports(document, sys_net, runner):
    base = os.path.join(sys_net, MGMT_PORT)
    if os.path.isdir(base):
        document["mgmt"] = {
            MGMT_PORT: dict(
                (attribute, read(os.path.join(base, attribute)))
                for attribute in ("address", "carrier", "mtu", "operstate", "speed")
            )
        }


EXTRAS = {
    "ports": extra_ports,
}


def collect(sections, sys_net=SYS_NET, runner=run):
    """Run the requested sections and return the document.

    Raises:
        RuntimeError: A mandatory table could not be read
    """
    document = {
        "collector": "sonic",
        "version": VERSION,
        "hostname": socket.gethostname(),
        "sections": sections,
        "db": {},
        "errors": {},
    }
    for section in sections:
        for database, table, pattern, mandatory in TABLES.get(section, []):
            dump, access, error = db_dump(database, pattern, runner)
            if dump is None:
                if mandatory:
                    raise RuntimeError(
                        "cannot read %s %s: %s" % (database, table, error)
                    )
                document["errors"]["%s %s" % (database, table)] = error
                continue
            document["db"].setdefault(database, {})[table] = dump
            document["db_access"] = access
        extra = EXTRAS.get(section)
        if extra:
            extra(document, sys_net, runner)
    return document


def main(argv=None, sys_net=SYS_NET, runner=run, stream=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", default="ports")
    arguments = parser.parse_args(argv)

    sections = [name for name in arguments.sections.split(",") if name]
    unknown = [name for name in sections if name not in TABLES and name not in EXTRAS]
    if unknown:
        sys.stderr.write("unknown section(s): %s\n" % ", ".join(unknown))
        return 2

    try:
        document = collect(sections, sys_net, runner)
    except RuntimeError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1

    json.dump(document, stream or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
