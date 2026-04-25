# SPDX-License-Identifier: Apache-2.0

import textwrap

import pytest
import yaml

from osism.data import playbooks


@pytest.fixture(autouse=True)
def _reset_module_caches():
    playbooks._reset_caches()
    yield
    playbooks._reset_caches()


@pytest.fixture
def playbook_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("osism.data.playbooks._PLAYBOOK_DIR", tmp_path)
    return tmp_path


def _write_yaml(directory, filename, content):
    (directory / filename).write_text(textwrap.dedent(content))


def test_load_merges_multiple_yaml_files(playbook_dir):
    _write_yaml(
        playbook_dir,
        "alpha.yml",
        """\
        role-a:
          env: alpha
        """,
    )
    _write_yaml(
        playbook_dir,
        "beta.yml",
        """\
        role-b:
          env: beta
        """,
    )

    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT == {
        "role-a": {"env": "alpha"},
        "role-b": {"env": "beta"},
    }


def test_load_runtime_map_uses_filename_stem(playbook_dir):
    _write_yaml(
        playbook_dir,
        "alpha.yml",
        """\
        role-a: {}
        role-b: {}
        """,
    )
    _write_yaml(
        playbook_dir,
        "beta.yml",
        """\
        role-c: {}
        """,
    )

    playbooks._load_playbook_data()

    assert set(playbooks._MAP_ROLE2RUNTIME) == {"alpha", "beta"}
    assert set(playbooks._MAP_ROLE2RUNTIME["alpha"]) == {"role-a", "role-b"}
    assert set(playbooks._MAP_ROLE2RUNTIME["beta"]) == {"role-c"}


def test_load_skips_invalid_yaml_and_logs_warning(playbook_dir, mocker):
    _write_yaml(
        playbook_dir,
        "good.yml",
        """\
        role-a: {}
        """,
    )
    (playbook_dir / "bad.yml").write_text("not: [valid yaml: at all")
    warning = mocker.patch("osism.data.playbooks.logger.warning")

    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT == {"role-a": {}}
    assert set(playbooks._MAP_ROLE2RUNTIME) == {"good"}
    warning.assert_called_once()
    assert isinstance(warning.call_args.args[0], yaml.YAMLError)


def test_load_short_circuits_when_environment_already_populated(monkeypatch, mocker):
    sentinel_env = {"sentinel": "value"}
    sentinel_runtime = {"sentinel": []}
    playbooks._MAP_ROLE2ENVIRONMENT = sentinel_env
    playbooks._MAP_ROLE2RUNTIME = sentinel_runtime

    fake_dir = mocker.Mock()
    fake_dir.glob.side_effect = AssertionError(
        "_PLAYBOOK_DIR.glob() must not be invoked when caches are already populated"
    )
    monkeypatch.setattr("osism.data.playbooks._PLAYBOOK_DIR", fake_dir)

    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT is sentinel_env
    assert playbooks._MAP_ROLE2RUNTIME is sentinel_runtime


def test_load_does_not_reread_directory_after_first_load(playbook_dir):
    _write_yaml(playbook_dir, "alpha.yml", "role-a: {}\n")
    playbooks._load_playbook_data()
    first_env = playbooks._MAP_ROLE2ENVIRONMENT

    _write_yaml(playbook_dir, "beta.yml", "role-b: {}\n")
    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT is first_env
    assert "role-b" not in playbooks._MAP_ROLE2ENVIRONMENT


def test_load_with_no_yaml_files_yields_empty_maps(playbook_dir):
    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT == {}
    assert playbooks._MAP_ROLE2RUNTIME == {}


def test_load_ignores_files_without_yml_suffix(playbook_dir):
    _write_yaml(playbook_dir, "alpha.yml", "role-a: {}\n")
    (playbook_dir / "ignored.yaml").write_text("role-x: {}\n")
    (playbook_dir / "ignored.txt").write_text("role-y: {}\n")

    playbooks._load_playbook_data()

    assert playbooks._MAP_ROLE2ENVIRONMENT == {"role-a": {}}
    assert set(playbooks._MAP_ROLE2RUNTIME) == {"alpha"}


def test_getattr_environment_triggers_load(playbook_dir):
    _write_yaml(
        playbook_dir,
        "alpha.yml",
        """\
        role-a:
          env: production
        """,
    )

    assert playbooks.MAP_ROLE2ENVIRONMENT == {"role-a": {"env": "production"}}


def test_getattr_runtime_triggers_load(playbook_dir):
    _write_yaml(playbook_dir, "alpha.yml", "role-a: {}\n")

    runtime = playbooks.MAP_ROLE2RUNTIME

    assert "alpha" in runtime
    assert set(runtime["alpha"]) == {"role-a"}


def test_getattr_caches_result_in_module_globals(playbook_dir, mocker):
    _write_yaml(playbook_dir, "alpha.yml", "role-a: {}\n")
    spy = mocker.spy(playbooks, "_load_playbook_data")

    first = playbooks.MAP_ROLE2ENVIRONMENT
    second = playbooks.MAP_ROLE2ENVIRONMENT

    assert first is second
    assert "MAP_ROLE2ENVIRONMENT" in playbooks.__dict__
    assert spy.call_count == 1


def test_getattr_runtime_caches_result_in_module_globals(playbook_dir, mocker):
    _write_yaml(playbook_dir, "alpha.yml", "role-a: {}\n")
    spy = mocker.spy(playbooks, "_load_playbook_data")

    first = playbooks.MAP_ROLE2RUNTIME
    second = playbooks.MAP_ROLE2RUNTIME

    assert first is second
    assert "MAP_ROLE2RUNTIME" in playbooks.__dict__
    assert spy.call_count == 1


def test_getattr_unknown_attribute_raises_attribute_error():
    with pytest.raises(
        AttributeError,
        match=r"module 'osism\.data\.playbooks' has no attribute 'does_not_exist'",
    ):
        playbooks.does_not_exist
