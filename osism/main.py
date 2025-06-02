# SPDX-License-Identifier: Apache-2.0

import os
import sys
from typing import List, Optional

from cliff.app import App
from cliff.commandmanager import CommandManager
from loguru import logger

from . import __version__

# Constants
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<level>{message}</level>"
)
APP_DESCRIPTION = "OSISM manager interface"
COMMAND_NAMESPACE = "osism.commands"


class AppConfig:
    """Configuration class for the OSISM application."""

    def __init__(self):
        self.log_level: str = os.getenv("OSISM_LOG_LEVEL", DEFAULT_LOG_LEVEL)
        self.log_format: str = os.getenv("OSISM_LOG_FORMAT", DEFAULT_LOG_FORMAT)
        self.log_colorize: bool = (
            os.getenv("OSISM_LOG_COLORIZE", "true").lower() == "true"
        )
        self.description: str = APP_DESCRIPTION
        self.version: str = __version__
        self.command_namespace: str = COMMAND_NAMESPACE

    def validate(self) -> None:
        """Validate configuration values."""
        valid_log_levels = [
            "TRACE",
            "DEBUG",
            "INFO",
            "SUCCESS",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ]
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(
                f"Invalid log level: {self.log_level}. Must be one of: {', '.join(valid_log_levels)}"
            )


def configure_logger(config: AppConfig) -> None:
    """Configure the loguru logger with the given configuration.

    Args:
        config: Application configuration object
    """
    logger.remove()
    logger.add(
        sys.stderr,
        format=config.log_format,
        level=config.log_level.upper(),
        colorize=config.log_colorize,
    )


class OsismApp(App):
    """Main OSISM application class."""

    def __init__(self):
        """Initialize the OSISM application."""
        self.config = AppConfig()

        try:
            self.config.validate()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            sys.exit(1)

        configure_logger(self.config)

        super(OsismApp, self).__init__(
            description=self.config.description,
            version=self.config.version,
            command_manager=CommandManager(self.config.command_namespace),
            deferred_help=True,
        )

        logger.debug(f"Initialized OSISM app version {self.config.version}")

    def initialize_app(self, argv: List[str]) -> None:
        """Initialize the application.

        Args:
            argv: Command line arguments
        """
        logger.debug(f"Initializing app with arguments: {argv}")
        super().initialize_app(argv)

    def prepare_to_run_command(self, cmd):
        """Prepare to run a command.

        Args:
            cmd: Command object about to be run
        """
        logger.debug(f"Preparing to run command: {cmd.__class__.__name__}")

    def clean_up(self, cmd, result, err):
        """Clean up after running a command.

        Args:
            cmd: Command that was run
            result: Result of the command
            err: Any error that occurred
        """
        logger.debug(f"Cleaning up after command: {cmd.__class__.__name__}")
        if err:
            logger.error(f"Command failed with error: {err}")


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the OSISM CLI.

    Args:
        argv: Command line arguments. Defaults to sys.argv[1:]

    Returns:
        Exit code
    """
    if argv is None:
        argv = sys.argv[1:]

    try:
        app = OsismApp()
        result = app.run(argv)
        return result
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
