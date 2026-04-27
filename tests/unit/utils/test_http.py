# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.http.fetch_text`` retry and validation behavior."""

import logging as _logging
from unittest.mock import MagicMock, patch

import pytest
import requests
from loguru import logger as _loguru_logger

from osism.utils.http import fetch_text


def _make_response(status_code: int, text: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_fetch_text_first_attempt_success():
    """Test #1: Happy path, first attempt succeeds. No sleep."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ) as mock_sleep:
        mock_get.return_value = _make_response(200, "hello\n")
        result = fetch_text("https://example.com/x")
        assert result == "hello\n"
        assert mock_get.call_count == 1
        assert mock_sleep.call_count == 0


def test_fetch_text_503_then_200():
    """Test #2: 503 then 200. One sleep at delays[0]."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ) as mock_sleep:
        mock_get.side_effect = [
            _make_response(503, "<?xml..."),
            _make_response(200, "ok-body"),
        ]
        result = fetch_text("https://example.com/x", delays=(2.0,))
        assert result == "ok-body"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(2.0)


def test_fetch_text_all_retryable_http_errors():
    """Test #5: All attempts return 503. Raises HTTPError. Sleeps (2, 4, 8)."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ) as mock_sleep:
        mock_get.return_value = _make_response(503, "<?xml...")
        with pytest.raises(requests.HTTPError):
            fetch_text("https://example.com/x", delays=(2.0, 4.0, 8.0))
        assert mock_get.call_count == 4
        assert [c.args[0] for c in mock_sleep.call_args_list] == [2.0, 4.0, 8.0]


def test_fetch_text_408_then_200():
    """Test #10: 408 in retryable set."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(408, "<?xml..."),
            _make_response(200, "ok"),
        ]
        assert fetch_text("https://example.com/x", delays=(1.0,)) == "ok"


def test_fetch_text_429_then_200():
    """Test #11: 429 in retryable set."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(429, "<?xml..."),
            _make_response(200, "ok"),
        ]
        assert fetch_text("https://example.com/x", delays=(1.0,)) == "ok"


def test_fetch_text_connection_error_then_200():
    """Test #3: ConnectionError then 200. Retry path covered."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            requests.ConnectionError("boom"),
            _make_response(200, "ok"),
        ]
        assert fetch_text("https://example.com/x", delays=(1.0,)) == "ok"
        assert mock_get.call_count == 2


def test_fetch_text_404_fails_fast():
    """Test #9: 404 raises HTTPError immediately. No sleep, no second call."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ) as mock_sleep:
        mock_get.return_value = _make_response(404, "not found")
        with pytest.raises(requests.HTTPError):
            fetch_text("https://example.com/x", delays=(2.0, 4.0, 8.0))
        assert mock_get.call_count == 1
        assert mock_sleep.call_count == 0


def test_fetch_text_validate_fail_then_pass():
    """Test #4: Validate fails on attempt 1 (XML body), succeeds on attempt 2."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(200, '<?xml version="1.0"?>'),
            _make_response(200, "good-body"),
        ]

        def is_good(b):
            return b == "good-body"

        assert (
            fetch_text("https://example.com/x", delays=(1.0,), validate=is_good)
            == "good-body"
        )


def test_fetch_text_all_validate_fail_raises_value_error():
    """Test #6: All attempts return 200 with invalid body. Raises ValueError."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.return_value = _make_response(200, "<?xml...")

        def always_false(_body):
            return False

        with pytest.raises(ValueError):
            fetch_text(
                "https://example.com/x", delays=(1.0, 2.0), validate=always_false
            )
        assert mock_get.call_count == 3


def test_fetch_text_empty_delays_raises_immediately():
    """Test #7: delays=() raises ValueError at call time."""
    with pytest.raises(ValueError):
        fetch_text("https://example.com/x", delays=())


