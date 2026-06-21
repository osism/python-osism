# SPDX-License-Identifier: Apache-2.0

"""Tests for ``osism/main.py`` — the ``osism`` console-script entry point.

Two units are covered:

- ``OsismApp.__init__`` wires loguru's stderr sink and the cliff ``App`` (the
  ``osism.commands`` entry-point namespace, deferred help, parser description,
  and the ``--version`` action). Every test that constructs ``OsismApp``
  requests the ``mock_logger`` fixture so the process-global loguru
  configuration is patched *before* construction and never mutated for real.
- ``main`` constructs the app once, forwards ``argv`` unchanged, and returns
  the app's exit code.

``main``'s ``argv=sys.argv[1:]`` default is evaluated once at import time, so
the default is frozen and reflects the arguments pytest itself was invoked
with. Every test therefore passes ``argv`` explicitly. The ``main`` tests run
only against a mocked ``OsismApp``; the real ``app.run([])`` is never called,
as cliff would drop into its interactive shell on an empty argv.
"""

import sys

import pytest

from osism.main import OsismApp, main, __version__


@pytest.fixture
def mock_logger(mocker):
    """Patch the loguru ``logger`` imported by ``osism.main``.

    Returns the mock so tests can assert the sink configuration without
    removing the loguru handlers other tests rely on.
    """
    return mocker.patch("osism.main.logger")


# ---------------------------------------------------------------------------
# OsismApp.__init__ — logging setup
# ---------------------------------------------------------------------------


def test_init_removes_default_loguru_handler(mock_logger):
    OsismApp()
    mock_logger.remove.assert_called_once_with()


def test_init_adds_stderr_sink_with_expected_config(mock_logger):
    OsismApp()

    mock_logger.add.assert_called_once()
    call_args = mock_logger.add.call_args
    assert call_args.args[0] is sys.stderr
    assert call_args.kwargs["level"] == "INFO"
    assert call_args.kwargs["colorize"] is True
    assert call_args.kwargs["format"].startswith(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green>"
    )


# ---------------------------------------------------------------------------
# OsismApp.__init__ — cliff wiring
# ---------------------------------------------------------------------------


def test_init_wires_osism_commands_namespace(mock_logger):
    assert OsismApp().command_manager.namespace == "osism.commands"


def test_init_enables_deferred_help(mock_logger):
    assert OsismApp().deferred_help is True


def test_init_sets_parser_description(mock_logger):
    assert OsismApp().parser.description == "OSISM manager interface"


def test_init_succeeds_when_version_is_none(mock_logger, mocker):
    # osism.__version__ (pbr) is None when package metadata is unavailable
    # (osism/__init__.py fallback); construction must still succeed.
    mocker.patch("osism.main.__version__", None)
    assert isinstance(OsismApp(), OsismApp)


def test_version_option_exits_zero(mock_logger, capsys):
    app = OsismApp()
    with pytest.raises(SystemExit) as excinfo:
        app.run(["--version"])
    assert excinfo.value.code == 0
    # cliff renders the version line as "<prog> <version>"; the prog name comes
    # from sys.argv[0] (so it is "pytest" here, "osism" only via the console
    # script). Assert on the package version that main.py wires in, which is
    # what this entry point actually controls.
    assert str(__version__) in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main — construct once, forward argv, return the app's exit code
# ---------------------------------------------------------------------------


def test_main_constructs_app_once_and_forwards_argv(mocker):
    mock_app_cls = mocker.patch("osism.main.OsismApp")

    main(["reconciler", "sync"])

    mock_app_cls.assert_called_once_with()
    mock_app_cls.return_value.run.assert_called_once_with(["reconciler", "sync"])


@pytest.mark.parametrize("rc", [42, 0])
def test_main_returns_app_run_result(mocker, rc):
    mock_app_cls = mocker.patch("osism.main.OsismApp")
    mock_app_cls.return_value.run.return_value = rc

    assert main(["reconciler", "sync"]) == rc


def test_main_forwards_empty_argv(mocker):
    # Only the mocked app sees the empty argv — never the real OsismApp, which
    # would enter cliff's interactive shell on an empty argument list.
    mock_app_cls = mocker.patch("osism.main.OsismApp")

    main([])

    mock_app_cls.return_value.run.assert_called_once_with([])
