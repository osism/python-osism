# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import tempfile

from loguru import logger


class HostContextResolutionError(Exception):
    """Raised when an expression cannot be templated in a host's context."""


def get_inventory_path(base_path: str, prefer_minified: bool = True) -> str:
    """Return the best available inventory path.

    Resolution order:
    1. If prefer_minified and hosts-minified.yml exists, use it.
    2. If a ``fast/`` directory exists next to hosts.yml, use it.
    3. Fall back to the original base_path.

    The minified inventory (hosts-minified.yml) contains only hosts and their
    group memberships. It is faster to parse than the full inventory and can
    be used for operations that only need to resolve hosts and groups.

    The fast inventory directory is structurally equivalent to hosts.yml but
    optimised for faster parsing by Ansible.

    Args:
        base_path: The original inventory path
                   (e.g., "/ansible/inventory/hosts.yml")
        prefer_minified: If True, try to use hosts-minified.yml first

    Returns:
        Path to the inventory file or directory to use
    """
    directory = os.path.dirname(base_path)

    if prefer_minified:
        minified_path = os.path.join(directory, "hosts-minified.yml")
        if os.path.exists(minified_path):
            logger.debug(f"Using minified inventory: {minified_path}")
            return minified_path

    fast_path = os.path.join(directory, "fast")
    if os.path.isdir(fast_path):
        logger.debug(f"Using fast inventory: {fast_path}")
        return fast_path

    return base_path


def get_hosts_from_inventory(data: dict) -> list:
    """Extract host names from ansible-inventory --list JSON output.

    The minified inventory does not populate _meta.hostvars (since hosts
    have no variables), so we also collect hosts from group listings.
    """
    hosts = set(data.get("_meta", {}).get("hostvars", {}).keys())
    for key, value in data.items():
        if key == "_meta":
            continue
        if isinstance(value, dict) and "hosts" in value:
            hosts.update(value["hosts"])
    return sorted(hosts)


def resolve_in_host_context(
    host: str,
    expression: str,
    inventory_path: str,
    facts: dict | None = None,
    timeout: int = 60,
) -> str:
    """Template a Jinja2 expression in a host's Ansible variable context.

    ``ansible-inventory --host`` returns variables *as defined*, so anything
    Jinja-valued comes back as the raw ``{{ ... }}``. Resolving such a value
    requires Ansible's own templating, in the host's variable context -- see
    ``osism/defaults`` ``all/README.md``, section "Consuming these values from
    code". Re-implementing the templating in the consumer is not an option: it
    only ever covers the shapes that were thought of.

    The value is produced by having Ansible ``copy`` the templated expression
    into a file, run with ``-c local`` so the module executes on the controller.
    No connection is made to the host, so this works for hosts that are down or
    unreachable, and the value is read back byte-exact instead of being parsed
    out of human-readable output. That matters because the callback formats
    differ between the ansible-core versions this package runs under, and
    because ``--tree``, the other way to get structured output, is deprecated
    for removal in ansible-core 2.23.

    Facts are passed as extra vars rather than through a fact-cache plugin.
    That keeps the call independent of which cache plugin is configured (the
    ``redis`` plugin lives in ``community.general``, which is not installed
    here) and of the Ansible version: ansible-core 2.18 exposes cached facts to
    an ad-hoc ``debug`` while 2.19 does not, whereas extra vars behave
    identically on both. Extra vars outrank everything, which is what we want
    for facts -- they already outrank host_vars in normal precedence.

    Args:
        host: Inventory hostname to evaluate the expression for.
        expression: Jinja2 expression *without* the surrounding braces.
        inventory_path: Inventory to resolve the host and its variables from.
        facts: Ansible facts for the host, as stored in the fact cache.
        timeout: Seconds to wait for Ansible.

    Returns:
        The templated value, as a string.

    Raises:
        HostContextResolutionError: If Ansible could not evaluate the
            expression. The message carries Ansible's own explanation, which
            names the undefined variable or attribute.
    """
    env = os.environ.copy()
    # The module runs locally, but be explicit: never gather facts, so a host
    # that is down cannot turn a lookup into an SSH timeout.
    env["ANSIBLE_GATHERING"] = "explicit"
    env["ANSIBLE_RETRY_FILES_ENABLED"] = "False"
    env["ANSIBLE_NOCOLOR"] = "1"

    with tempfile.TemporaryDirectory(prefix="osism-resolve-") as workdir:
        value_path = os.path.join(workdir, "value")
        # JSON module args rather than key=value, so a value containing spaces
        # survives.
        module_args = json.dumps(
            {"content": "{{ %s }}" % expression, "dest": value_path}
        )
        command = [
            "ansible",
            host,
            "-i",
            inventory_path,
            "-c",
            "local",
            "-m",
            "copy",
            "-a",
            module_args,
        ]
        if facts:
            facts_path = os.path.join(workdir, "facts.json")
            with open(facts_path, "w") as fp:
                json.dump(facts, fp)
            command += ["-e", f"@{facts_path}"]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise HostContextResolutionError(
                f"ansible timed out after {timeout}s"
            ) from exc

        if result.returncode != 0:
            # Ansible names the undefined variable, which is the most useful
            # thing to pass on. Its wording and stream differ between versions,
            # so take whichever of the two is non-empty and do not parse it.
            detail = (result.stdout or "").strip() or (result.stderr or "").strip()
            raise HostContextResolutionError(
                detail or f"ansible exited {result.returncode}"
            )

        try:
            with open(value_path) as fp:
                return fp.read()
        except OSError as exc:
            raise HostContextResolutionError("ansible wrote no value") from exc