def test_fetch_text_mixed_validate_fail_last():
    """Test #12: 503 -> 200 invalid -> ConnectionError -> 200 invalid -> ValueError."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(503, "<?xml..."),
            _make_response(200, "<?xml..."),
            requests.ConnectionError("boom"),
            _make_response(200, "<?xml..."),
        ]
        with pytest.raises(ValueError):
            fetch_text(
                "https://example.com/x",
                delays=(0.0, 0.0, 0.0),
                validate=lambda b: not b.startswith("<?xml"),
            )


def test_fetch_text_mixed_network_error_last():
    """Test #13: 503 -> 200 invalid -> 200 invalid -> ConnectionError -> ConnectionError."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(503, "<?xml..."),
            _make_response(200, "<?xml..."),
            _make_response(200, "<?xml..."),
            requests.ConnectionError("boom"),
        ]
        with pytest.raises(requests.ConnectionError):
            fetch_text(
                "https://example.com/x",
                delays=(0.0, 0.0, 0.0),
                validate=lambda b: not b.startswith("<?xml"),
            )


def test_fetch_text_mixed_http_error_last():
    """Test #14: 200 invalid -> ConnectionError -> 200 invalid -> 503 -> HTTPError(503)."""
    with patch("osism.utils.http.requests.get") as mock_get, patch(
        "osism.utils.http.time.sleep"
    ):
        mock_get.side_effect = [
            _make_response(200, "<?xml..."),
            requests.ConnectionError("boom"),
            _make_response(200, "<?xml..."),
            _make_response(503, "<?xml..."),
        ]
        with pytest.raises(requests.HTTPError) as exc_info:
            fetch_text(
                "https://example.com/x",
                delays=(0.0, 0.0, 0.0),
                validate=lambda b: not b.startswith("<?xml"),
            )
        assert exc_info.value.response.status_code == 503


def _capture_loguru_messages():
    """Bridge loguru -> stdlib logging so pytest's caplog fixture sees the records.

    Returns the handler_id so the caller can remove it during cleanup.
    """
    return _loguru_logger.add(
        lambda msg: _logging.getLogger("loguru").info(msg.record["message"]),
        format="{message}",
    )


def test_fetch_text_logs_two_lines_per_attempt(caplog):
    """Test #8: Two log lines per attempt; outcome line for winner has ' ok'."""
    handler_id = _capture_loguru_messages()
    try:
        with patch("osism.utils.http.requests.get") as mock_get, patch(
            "osism.utils.http.time.sleep"
        ):
            mock_get.side_effect = [
                _make_response(503, "<?xml..."),
                _make_response(200, "ok"),
            ]
            with caplog.at_level(_logging.INFO, logger="loguru"):
                fetch_text("https://example.com/x", delays=(1.0,))
    finally:
        _loguru_logger.remove(handler_id)

    fetch_text_lines = [r.message for r in caplog.records if "fetch_text" in r.message]
    # Two attempts, two lines each => four lines
    assert len(fetch_text_lines) == 4
    # First attempt: start + retry-on-status
    assert "attempt=1/2" in fetch_text_lines[0]
    assert "status=503" in fetch_text_lines[1]
    assert "retrying" in fetch_text_lines[1]
    # Second attempt: start + ok
    assert "attempt=2/2" in fetch_text_lines[2]
    assert " ok" in fetch_text_lines[3]
    assert "attempt=2/2" in fetch_text_lines[3]


def test_fetch_text_404_emits_non_retryable_outcome_log(caplog):
    """Test #15: 404 emits a start line and a status=404 non-retryable outcome line."""
    handler_id = _capture_loguru_messages()
    try:
        with patch("osism.utils.http.requests.get") as mock_get, patch(
            "osism.utils.http.time.sleep"
        ) as mock_sleep:
            mock_get.return_value = _make_response(404, "not found")
            with caplog.at_level(_logging.INFO, logger="loguru"):
                with pytest.raises(requests.HTTPError):
                    fetch_text("https://example.com/x", delays=(2.0, 4.0, 8.0))
            assert mock_sleep.call_count == 0
    finally:
        _loguru_logger.remove(handler_id)

    fetch_text_lines = [r.message for r in caplog.records if "fetch_text" in r.message]
    # Exactly two lines: start + non-retryable outcome
    assert len(fetch_text_lines) == 2
    assert "attempt=1/4" in fetch_text_lines[0]
    assert "status=404" in fetch_text_lines[1]
    assert "non-retryable" in fetch_text_lines[1]
