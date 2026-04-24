# SPDX-License-Identifier: Apache-2.0

from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path


def _make_base(tmp_path):
    base = tmp_path / "hosts.yml"
    base.write_text("---\n")
    return base


def test_get_inventory_path_minified_preferred(tmp_path):
    base = _make_base(tmp_path)
    minified = tmp_path / "hosts-minified.yml"
    minified.write_text("---\n")

    assert get_inventory_path(str(base)) == str(minified)


def test_get_inventory_path_minified_ignored_when_not_preferred(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "hosts-minified.yml").write_text("---\n")

    assert get_inventory_path(str(base), prefer_minified=False) == str(base)


def test_get_inventory_path_fast_directory(tmp_path):
    base = _make_base(tmp_path)
    fast = tmp_path / "fast"
    fast.mkdir()

    assert get_inventory_path(str(base)) == str(fast)


def test_get_inventory_path_fallback_to_base(tmp_path):
    base = _make_base(tmp_path)

    assert get_inventory_path(str(base)) == str(base)


def test_get_inventory_path_minified_wins_over_fast(tmp_path):
    base = _make_base(tmp_path)
    minified = tmp_path / "hosts-minified.yml"
    minified.write_text("---\n")
    (tmp_path / "fast").mkdir()

    assert get_inventory_path(str(base), prefer_minified=True) == str(minified)


def test_get_inventory_path_fast_wins_when_minified_not_preferred(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "hosts-minified.yml").write_text("---\n")
    fast = tmp_path / "fast"
    fast.mkdir()

    assert get_inventory_path(str(base), prefer_minified=False) == str(fast)


def test_get_inventory_path_fast_as_file_is_ignored(tmp_path):
    base = _make_base(tmp_path)
    (tmp_path / "fast").write_text("not a directory\n")

    assert get_inventory_path(str(base)) == str(base)


def test_get_hosts_from_inventory_hostvars_only():
    data = {
        "_meta": {"hostvars": {"host-b": {}, "host-a": {}}},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_groups_only():
    data = {
        "webservers": {"hosts": ["host-b", "host-a"]},
        "dbservers": {"hosts": ["host-c"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b", "host-c"]


def test_get_hosts_from_inventory_union_deduplicated():
    data = {
        "_meta": {"hostvars": {"host-a": {}, "host-b": {}}},
        "webservers": {"hosts": ["host-b", "host-c"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b", "host-c"]


def test_get_hosts_from_inventory_empty():
    assert get_hosts_from_inventory({}) == []


def test_get_hosts_from_inventory_ignores_non_dict_and_missing_hosts():
    data = {
        "_meta": {"hostvars": {"host-a": {}}},
        "all": ["not", "a", "dict"],
        "empty_group": {},
        "group_with_children_only": {"children": ["other"]},
        "webservers": {"hosts": ["host-b"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_result_is_sorted():
    data = {
        "_meta": {"hostvars": {"zeta": {}, "alpha": {}}},
        "group": {"hosts": ["mike", "bravo"]},
    }

    assert get_hosts_from_inventory(data) == ["alpha", "bravo", "mike", "zeta"]


def test_get_hosts_from_inventory_meta_without_hostvars_key():
    data = {
        "_meta": {},
        "webservers": {"hosts": ["host-a"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a"]


def test_get_hosts_from_inventory_duplicates_within_group_deduplicated():
    data = {
        "webservers": {"hosts": ["host-a", "host-a", "host-b"]},
    }

    assert get_hosts_from_inventory(data) == ["host-a", "host-b"]


def test_get_hosts_from_inventory_group_with_hosts_and_children():
    data = {
        "webservers": {
            "hosts": ["host-a"],
            "children": ["other-group"],
        },
    }

    assert get_hosts_from_inventory(data) == ["host-a"]
