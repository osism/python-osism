# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the marker and sha256 body validators in osism.commands.manage."""

from osism.commands.manage import _is_sha256, _validate_marker

# --- Marker validator (M1-M9) ---


def test_m1_validates_octavia_marker():
    assert (
        _validate_marker("2026-04-12 octavia-amphora-haproxy-2024.2.20260412.qcow2")
        is True
    )


def test_m2_validates_capi_marker():
    assert _validate_marker("2026-04-12 ubuntu-2404-kube-v1.33.1.qcow2") is True


def test_m3_rejects_xml_error_body():
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>InternalError</Code></Error>'
    assert _validate_marker(body) is False


def test_m4_rejects_empty_body():
    assert _validate_marker("") is False


def test_m5_rejects_single_token():
    assert _validate_marker("2026-04-12") is False


def test_m6_rejects_wrong_suffix():
    assert _validate_marker("2026-04-12 random.txt") is False


def test_m7_rejects_wrong_date_shape():
    assert _validate_marker("yesterday octavia-amphora-foo.qcow2") is False


def test_m8_accepts_unfamiliar_qcow2_name():
    """Production-diversity: validator must accept names CI has never seen."""
    assert _validate_marker("2026-04-12 some-future-amphora-variant.qcow2") is True


def test_m9_rejects_filename_with_internal_whitespace():
    """Second token must be a single \\S+\\.qcow2 token."""
    assert _validate_marker("2026-04-12 image-with-spaces in-name.qcow2") is False


# --- Checksum validator (S1-S6) ---


def test_s1_accepts_lowercase_hex_sha256():
    body = "8ce3f3" + "a" * 58 + "  octavia-amphora-haproxy-2024.2.20260412.qcow2"
    assert _is_sha256(body) is True


def test_s2_rejects_xml_body():
    assert _is_sha256('<?xml version="1.0"?> <Error>') is False


def test_s3_rejects_empty_body():
    assert _is_sha256("") is False


def test_s4_rejects_non_hex_64_char_first_token():
    assert (
        _is_sha256("not-hex-but-64-chars-long-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        is False
    )


def test_s5_rejects_too_short_hex():
    assert _is_sha256("abc123") is False


def test_s6_rejects_uppercase_hex():
    assert _is_sha256("ABCDEF" + "0" * 58) is False
