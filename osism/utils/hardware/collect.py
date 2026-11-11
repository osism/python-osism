# SPDX-License-Identifier: Apache-2.0

"""Parallel collection of raw hardware data over SSH.

Every device gets one SSH session. The session pipes a small, stdlib-only
collector script to ``python3 -`` on the device, and the script prints one
JSON document with raw command output and sysfs or database values. Parsing
happens afterwards on the manager, see the ``parse_*`` modules.

Nothing in here talks to NetBox, so the collection can fan out to worker
threads while the NetBox session stays in the main thread.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Callable, Dict, Iterable, List

from osism.utils.hardware.selection import KIND_NODE, KIND_SWITCH, Target
from osism.utils.ssh import run_remote

COLLECTORS = {
    KIND_NODE: "remote_linux.py",
    KIND_SWITCH: "remote_sonic.py",
}


class CollectError(Exception):
    """A device could not be queried."""


@dataclass
class Request:
    """What to collect on the devices of one kind.

    Attributes:
        sections: Names of the collector sections to run
        options: Further command line options of the collector
        sudo: Run the collector as root (``sudo -n``)
    """

    sections: List[str]
    options: List[str] = field(default_factory=list)
    sudo: bool = False


@dataclass
class Collection:
    """Result of a collection run.

    Attributes:
        documents: Raw collector document per device name
        failed: Devices that could not be queried, as ``{"name", "error"}``
    """

    documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    failed: List[Dict[str, str]] = field(default_factory=list)


def add_collection_arguments(parser) -> None:
    """Add the collection options shared by the hardware reports."""
    parser.add_argument(
        "--parallel",
        type=int,
        default=10,
        metavar="N",
        help="Number of devices queried at the same time (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        metavar="SECONDS",
        help="Seconds one device may take (default: 60)",
    )
    parser.add_argument(
        "--dump-raw",
        metavar="DIR",
        help="Write the raw data collected from each device to DIR/<device>.json",
    )


def collector_script(kind: str) -> str:
    """Return the source of the collector for a device kind."""
    return (Path(__file__).parent / COLLECTORS[kind]).read_text()


def remote_command(request: Request) -> str:
    """Return the command line that runs a collector read from stdin."""
    arguments = ["python3", "-", "--sections", ",".join(request.sections)]
    arguments.extend(request.options)
    command = " ".join(shlex.quote(argument) for argument in arguments)
    return f"sudo -n {command}" if request.sudo else command


def collect_one(
    target: Target,
    request: Request,
    timeout: float,
    run: Callable[..., subprocess.CompletedProcess] = run_remote,
) -> Dict[str, Any]:
    """Run the collector on one device and return its document.

    Raises:
        CollectError: The device has no address, did not answer in time,
            refused the login, or returned something that is not a
            collector document
    """
    if not target.address:
        raise CollectError("no management address")

    try:
        result = run(
            target.address,
            target.user,
            remote_command(request),
            stdin=collector_script(target.kind),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CollectError("timeout")

    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        raise CollectError(lines[-1] if lines else f"exit code {result.returncode}")

    try:
        document = json.loads(result.stdout)
    except ValueError:
        raise CollectError("unparsable collector output")
    if not isinstance(document, dict):
        raise CollectError("unparsable collector output")

    return document


def collect(
    targets: Iterable[Target],
    requests: Dict[str, Request],
    parallel: int = 10,
    timeout: float = 60,
    run: Callable[..., subprocess.CompletedProcess] = run_remote,
) -> Collection:
    """Query all targets in parallel.

    A device that cannot be queried is recorded in ``failed``. It neither
    aborts the run nor delays the other devices beyond ``timeout``.

    Args:
        targets: Devices to query, with addresses resolved
        requests: What to collect, per device kind
        parallel: Number of devices queried at the same time
        timeout: Seconds one device may take
        run: Function executing the remote command, replaceable in tests
    """
    targets = list(targets)
    collection = Collection()

    def job(target: Target) -> Dict[str, Any]:
        return collect_one(target, requests[target.kind], timeout, run)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
        futures = [(target, executor.submit(job, target)) for target in targets]
        for target, future in futures:
            try:
                collection.documents[target.name] = future.result()
            except CollectError as exc:
                collection.failed.append({"name": target.name, "error": str(exc)})
            except Exception as exc:
                collection.failed.append(
                    {"name": target.name, "error": f"{type(exc).__name__}: {exc}"}
                )

    return collection


def dump_raw(collection: Collection, directory: str) -> List[str]:
    """Write every raw collector document to ``<directory>/<name>.json``.

    The files are what the parsers consume, which makes them usable as test
    fixtures and as attachments to a bug report.

    Returns:
        Paths of the files written
    """
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, document in sorted(collection.documents.items()):
        path = base / f"{name.replace('/', '_')}.json"
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        paths.append(str(path))
    return paths
