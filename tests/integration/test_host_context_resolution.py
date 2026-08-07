# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``resolve_in_host_context()`` against real Ansible.

The unit tests in ``tests/unit/utils/test_inventory.py`` mock ``subprocess``,
so they pin the shape of the command that gets built and nothing about what
Ansible does with it. Three properties of this helper can only be established
by running Ansible, and each of them has already been wrong once:

- the expression is evaluated in the *target host's* variable context;
- resolution does not depend on the target's ``ansible_python_interpreter``
  existing on the controller -- it is a path chosen for the host, and the
  controller is a different machine (in production, a different container
  image);
- the resolved value is returned as text even when the expression yields a
  non-string, which Ansible types as such.

These drive the public function, so they stay meaningful across changes to how
resolution is implemented.

Requires ``ansible`` on PATH; ``ansible-core`` is not a dependency of this
package -- it comes from the container images -- so these skip without it.
"""

import os
import shutil

import pytest

from osism.utils.inventory import resolve_in_host_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _require_ansible():
    """Skip unless ``ansible`` is on PATH.

    Set OSISM_REQUIRE_ANSIBLE to turn the skip into a failure, so a job that is
    meant to have Ansible cannot pass by skipping everything.
    """
    if shutil.which("ansible"):
        return
    if os.environ.get("OSISM_REQUIRE_ANSIBLE"):
        pytest.fail("OSISM_REQUIRE_ANSIBLE is set but 'ansible' is not on PATH")
    pytest.skip("ansible not on PATH")


@pytest.fixture
def inventory(tmp_path):
    """Build a one-host inventory carrying the given host variables."""

    def _build(**variables):
        path = tmp_path / "hosts.yml"
        lines = ["all:", "  hosts:", "    node1:"]
        # RFC 5737 documentation range: unreachable on purpose, so an
        # implementation that tried to connect would fail here rather than
        # pass quietly.
        variables.setdefault("ansible_host", "192.0.2.10")
        lines += [f"      {key}: {value}" for key, value in variables.items()]
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    return _build


def test_expression_is_evaluated_in_the_host_context(inventory):
    inv = inventory(internal_interface="eth3")

    assert resolve_in_host_context("node1", "internal_interface", inv) == "eth3"


@pytest.mark.parametrize(
    "interpreter",
    ["/usr/bin/python3", "/opt/osism/venv/bin/python3", "/nonexistent/python3"],
    ids=["default", "venv", "absent"],
)
def test_resolution_does_not_need_the_target_interpreter(inventory, interpreter):
    """The interpreter a host declares need not exist on the controller.

    Resolution runs a controller-side action plugin and launches no module, so
    no interpreter is selected. Before that, Ansible used the target's
    ansible_python_interpreter to run the module locally and every lookup in
    the osismclient image died with "/bin/sh: /usr/bin/python3: not found".
    The venv case is not hypothetical -- OSISM's own testbed sets a venv
    interpreter, and /usr/bin/python3 is a default rather than a constant, so
    providing that one path on the controller would not be enough.
    """
    inv = inventory(ansible_python_interpreter=interpreter, internal_interface="eth3")

    assert resolve_in_host_context("node1", "internal_interface", inv) == "eth3"


def test_target_interpreter_is_readable_as_a_host_variable(inventory):
    """The host's own interpreter value must survive resolution.

    Overriding it with an extra var would make the module run locally too, but
    extra vars outrank everything, so the variable would read back as the
    controller's interpreter -- a silently wrong answer from a helper whose
    whole job is to evaluate in the host's context.
    """
    inv = inventory(ansible_python_interpreter="/opt/osism/venv/bin/python3")

    resolved = resolve_in_host_context("node1", "ansible_python_interpreter", inv)

    assert resolved == "/opt/osism/venv/bin/python3"


def test_non_string_result_is_returned_as_text(inventory):
    """A numeric expression resolves rather than raising.

    Ansible types the templated result, so this arrives as an int, which
    write() rejects unless the value is converted. Without that conversion a
    helper documented as generic silently handles only the expressions that
    happen to yield a string.
    """
    inv = inventory(workers=4)

    assert resolve_in_host_context("node1", "workers * 2", inv) == "8"
