# SPDX-License-Identifier: Apache-2.0

"""Generation driver for the SONiC config E2E test.

Runs ``sync_sonic()`` against the seeded NetBox and asserts that generation
itself succeeded. ``sync_sonic`` returns only a ``{device: config}`` dict:
its internal rc is reported solely through the task layer when a ``task_id``
is set, and per-device failures are logged and swallowed. Success is
therefore asserted here by

- comparing the returned device set against the expectation derived from
  the golden files (``--golden``), and
- failing on any ERROR-level loguru record captured during the run, which
  covers every swallowed-exception path in ``sync.py``.

All environment (NETBOX_API/NETBOX_TOKEN, SONIC_EXPORT_DIR,
SONIC_PORT_CONFIG_PATH, SONIC_EXPORT_IDENTIFIER=hostname) must be set
before this module is imported, since ``osism.settings`` reads it at import
time. The exported files are checked against the goldens by ``compare.py``.
"""

import argparse
import os
import sys
from pathlib import Path

from loguru import logger


def expected_devices(golden_dir, prefix, suffix):
    """Derive the expected device names from the golden file names."""
    devices = set()
    for path in Path(golden_dir).glob("*.json"):
        if path.name.startswith(prefix) and path.name.endswith(suffix):
            devices.add(path.name[len(prefix) : -len(suffix)])
    return devices


def run_generation(sync):
    """Call the sync function, capturing ERROR-level loguru records.

    Returns ``(device_configs, errors)`` where ``errors`` is the list of
    error messages logged during the run.
    """
    errors = []
    sink_id = logger.add(
        lambda message: errors.append(str(message).strip()),
        level="ERROR",
        format="{message}",
    )
    try:
        configs = sync()
    finally:
        logger.remove(sink_id)
    return configs, errors


def main(argv=None, sync=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        help="golden file directory the expected device set is derived from",
    )
    parser.add_argument(
        "--no-expect",
        action="store_true",
        help="skip the device-set check (golden bootstrap / regeneration)",
    )
    args = parser.parse_args(argv)
    if not args.no_expect and not args.golden:
        parser.error("either --golden or --no-expect is required")

    if sync is None:
        missing_env = [
            name for name in ("NETBOX_API", "NETBOX_TOKEN") if not os.environ.get(name)
        ]
        if missing_env:
            print(f"Missing required environment variables: {', '.join(missing_env)}")
            return 2
        from osism.tasks.conductor.sonic.sync import sync_sonic

        sync = sync_sonic

    configs, errors = run_generation(sync)

    failed = False
    for error in errors:
        print(f"ERROR during generation: {error}")
        failed = True

    empty = sorted(name for name, config in configs.items() if not config)
    for name in empty:
        print(f"EMPTY config generated for device: {name}")
        failed = True

    if args.golden:
        from osism import settings

        expected = expected_devices(
            args.golden, settings.SONIC_EXPORT_PREFIX, settings.SONIC_EXPORT_SUFFIX
        )
        for name in sorted(expected - set(configs)):
            print(f"MISSING device (expected from goldens, not generated): {name}")
            failed = True
        for name in sorted(set(configs) - expected):
            print(f"UNEXPECTED device (generated, no golden file): {name}")
            failed = True

    print(f"Generated {len(configs)} SONiC configurations")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
