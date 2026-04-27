# SPDX-License-Identifier: Apache-2.0

"""HTTP fetch helper with retry, content validation, and structured logging."""

from __future__ import annotations

import time
from typing import Callable, Optional

import requests
from loguru import logger

RETRYABLE_STATUSES = {408, 429} | set(range(500, 600))


def fetch_text(
    url: str,
    *,
    delays: tuple[float, ...] = (2.0, 4.0, 8.0),
    validate: Optional[Callable[[str], bool]] = None,
) -> str:
    """Fetch ``url`` as text with retry on transient failures."""
    if not delays:
        raise ValueError(
            "fetch_text requires non-empty delays; the helper exists to retry"
        )

    attempts = len(delays) + 1
    last_failure: Optional[BaseException] = None

    for n in range(1, attempts + 1):
        logger.info(f"fetch_text url={url} attempt={n}/{attempts}")
        try:
            response = requests.get(url)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status not in RETRYABLE_STATUSES:
                logger.info(
                    f"fetch_text url={url} attempt={n}/{attempts} status={status} non-retryable"
                )
                raise
            last_failure = exc
            if n < attempts:
                logger.info(
                    f"fetch_text url={url} attempt={n}/{attempts} status={status} "
                    f"retrying in {delays[n - 1]}s"
                )
                time.sleep(delays[n - 1])
                continue
            logger.info(
                f"fetch_text url={url} attempt={n}/{attempts} status={status} giving up"
            )
            raise
        except requests.RequestException as exc:
            last_failure = exc
            if n < attempts:
                logger.info(
                    f"fetch_text url={url} attempt={n}/{attempts} "
                    f"error={type(exc).__name__}({exc}) retrying in {delays[n - 1]}s"
                )
                time.sleep(delays[n - 1])
                continue
            logger.info(
                f"fetch_text url={url} attempt={n}/{attempts} "
                f"error={type(exc).__name__}({exc}) giving up"
            )
            raise

        status = response.status_code
        text = response.text
        if validate is not None and not validate(text):
            last_failure = ValueError(f"fetch_text validate rejected body for {url!r}")
            excerpt = text[:40].replace("\n", "\\n")
            if n < attempts:
                logger.info(
                    f"fetch_text url={url} attempt={n}/{attempts} status={status} "
                    f"invalid_body={excerpt!r} retrying in {delays[n - 1]}s"
                )
                time.sleep(delays[n - 1])
                continue
            logger.info(
                f"fetch_text url={url} attempt={n}/{attempts} status={status} "
                f"invalid_body={excerpt!r} giving up"
            )
            raise last_failure

        logger.info(f"fetch_text url={url} attempt={n}/{attempts} status={status} ok")
        return text

    raise RuntimeError("fetch_text loop exited without return or raise")
