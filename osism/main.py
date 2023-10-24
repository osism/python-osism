# SPDX-License-Identifier: Apache-2.0

import sys

from cliff.app import App
from cliff.commandmanager import CommandManager
from loguru import logger

from . import __version__


class OsismApp(App):
    def __init__(self):
        level = "INFO"
        log_fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<level>{message}</level>"
        )

        logger.remove()
        logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

        super(OsismApp, self).__init__(
            description="OSISM manager interface",
            version=__version__,
            command_manager=CommandManager("osism.commands"),
            deferred_help=True,
        )


def main(argv=sys.argv[1:]):
    app = OsismApp()
    result = app.run(argv)
    return result


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
