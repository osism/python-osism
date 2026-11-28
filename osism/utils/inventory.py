# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
import tempfile

from loguru import logger

_RESOLVE_ACTION_PLUGIN = """\
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        with open(self._task.args["dest"], "w") as fp:
            # Ansible types the templated result, so a numeric expression
            # arrives as an int, which write() rejects. Convert it, so any
            # expression resolves and not just the ones that happen to yield
            # a string.
            fp.write(str(self._task.args["content"]))
        result["changed"] = False
        return result
"""


class HostContextResolutionError(Exception):
    """Raised when an expression cannot be templated in a host's context.

    ``from_ansible`` is True when the message is Ansible's own output, which
    may quote variable values; it is False for messages composed here.
    """

    def __init__(self, message: str, from_ansible: bool = False):
        super().__init__(message)
        self.from_ansible = from_ansible


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

    The value is produced by a controller-side Ansible action plugin. Ansible
    templates the plugin arguments in the target host's variable context, but
    the plugin writes the result locally without making a connection or
    launching a module with the target's Python interpreter. This works for
    hosts that are down or unreachable and preserves the value byte-exact
    instead of parsing it out of human-readable output. That matters because
    callback formats differ between the ansible-core versions this package
    runs under.

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
    return run_in_host_context(
        host,
        inventory_path,
        "osism_resolve",
        _RESOLVE_ACTION_PLUGIN,
        # JSON module args rather than key=value, so a value containing spaces
        # survives.
        {"content": "{{ %s }}" % expression},
        facts=facts,
        timeout=timeout,
    )


def run_in_host_context(
    host: str,
    inventory_path: str,
    plugin_name: str,
    plugin_source: str,
    args: dict,
    request: object = None,
    facts: dict | None = None,
    extra_vars_files: tuple = (),
    vault_password: str | None = None,
    timeout: int = 60,
) -> str:
    """Run a controller-side action plugin in a host's variable context.

    The one engine behind ``resolve_in_host_context`` and the batch renderer
    of ``osism dump inventory`` (``osism.utils.render``). Each brings its own
    plugin, because what it templates differs; everything around the plugin
    lives here once:

    - The plugin is installed into a temporary directory, which is also the
      working directory, so no ``group_vars/`` next to the caller's current
      directory leaks into the run.
    - ``-c local`` with an action plugin: no connection, no module launched
      with the target's interpreter, so a host that is down still resolves.
      Facts are never gathered and stdin is closed.
    - Facts travel as an extra-vars file, ahead of ``extra_vars_files``: a
      later ``-e`` wins, and in a play extra vars outrank facts.
    - The plugin writes its result to the file named by the ``dest``
      argument, which is read back byte-exact instead of parsed out of
      Ansible's output, whose format differs between ansible-core versions.

    Args:
        args: Module arguments; ``dest`` is added, and ``request`` when a
            request is given. Ansible templates them in the host's context.
        request: Optional JSON data for the plugin, passed as a file so that
            Ansible does not template it.
        vault_password: Optional; given to Ansible as a password file.

    Returns:
        The text the plugin wrote.

    Raises:
        HostContextResolutionError: Ansible failed (``from_ansible`` set; the
            message is its output), timed out, or wrote nothing.
    """
    env = os.environ.copy()
    env.update(
        ANSIBLE_GATHERING="explicit",
        ANSIBLE_NOCOLOR="1",
        # ANSIBLE_FORCE_COLOR in the caller's environment beats NOCOLOR.
        ANSIBLE_FORCE_COLOR="0",
        ANSIBLE_RETRY_FILES_ENABLED="False",
    )

    with tempfile.TemporaryDirectory(prefix="osism-host-context-") as workdir:
        with open(os.path.join(workdir, f"{plugin_name}.py"), "w") as fp:
            fp.write(plugin_source)
        env["ANSIBLE_ACTION_PLUGINS"] = os.pathsep.join(
            part for part in (workdir, env.get("ANSIBLE_ACTION_PLUGINS")) if part
        )

        dest = os.path.join(workdir, "value")
        args = dict(args, dest=dest)
        if request is not None:
            args["request"] = os.path.join(workdir, "request.json")
            with open(args["request"], "w") as fp:
                json.dump(request, fp)

        command = [
            "ansible",
            host,
            "-i",
            inventory_path,
            "-c",
            "local",
            "-m",
            plugin_name,
            "-a",
            json.dumps(args),
        ]
        if vault_password is not None:
            vault_file = os.path.join(workdir, "vault")
            with open(os.open(vault_file, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fp:
                fp.write(vault_password)
            command += ["--vault-password-file", vault_file]
        if facts:
            facts_path = os.path.join(workdir, "facts.json")
            with open(facts_path, "w") as fp:
                json.dump(facts, fp)
            command += ["-e", f"@{facts_path}"]
        for path in extra_vars_files:
            command += ["-e", f"@{path}"]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=workdir,
                stdin=subprocess.DEVNULL,
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
                detail or f"ansible exited {result.returncode}", from_ansible=True
            )

        try:
            with open(dest) as fp:
                return fp.read()
        except OSError as exc:
            raise HostContextResolutionError("ansible wrote no value") from exc
