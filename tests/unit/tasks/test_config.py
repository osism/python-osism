# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Celery ``Config`` broker/result-backend precedence.

``Config.broker_url`` and ``Config.result_backend`` are class attributes
resolved once at import time from the (also import-frozen) ``settings.REDIS_*``
values. Asserting the precedence logic therefore requires reloading both
``osism.settings`` and ``osism.tasks`` after changing the environment --
``monkeypatch.setenv`` alone would leave the cached attributes in place and the
test would pass for the wrong reason.
"""

import importlib

import pytest

import osism.settings
import osism.tasks

# Environment variables that feed ``broker_url`` / ``result_backend``.
CELERY_ENV = (
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
)


@pytest.fixture(autouse=True)
def _restore_task_config():
    """Reload ``settings`` / ``osism.tasks`` after each test.

    Without this the reloaded modules would leak a test's custom environment
    (frozen into ``Config``) into later tests.
    """
    yield
    importlib.reload(osism.settings)
    importlib.reload(osism.tasks)


@pytest.fixture
def config_with_env(monkeypatch):
    """Return a fresh ``Config`` after applying ``env`` and reloading modules."""

    def _build(env):
        for key in CELERY_ENV:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        importlib.reload(osism.settings)
        importlib.reload(osism.tasks)
        return osism.tasks.Config

    return _build


def test_broker_url_derived_from_redis_settings(config_with_env):
    """Without an override, ``broker_url`` is derived from ``REDIS_*``."""
    config = config_with_env(
        {"REDIS_HOST": "redis.example", "REDIS_PORT": "6399", "REDIS_DB": "5"}
    )

    assert config.broker_url == "redis://redis.example:6399/5"


def test_celery_broker_url_overrides_derived(config_with_env):
    """``CELERY_BROKER_URL`` wins over the derived ``REDIS_*`` URL."""
    config = config_with_env(
        {
            "REDIS_HOST": "redis.example",
            "REDIS_PORT": "6399",
            "REDIS_DB": "5",
            "CELERY_BROKER_URL": "redis://broker.example:6380/2",
        }
    )

    assert config.broker_url == "redis://broker.example:6380/2"


def test_result_backend_overrides_independently(config_with_env):
    """``CELERY_RESULT_BACKEND`` overrides independently of the broker URL."""
    config = config_with_env(
        {
            "CELERY_BROKER_URL": "redis://broker.example:6380/2",
            "CELERY_RESULT_BACKEND": "redis://backend.example:6381/3",
        }
    )

    assert config.broker_url == "redis://broker.example:6380/2"
    assert config.result_backend == "redis://backend.example:6381/3"


def test_result_backend_defaults_to_broker_url(config_with_env):
    """Absent ``CELERY_RESULT_BACKEND``, ``result_backend`` equals ``broker_url``."""
    config = config_with_env(
        {"REDIS_HOST": "redis", "REDIS_PORT": "6379", "REDIS_DB": "0"}
    )

    assert config.result_backend == config.broker_url


def test_task_track_started_is_true(config_with_env):
    """``task_track_started`` is the boolean ``True`` (not a truthy 1-tuple)."""
    config = config_with_env({})

    assert config.task_track_started is True
