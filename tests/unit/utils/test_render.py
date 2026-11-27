# tests/unit/utils/test_render.py
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from osism.utils import inventory
from osism.utils.render import (
    RenderError,
    build_stack,
    environment_local_names,
    list_environments,
    load_yaml,
    render_batch,
)


def _envs(tmp_path, *names, files=("configuration.yml", "images.yml", "secrets.yml")):
    root = tmp_path / "environments"
    root.mkdir()
    (root / "configuration.yml").write_text("a: 1\n")
    (root / "secrets.yml").write_text("s: x\n")
    (root / "images.yml").write_text("i: 1\n")
    (root / "ansible.cfg").write_text("")
    (root / ".hidden").mkdir()
    for n in names:
        d = root / n
        d.mkdir()
        for f in files:
            (d / f).write_text(f"{n}_{f.split('.')[0]}: 1\n")
    return str(root)


def test_list_environments_directories_only(tmp_path):
    assert list_environments(_envs(tmp_path, "kolla", "ceph")) == ["ceph", "kolla"]


def test_global_stack_order_and_excludes_top_level_images(tmp_path):
    s = build_stack(None, _envs(tmp_path, "kolla"))
    assert [p.rsplit("/", 1)[1] for p in s.files] == [
        "configuration.yml",
        "secrets.yml",
    ]


def test_environment_stack_order(tmp_path):
    root = _envs(tmp_path, "kolla")
    assert [p.replace(root + "/", "") for p in build_stack("kolla", root).files] == [
        "configuration.yml",
        "secrets.yml",
        "kolla/secrets.yml",
        "kolla/images.yml",
        "kolla/configuration.yml",
    ]


def test_missing_environment_file_is_recorded(tmp_path):
    # Review focus 4
    root = _envs(tmp_path, "kolla", files=("configuration.yml", "secrets.yml"))
    assert build_stack("kolla", root).missing == (f"{root}/kolla/images.yml",)


def test_environment_local_names_excludes_global(tmp_path):
    # Review round 3, point 6
    root = _envs(tmp_path, "kolla")
    assert environment_local_names("kolla", "pw", root) == {
        "kolla_configuration",
        "kolla_images",
        "kolla_secrets",
    }


def test_load_yaml_inline_vault_keeps_provenance(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("p: !vault |\n  $ANSIBLE_VAULT;1.1;AES256\n  6162\nq: plain\n")
    assert load_yaml(str(f), "pw") == {
        "p": {"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n6162\n"},
        "q": "plain",
    }


def test_load_yaml_error_has_no_excerpt(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("db_password: s3cr3t\nbad: [\n")
    with pytest.raises(RenderError) as exc:
        load_yaml(str(f), "pw")
    assert "invalid YAML at line" in str(exc.value) and "s3cr3t" not in str(exc.value)


def test_render_batch_refuses_missing_files(tmp_path):
    root = _envs(tmp_path, "kolla", files=("configuration.yml", "secrets.yml"))
    with pytest.raises(
        RenderError, match="images.yml missing; this environment cannot be applied"
    ):
        render_batch("h", {"names": []}, "/inv", build_stack("kolla", root), "pw")


def test_render_batch_is_one_argv_run_with_neutral_cwd(tmp_path, mocker):
    # Review focus 5 and the one-run-per-stack requirement.
    root = _envs(tmp_path, "kolla")
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append((cmd, kwargs))
        args = json.loads(cmd[cmd.index("-a") + 1])
        with open(args["dest"], "w") as fp:
            json.dump({"values": {}, "closures": {}}, fp)
        return mocker.Mock(returncode=0, stdout="", stderr="")

    mocker.patch.object(inventory.subprocess, "run", side_effect=fake_run)
    render_batch(
        "node;rm -rf /",
        {"names": ["a"], "secrets": [], "raw": {}, "raw_all": {}},
        "/inv",
        build_stack("kolla", root),
        "pw",
        facts={"ansible_hostname": "n"},
    )
    assert len(runs) == 1
    cmd, kwargs = runs[0]
    assert isinstance(cmd, list) and cmd[1] == "node;rm -rf /" and "shell" not in kwargs
    assert kwargs["cwd"] not in ("/ansible", None)
    assert kwargs["env"]["ANSIBLE_NOCOLOR"] == "1"
    # ANSIBLE_FORCE_COLOR in the caller's environment beats NOCOLOR.
    assert kwargs["env"]["ANSIBLE_FORCE_COLOR"] == "0"
    extra = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]
    # Final review I4: in a play, extra-vars outrank facts. Later -e wins,
    # so the facts file goes first.
    assert extra[0].endswith("/facts.json")
    assert [e.replace("@" + root + "/", "") for e in extra[1:]] == [
        "configuration.yml",
        "secrets.yml",
        "kolla/secrets.yml",
        "kolla/images.yml",
        "kolla/configuration.yml",
    ]


def test_render_batch_ansible_failure_raises_unsafe(tmp_path, mocker):
    root = _envs(tmp_path)
    mocker.patch.object(
        inventory.subprocess,
        "run",
        return_value=mocker.Mock(returncode=4, stdout="", stderr="boom"),
    )
    with pytest.raises(RenderError, match="boom") as exc:
        render_batch("h", {"names": []}, "/inv", build_stack(None, root), "pw")
    assert exc.value.safe is False


def test_own_render_errors_are_safe(tmp_path):
    root = _envs(tmp_path, "kolla", files=("configuration.yml", "secrets.yml"))
    with pytest.raises(RenderError) as exc:
        render_batch("h", {"names": []}, "/inv", build_stack("kolla", root), "pw")
    assert exc.value.safe is True


def test_load_yaml_unsafe_is_a_literal_string(tmp_path):
    # Final review I3: !unsafe made the command exit 1 (ConstructorError).
    from osism.utils.template_deps import references

    f = tmp_path / "c.yml"
    f.write_text("literal: !unsafe '{{ x }}'\n")
    loaded = load_yaml(str(f), "pw")
    assert loaded == {"literal": "{{ x }}"}
    assert references(loaded["literal"]) == references("plain")
    assert json.loads(json.dumps(loaded)) == {"literal": "{{ x }}"}
