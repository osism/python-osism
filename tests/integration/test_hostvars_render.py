# tests/integration/test_hostvars_render.py
# SPDX-License-Identifier: Apache-2.0

"""render_batch end to end against real Ansible; the plugin imports osism."""

import base64
import json
import os
import shutil
import subprocess

import pytest
import yaml

from osism.utils.hostvars import effective_rows
from osism.utils.render import (
    build_stack,
    environment_local_names,
    load_yaml,
    render_batch,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _require_ansible():
    if shutil.which("ansible"):
        return
    if os.environ.get("OSISM_REQUIRE_ANSIBLE"):
        pytest.fail("OSISM_REQUIRE_ANSIBLE is set but 'ansible' is not on PATH")
    pytest.skip("ansible not on PATH")


@pytest.fixture
def setup(tmp_path):
    pw = tmp_path / "pw"
    pw.write_text("probe-vault-pw")
    inline = subprocess.run(
        [
            "ansible-vault",
            "encrypt_string",
            "--vault-password-file",
            str(pw),
            "inline-secret-xyz",
            "--name",
            "inline_pw",
        ],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout
    inv = tmp_path / "hosts.yml"
    inv.write_text("all:\n  hosts:\n    node1:\n      ansible_host: 192.0.2.10\n")
    root = tmp_path / "environments"
    (root / "kolla").mkdir(parents=True)
    (root / "configuration.yml").write_text(
        "n: k1\nk1: '{{ vars[m] }}'\nm: db_password\nd: '{{ vars[n] | b64encode }}'\n"
    )
    (root / "secrets.yml").write_text("db_password: long-secret-1\n")
    subprocess.run(
        [
            "ansible-vault",
            "encrypt",
            "--vault-password-file",
            str(pw),
            str(root / "secrets.yml"),
        ],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    (root / "kolla" / "secrets.yml").write_text("{}\n")
    (root / "kolla" / "images.yml").write_text("{}\n")
    (root / "kolla" / "configuration.yml").write_text(
        inline + "svc_url: 'https://u:{{ inline_pw }}@h'\n"
    )
    return str(inv), str(root)


def test_one_run_resolves_chains_and_vaults(setup):
    inv, root = setup
    stack = build_stack("kolla", root)
    raw = {}
    for path in stack.files:
        raw.update(load_yaml(path, "probe-vault-pw"))
    request = {
        "names": ["d", "svc_url", "zz"],
        "secrets": ["db_password", "inline_pw"],
        "raw": raw,
        "raw_all": {},
    }
    out = render_batch("node1", request, inv, stack, "probe-vault-pw")
    assert out["closures"]["d"]["secret_hits"] == ["db_password"]
    assert out["closures"]["svc_url"]["secret_hits"] == ["inline_pw"]
    assert out["values"]["svc_url"] == {"value": "https://u:inline-secret-xyz@h"}
    assert out["values"]["db_password"] == {"value": "long-secret-1"}
    # hostvars_rows matches this exact shape to drop the row of an absent
    # variable; a change in ansible-core's wording must fail here.
    assert out["values"]["zz"]["error"] == "AnsibleUndefinedVariable: 'zz' is undefined"
    assert raw["inline_pw"].keys() == {"__ansible_vault"}


def test_environment_local_names_reads_inline_vault(setup):
    _, root = setup
    assert environment_local_names("kolla", "probe-vault-pw", root) == {
        "inline_pw",
        "svc_url",
    }


def _inventory_hostvars(inv, host):
    def run(*args):
        return json.loads(
            subprocess.run(
                ["ansible-inventory", "-i", inv, *args],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            ).stdout
        )

    return run("--host", host), run("--list")["_meta"]["hostvars"]


@pytest.fixture
def two_hosts(tmp_path):
    """node1 reads a secret through shapes the walker once missed."""
    inv = tmp_path / "hosts.yml"
    inv.write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        "node1": {
                            "ansible_host": "192.0.2.10",
                            "enc_lookup": "{{ lookup('ansible.builtin.vars', "
                            "'redis_master_password') | b64encode }}",
                            "enc_get": "{{ hostvars[inventory_hostname]"
                            ".get('redis_master_password') | b64encode }}",
                            "bmc_list": "{{ groups['all'] | map('extract', "
                            "hostvars, 'ipmi_password') | select('defined') | list }}",
                            "fb": "{{ nope_undefined | default('fallback-value') }}",
                        },
                        "node2": {
                            "ansible_host": "192.0.2.11",
                            "ipmi_password": "Node2PlainIpmiPw",
                        },
                    }
                }
            }
        )
    )
    root = tmp_path / "environments"
    root.mkdir()
    (root / "configuration.yml").write_text("plain: 1\n")
    (root / "secrets.yml").write_text("redis_master_password: Redis-Secret-42\n")
    raw, all_raw = _inventory_hostvars(str(inv), "node1")
    return dict(
        inventory_path=str(inv),
        vault_password="probe-vault-pw",
        facts=None,
        raw_hostvars=raw,
        all_raw_hostvars=all_raw,
        root=str(root),
    )


@pytest.mark.parametrize("name", ["enc_lookup", "enc_get", "bmc_list"])
def test_real_render_masks_unmodelled_secret_shapes(two_hosts, name):
    rows = effective_rows("node1", name, None, False, **two_hosts)
    assert len(rows) == 1 and rows[0].masked and rows[0].value == "***"
    leaked = (
        "Redis-Secret-42",
        base64.b64encode(b"Redis-Secret-42").decode(),
        "Node2PlainIpmiPw",
    )
    assert not any(s in repr(rows) for s in leaked)
    # The same run shows the value with --show-secrets: the mask is not a
    # render failure in disguise.
    shown = effective_rows("node1", name, None, True, **two_hosts)
    assert any(s in repr(shown) for s in leaked)
