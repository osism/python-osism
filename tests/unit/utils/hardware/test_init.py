# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the small helpers in ``osism.utils.hardware``."""

import pytest

from osism.utils.hardware import natural_key, normalize_date_code, normalize_mac


@pytest.mark.parametrize(
    "value",
    ["AA:BB:CC:00:11:22", "aa-bb-cc-00-11-22", "aabb.cc00.1122", " aabbcc001122 "],
)
def test_normalize_mac_accepts_common_spellings(value):
    assert normalize_mac(value) == "aa:bb:cc:00:11:22"


@pytest.mark.parametrize(
    "value",
    [None, "", "Ethernet0", "aa:bb:cc", "00:00:00:00:00:00", "zz:bb:cc:00:11:22"],
)
def test_normalize_mac_rejects_non_addresses(value):
    assert normalize_mac(value) is None


def test_natural_key_orders_numbers_by_value():
    names = ["Ethernet10", "Ethernet2", "Ethernet1", "eth0", "ens1f1", "ens1f0"]

    assert sorted(names, key=natural_key) == [
        "Ethernet1",
        "Ethernet2",
        "Ethernet10",
        "ens1f0",
        "ens1f1",
        "eth0",
    ]


def test_natural_key_handles_none_and_mixed_values():
    assert sorted([None, "b", "1", "a"], key=natural_key) == [None, "1", "a", "b"]


@pytest.mark.parametrize(
    "value,expected",
    [
        # ethtool -m: the EEPROM field, with and without a lot code
        ("220907", "2022-09-07"),
        ("220907  ", "2022-09-07"),
        ("220907A1", "2022-09-07"),
        # Enterprise SONiC and community SONiC
        ("2022-09-07T00:00:00+00:00", "2022-09-07"),
        ("2020-07-24 A1", "2020-07-24"),
        ("2020-07-24", "2020-07-24"),
        # Not a date: left alone
        ("991332", "991332"),
        ("week 12", "week 12"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_date_code(value, expected):
    assert normalize_date_code(value) == expected
